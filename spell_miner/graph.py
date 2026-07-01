from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db2 import DB2Store, SpellEffect


DAMAGE_EFFECT_CODES = {"2", "6", "58"}
AURA_WORDS = ("aura", "apply", "periodic", "buff", "debuff")
DAMAGE_WORDS = ("damage", "伤害", "造成", "击中")


@dataclass(frozen=True)
class KnownEdge:
    source: int
    target: int
    edge_type: str
    note: str = ""


def slugify(text: str, fallback: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", text.strip()).strip("_")
    return text or fallback


def load_seed_file(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def parse_known_edges(seed_data: dict[str, Any]) -> list[KnownEdge]:
    edges: list[KnownEdge] = []
    for item in seed_data.get("known_edges", []):
        try:
            source = int(item["from"])
            target = int(item["to"])
        except (KeyError, TypeError, ValueError):
            continue
        edges.append(
            KnownEdge(
                source=source,
                target=target,
                edge_type=str(item.get("type", "manual")),
                note=str(item.get("note", "")),
            )
        )
    return edges


class SpellGraphMiner:
    def __init__(self, store: DB2Store):
        self.store = store
        self.names = store.spell_names()
        self.descriptions = store.spell_descriptions()
        self.aura_descriptions = store.aura_descriptions()
        self.effects: dict[int, list[Any]] = {}
        self.sections = store.journal_sections()
        self.name_index = self._build_name_index()

    def _build_name_index(self) -> dict[str, set[int]]:
        index: dict[str, set[int]] = {}
        for spell_id, name in self.names.items():
            key = name.strip().lower()
            if key:
                index.setdefault(key, set()).add(spell_id)
        return index

    def related_by_name(self, spell_id: int) -> set[int]:
        name = self.names.get(spell_id, "").strip().lower()
        if not name:
            return set()
        return set(self.name_index.get(name, set())) - {spell_id}

    def mine(
        self,
        seed_ids: set[int],
        keywords: list[str],
        encounter_ids: set[int],
        known_edges: list[KnownEdge],
        max_depth: int,
        include_name_siblings: bool,
    ) -> dict[str, Any]:
        entry_roots = set(seed_ids)
        entry_roots.update(self.store.search_spell_ids(keywords))
        entry_roots.update(self.store.encounter_spell_ids(encounter_ids))
        graph_roots = set(entry_roots)
        graph_roots.update(edge.source for edge in known_edges)
        graph_roots.update(edge.target for edge in known_edges)
        if include_name_siblings:
            sibling_roots = set(graph_roots)
            for spell_id in graph_roots:
                sibling_roots.update(self.related_by_name(spell_id))
            graph_roots = sibling_roots

        self.effects = self.store.spell_effects_for(graph_roots, max_depth)

        edge_rows = self._collect_edges(graph_roots, known_edges, max_depth, include_name_siblings)
        spell_ids = set(graph_roots)
        for edge in edge_rows:
            spell_ids.add(edge["from"])
            spell_ids.add(edge["to"])

        spells = [self._spell_payload(spell_id, edge_rows) for spell_id in sorted(spell_ids)]
        mechanisms = self._mechanism_candidates(entry_roots or graph_roots, spell_ids, edge_rows)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "db2_dir": str(self.store.db2_dir),
                "tables": {name: str(path) for name, path in self.store.available_tables().items()},
            },
            "query": {
                "seed_ids": sorted(seed_ids),
                "keywords": keywords,
                "encounter_ids": sorted(encounter_ids),
                "max_depth": max_depth,
                "include_name_siblings": include_name_siblings,
            },
            "spells": spells,
            "edges": edge_rows,
            "mechanism_candidates": mechanisms,
        }

    def _collect_edges(
        self,
        roots: set[int],
        known_edges: list[KnownEdge],
        max_depth: int,
        include_name_siblings: bool,
    ) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        seen_edges: set[tuple[int, int, str]] = set()
        queue: deque[tuple[int, int]] = deque((spell_id, 0) for spell_id in sorted(roots))
        seen_nodes = set(roots)

        def add_edge(source: int, target: int, edge_type: str, evidence: str) -> None:
            key = (source, target, edge_type)
            if source == target or key in seen_edges:
                return
            seen_edges.add(key)
            edges.append({"from": source, "to": target, "type": edge_type, "evidence": evidence})
            if target not in seen_nodes:
                seen_nodes.add(target)
                queue.append((target, depth + 1))

        for known in known_edges:
            edges.append(
                {
                    "from": known.source,
                    "to": known.target,
                    "type": known.edge_type,
                    "evidence": known.note or "manual mapping",
                }
            )
            seen_edges.add((known.source, known.target, known.edge_type))
            seen_nodes.update({known.source, known.target})

        while queue:
            spell_id, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for effect in self.effects.get(spell_id, []):
                if effect.trigger_spell_id:
                    add_edge(
                        spell_id,
                        effect.trigger_spell_id,
                        "effect_trigger_spell",
                        self._effect_evidence(effect),
                    )
            if include_name_siblings:
                for sibling_id in sorted(self.related_by_name(spell_id)):
                    add_edge(spell_id, sibling_id, "same_spell_name", self.names.get(spell_id, ""))
        return edges

    def _effect_evidence(self, effect: SpellEffect) -> str:
        parts = []
        if effect.effect_index is not None:
            parts.append(f"index={effect.effect_index}")
        if effect.effect:
            parts.append(f"effect={effect.effect}")
        if effect.aura:
            parts.append(f"aura={effect.aura}")
        return ", ".join(parts) or "SpellEffect row"

    def _spell_payload(self, spell_id: int, edges: list[dict[str, Any]]) -> dict[str, Any]:
        incoming = [edge for edge in edges if edge["to"] == spell_id]
        outgoing = [edge for edge in edges if edge["from"] == spell_id]
        sections = [
            {
                "section_id": section.section_id,
                "encounter_id": section.encounter_id,
                "title": section.title,
                "body": section.body,
            }
            for section in self.sections
            if section.spell_id == spell_id
        ]
        return {
            "id": spell_id,
            "name": self.names.get(spell_id, ""),
            "description": self.descriptions.get(spell_id, ""),
            "aura_description": self.aura_descriptions.get(spell_id, ""),
            "roles": self._roles(spell_id, incoming, outgoing),
            "triggered_by": [edge["from"] for edge in incoming],
            "triggers": [edge["to"] for edge in outgoing],
            "journal_sections": sections,
            "effects": [self._effect_summary(effect) for effect in self.effects.get(spell_id, [])],
        }

    def _roles(
        self,
        spell_id: int,
        incoming: list[dict[str, Any]] | None = None,
        outgoing: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        incoming = incoming or []
        outgoing = outgoing or []
        roles: set[str] = set()
        if outgoing:
            roles.add("trigger")
        for edge in incoming:
            edge_type = str(edge.get("type", "")).lower()
            if "aura" in edge_type:
                roles.add("aura")
            if "damage" in edge_type:
                roles.add("damage")
        for edge in outgoing:
            edge_type = str(edge.get("type", "")).lower()
            if "trigger_damage" in edge_type:
                roles.add("aura")
        if self.aura_descriptions.get(spell_id):
            roles.add("aura")

        text = "\n".join(
            [
                self.names.get(spell_id, ""),
                self.descriptions.get(spell_id, ""),
                self.aura_descriptions.get(spell_id, ""),
            ]
        ).lower()
        if any(word in text for word in DAMAGE_WORDS):
            roles.add("damage")
        if any(word in text for word in AURA_WORDS):
            roles.add("aura")

        for effect in self.effects.get(spell_id, []):
            effect_code = str(effect.effect).strip()
            aura_code = str(effect.aura).strip()
            if effect_code in DAMAGE_EFFECT_CODES:
                roles.add("damage")
            if aura_code and aura_code not in {"0", "-1"}:
                roles.add("aura")
        if any(section.spell_id == spell_id for section in self.sections):
            roles.add("journal")
        return sorted(roles) or ["unknown"]

    def _effect_summary(self, effect: SpellEffect) -> dict[str, Any]:
        return {
            "effect_index": effect.effect_index,
            "effect": effect.effect,
            "aura": effect.aura,
            "trigger_spell_id": effect.trigger_spell_id,
        }

    def _mechanism_candidates(
        self, roots: set[int], spell_ids: set[int], edges: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        grouped_roots = sorted(roots) if roots else sorted(spell_ids)
        for root in grouped_roots:
            related = self._reachable_from(root, edges) | {root}
            names = [self.names.get(spell_id, "") for spell_id in related if self.names.get(spell_id)]
            display_name = self.names.get(root) or (names[0] if names else f"spell_{root}")
            aura_ids: list[int] = []
            damage_ids: list[int] = []
            trigger_ids: list[int] = []
            other_ids: list[int] = []
            for spell_id in sorted(related):
                roles = set(
                    self._roles(
                        spell_id,
                        [edge for edge in edges if edge["to"] == spell_id],
                        [edge for edge in edges if edge["from"] == spell_id],
                    )
                )
                if "aura" in roles:
                    aura_ids.append(spell_id)
                if "damage" in roles:
                    damage_ids.append(spell_id)
                if "trigger" in roles:
                    trigger_ids.append(spell_id)
                if not roles.intersection({"aura", "damage", "trigger"}):
                    other_ids.append(spell_id)
            candidates.append(
                {
                    "key": slugify(display_name.lower(), f"spell_{root}"),
                    "name": display_name,
                    "root_spell_ids": [root],
                    "aura_ids": aura_ids,
                    "damage_ids": damage_ids,
                    "trigger_spell_ids": trigger_ids,
                    "other_ids": other_ids,
                    "confidence": "needs_review",
                    "evidence": [
                        edge for edge in edges if edge["from"] in related and edge["to"] in related
                    ],
                }
            )
        return candidates

    def _reachable_from(self, root: int, edges: list[dict[str, Any]]) -> set[int]:
        adjacency: dict[int, set[int]] = {}
        for edge in edges:
            adjacency.setdefault(edge["from"], set()).add(edge["to"])
        seen: set[int] = set()
        queue: deque[int] = deque([root])
        while queue:
            current = queue.popleft()
            for target in adjacency.get(current, set()):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        return seen
