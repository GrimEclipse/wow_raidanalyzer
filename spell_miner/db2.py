from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TABLE_ALIASES = {
    "SpellName": ["SpellName", "spellname"],
    "SpellDescription": ["SpellDescription", "spelldescription"],
    "SpellAuraDescription": ["SpellAuraDescription", "spellauradescription"],
    "SpellEffect": ["SpellEffect", "spelleffect"],
    "JournalEncounter": ["JournalEncounter", "journalencounter"],
    "JournalEncounterSection": ["JournalEncounterSection", "journalencountersection"],
}


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def parse_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nil", "none", "null"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def first_text(row: dict[str, str], *names: str) -> str:
    normalized = {normalize_key(key): value for key, value in row.items()}
    for name in names:
        value = normalized.get(normalize_key(name))
        if value:
            return value.strip()
    return ""


def first_int(row: dict[str, str], *names: str) -> int | None:
    for name in names:
        value = first_text(row, name)
        parsed = parse_int(value)
        if parsed is not None:
            return parsed
    return None


def table_file(db2_dir: Path, table_name: str) -> Path | None:
    aliases = TABLE_ALIASES.get(table_name, [table_name])
    suffixes = [".csv", ".tsv", ".txt"]
    candidates: list[Path] = []
    for alias in aliases:
        for suffix in suffixes:
            candidates.extend(db2_dir.glob(f"{alias}{suffix}"))
            candidates.extend(db2_dir.glob(f"{alias.lower()}{suffix}"))
    return candidates[0] if candidates else None


def read_table(path: Path) -> list[dict[str, str]]:
    encodings = ["utf-8-sig", "utf-8", "gb18030"]
    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    else:
        assert last_error is not None
        raise last_error

    sample = text[:4096]
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
    except csv.Error:
        pass

    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    return [dict(row) for row in reader]


def iter_table(path: Path):
    encodings = ["utf-8-sig", "utf-8", "gb18030"]
    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                sample = handle.read(4096)
                handle.seek(0)
                delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
                except csv.Error:
                    pass
                reader = csv.DictReader(handle, delimiter=delimiter)
                for row in reader:
                    yield dict(row)
            return
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error


@dataclass(frozen=True)
class SpellEffect:
    spell_id: int
    effect_index: int | None
    effect: str
    aura: str
    trigger_spell_id: int | None
    raw: dict[str, str]


@dataclass(frozen=True)
class JournalSection:
    section_id: int
    encounter_id: int | None
    spell_id: int | None
    title: str
    body: str
    raw: dict[str, str]


class DB2Store:
    def __init__(self, db2_dir: Path):
        self.db2_dir = db2_dir
        self._tables: dict[str, list[dict[str, str]]] = {}

    def available_tables(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for table in TABLE_ALIASES:
            path = table_file(self.db2_dir, table)
            if path:
                found[table] = path
        return found

    def table(self, name: str) -> list[dict[str, str]]:
        if name not in self._tables:
            path = table_file(self.db2_dir, name)
            self._tables[name] = read_table(path) if path else []
        return self._tables[name]

    def spell_names(self) -> dict[int, str]:
        result: dict[int, str] = {}
        for row in self.table("SpellName"):
            spell_id = first_int(row, "ID", "SpellID")
            if spell_id is None:
                continue
            name = first_text(row, "Name_lang", "Name", "Name_zhCN", "Name_enUS")
            if name:
                result[spell_id] = name
        return result

    def spell_descriptions(self) -> dict[int, str]:
        result: dict[int, str] = {}
        for row in self.table("SpellDescription"):
            spell_id = first_int(row, "ID", "SpellID")
            if spell_id is None:
                continue
            description = first_text(
                row,
                "Description_lang",
                "Description",
                "Description_zhCN",
                "Description_enUS",
            )
            if description:
                result[spell_id] = description
        return result

    def aura_descriptions(self) -> dict[int, str]:
        result: dict[int, str] = {}
        for row in self.table("SpellAuraDescription"):
            spell_id = first_int(row, "ID", "SpellID")
            if spell_id is None:
                continue
            description = first_text(
                row,
                "Description_lang",
                "Description",
                "Description_zhCN",
                "Description_enUS",
            )
            if description:
                result[spell_id] = description
        return result

    def spell_effects(self) -> dict[int, list[SpellEffect]]:
        result: dict[int, list[SpellEffect]] = {}
        for row in self.table("SpellEffect"):
            spell_id = first_int(row, "SpellID", "Spell")
            if spell_id is None:
                continue
            effect = first_text(row, "Effect", "EffectType")
            aura = first_text(row, "EffectAura", "Aura", "ApplyAuraName")
            trigger = first_int(row, "EffectTriggerSpell", "TriggerSpell", "TriggeredSpellID")
            item = SpellEffect(
                spell_id=spell_id,
                effect_index=first_int(row, "EffectIndex", "Index", "EffectBaseIndex"),
                effect=effect,
                aura=aura,
                trigger_spell_id=trigger,
                raw=row,
            )
            result.setdefault(spell_id, []).append(item)
        return result

    def spell_effects_for(self, roots: Iterable[int], max_depth: int) -> dict[int, list[SpellEffect]]:
        path = table_file(self.db2_dir, "SpellEffect")
        if not path:
            return {}

        result: dict[int, list[SpellEffect]] = {}
        known = set(roots)
        frontier = set(roots)
        for _ in range(max(1, max_depth)):
            if not frontier:
                break
            next_frontier: set[int] = set()
            wanted = set(frontier)
            for row in iter_table(path):
                spell_id = first_int(row, "SpellID", "Spell")
                if spell_id not in wanted:
                    continue
                trigger = first_int(row, "EffectTriggerSpell", "TriggerSpell", "TriggeredSpellID")
                item = SpellEffect(
                    spell_id=spell_id,
                    effect_index=first_int(row, "EffectIndex", "Index", "EffectBaseIndex"),
                    effect=first_text(row, "Effect", "EffectType"),
                    aura=first_text(row, "EffectAura", "Aura", "ApplyAuraName"),
                    trigger_spell_id=trigger,
                    raw=row,
                )
                result.setdefault(spell_id, []).append(item)
                if trigger and trigger not in known:
                    known.add(trigger)
                    next_frontier.add(trigger)
            frontier = next_frontier
        return result

    def journal_sections(self) -> list[JournalSection]:
        rows = self.table("JournalEncounterSection")
        sections: list[JournalSection] = []
        for row in rows:
            section_id = first_int(row, "ID", "SectionID")
            if section_id is None:
                continue
            sections.append(
                JournalSection(
                    section_id=section_id,
                    encounter_id=first_int(row, "JournalEncounterID", "EncounterID", "JournalEncounter"),
                    spell_id=first_int(row, "SpellID", "Spell"),
                    title=first_text(row, "Title_lang", "Title", "Title_zhCN", "Title_enUS"),
                    body=first_text(row, "BodyText_lang", "BodyText", "Description", "BodyText_zhCN"),
                    raw=row,
                )
            )
        return sections

    def search_spell_ids(self, keywords: Iterable[str]) -> set[int]:
        names = self.spell_names()
        descriptions = self.spell_descriptions()
        aura_descriptions = self.aura_descriptions()
        lowered_keywords = [keyword.lower() for keyword in keywords if keyword]
        matches: set[int] = set()
        for spell_id in set(names) | set(descriptions) | set(aura_descriptions):
            haystack = "\n".join(
                [
                    names.get(spell_id, ""),
                    descriptions.get(spell_id, ""),
                    aura_descriptions.get(spell_id, ""),
                ]
            ).lower()
            if any(keyword in haystack for keyword in lowered_keywords):
                matches.add(spell_id)

        for section in self.journal_sections():
            haystack = f"{section.title}\n{section.body}".lower()
            if section.spell_id and any(keyword in haystack for keyword in lowered_keywords):
                matches.add(section.spell_id)
        return matches

    def encounter_spell_ids(self, encounter_ids: Iterable[int]) -> set[int]:
        wanted = set(encounter_ids)
        return {
            section.spell_id
            for section in self.journal_sections()
            if section.encounter_id in wanted and section.spell_id is not None
        }
