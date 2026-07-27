import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional


CATALOG_PATH = Path(__file__).resolve().parents[1] / "boss_catalog.json"


@dataclass(frozen=True)
class BossEntry:
    version: str
    raid_key: str
    raid_name: str
    boss_key: str
    boss_name: str
    plugin: str
    supported: bool = False
    disabled_reason: str = "暂未接入在线分析"
    config_schema: List[dict] = field(default_factory=list)
    order: int = 0
    english_name: str = ""
    external_key: str = ""
    aliases: List[str] = field(default_factory=list)
    arena_assets: List[dict] = field(default_factory=list)
    raid_english_name: str = ""
    raid_external_key: str = ""
    raid_aliases: List[str] = field(default_factory=list)


def load_catalog_document(path: Optional[Path] = None) -> dict:
    catalog_path = Path(path or CATALOG_PATH)
    try:
        document = json.loads(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"Boss 目录不存在：{catalog_path}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Boss 目录 JSON 无效：{catalog_path}（{error}）") from error

    if not isinstance(document, dict) or not isinstance(document.get("versions"), list):
        raise RuntimeError("Boss 目录必须包含 versions 数组。")
    return document


def build_catalog(document: Optional[dict] = None) -> List[BossEntry]:
    source = document or load_catalog_document()
    entries: List[BossEntry] = []
    identities = set()
    external_identities = set()

    for version_item in source.get("versions", []):
        version = str(version_item.get("version") or "").strip()
        if not version:
            raise RuntimeError("Boss 目录中存在缺少 version 的版本项。")
        raids = version_item.get("raids") or []
        if not isinstance(raids, list):
            raise RuntimeError(f"Boss 目录 {version} 的 raids 必须是数组。")

        for raid in raids:
            raid_key = str(raid.get("key") or "").strip()
            raid_name = str(raid.get("name") or "").strip()
            if not raid_key or not raid_name:
                raise RuntimeError(f"Boss 目录 {version} 中存在缺少 key/name 的副本。")

            for index, boss in enumerate(raid.get("bosses") or [], start=1):
                boss_key = str(boss.get("key") or "").strip()
                boss_name = str(boss.get("name") or "").strip()
                identity = (version, raid_key, boss_key)
                if not boss_key or not boss_name:
                    raise RuntimeError(f"Boss 目录 {version}/{raid_key} 中存在缺少 key/name 的 Boss。")
                if identity in identities:
                    raise RuntimeError(f"Boss 目录存在重复项：{'/'.join(identity)}")
                identities.add(identity)

                external_key = str(boss.get("externalKey") or "").strip()
                if external_key:
                    external_identity = (version, external_key)
                    if external_identity in external_identities:
                        raise RuntimeError(f"Boss 目录存在重复 externalKey：{version}/{external_key}")
                    external_identities.add(external_identity)

                supported = bool(boss.get("supported"))
                plugin = str(boss.get("plugin") or "").strip()
                if supported and not plugin:
                    raise RuntimeError(f"已启用 Boss 缺少 plugin：{'/'.join(identity)}")

                entries.append(
                    BossEntry(
                        version=version,
                        raid_key=raid_key,
                        raid_name=raid_name,
                        boss_key=boss_key,
                        boss_name=boss_name,
                        plugin=plugin,
                        supported=supported,
                        disabled_reason=str(
                            boss.get("disabledReason")
                            or ("" if supported else "暂未接入在线分析")
                        ),
                        config_schema=list(boss.get("configSchema") or []),
                        order=int(boss.get("order") or index),
                        english_name=str(boss.get("englishName") or ""),
                        external_key=external_key,
                        aliases=list(boss.get("aliases") or []),
                        arena_assets=list(boss.get("arenaAssets") or []),
                        raid_english_name=str(raid.get("englishName") or ""),
                        raid_external_key=str(raid.get("externalKey") or ""),
                        raid_aliases=list(raid.get("aliases") or []),
                    )
                )
    return entries


CATALOG_DOCUMENT = load_catalog_document()
CATALOG = build_catalog(CATALOG_DOCUMENT)


def iter_versions() -> Iterable[str]:
    seen = set()
    for entry in CATALOG:
        if entry.version not in seen:
            seen.add(entry.version)
            yield entry.version


def find_boss(version: str, raid_key: str, boss_key: str) -> BossEntry:
    for entry in CATALOG:
        if entry.version == version and entry.raid_key == raid_key and entry.boss_key == boss_key:
            return entry
    available = ", ".join(f"{item.version}/{item.raid_key}/{item.boss_key}" for item in CATALOG)
    raise ValueError(f"未找到 boss 插件：{version}/{raid_key}/{boss_key}。可用项：{available}")


def to_frontend_catalog() -> dict:
    versions = []
    for version in iter_versions():
        raids = []
        version_entries = [entry for entry in CATALOG if entry.version == version]
        for raid_key in dict.fromkeys(entry.raid_key for entry in version_entries):
            raid_entries = [entry for entry in version_entries if entry.raid_key == raid_key]
            first = raid_entries[0]
            raid = {
                "key": raid_key,
                "name": first.raid_name,
                "bosses": [],
            }
            if first.raid_english_name:
                raid["englishName"] = first.raid_english_name
            if first.raid_external_key:
                raid["externalKey"] = first.raid_external_key
            if first.raid_aliases:
                raid["aliases"] = first.raid_aliases

            for entry in sorted(raid_entries, key=lambda item: item.order):
                boss = {
                    "key": entry.boss_key,
                    "name": entry.boss_name,
                    "order": entry.order,
                    "supported": entry.supported,
                    "disabledReason": entry.disabled_reason,
                    "configSchema": entry.config_schema,
                }
                if entry.english_name:
                    boss["englishName"] = entry.english_name
                if entry.external_key:
                    boss["externalKey"] = entry.external_key
                if entry.aliases:
                    boss["aliases"] = entry.aliases
                if entry.arena_assets:
                    boss["arenaAssets"] = entry.arena_assets
                raid["bosses"].append(boss)
            raids.append(raid)
        versions.append({"version": version, "raids": raids})
    return {"schemaVersion": int(CATALOG_DOCUMENT.get("schemaVersion") or 1), "versions": versions}
