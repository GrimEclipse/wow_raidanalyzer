# -*- coding: utf-8 -*-
"""Bake all WCL JSON files into vendor JS for file:// multi-source load. Author: Wei."""
from pathlib import Path
import json
import sys

target = Path(sys.argv[1])
root = Path(sys.argv[2])
vendor = target / "assets" / "vendor"
vendor.mkdir(parents=True, exist_ok=True)

def web_key(path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name

candidates = []
legacy = root / "wcl_hardcore_api.json"
if legacy.is_file():
    candidates.append(legacy)
data_dir = root / "data"
if data_dir.is_dir():
    candidates.extend(sorted(data_dir.glob("wcl_*.json"), key=lambda p: p.stat().st_mtime, reverse=True))

source_map = {}
for path in candidates:
    raw = path.read_text(encoding="utf-8-sig")
    json.loads(raw)  # validate
    source_map[web_key(path)] = json.loads(raw)
    print("bake candidate:", web_key(path), path.stat().st_size, "bytes")

parts = [
    "// Auto-baked by build_offline_package.ps1",
    "// Prefer window.__WCL_DATA_BY_SOURCE__[path]; fall back to __WCL_HARDCORE_DATA__.",
]
if source_map:
    parts.append("window.__WCL_DATA_BY_SOURCE__ = " + json.dumps(source_map, ensure_ascii=False) + ";")
    primary_key = next(iter(source_map))
    if "wcl_hardcore_api.json" in source_map:
        primary_key = "wcl_hardcore_api.json"
    parts.append("window.__WCL_HARDCORE_DATA__ = window.__WCL_DATA_BY_SOURCE__[" + json.dumps(primary_key) + "];")
    parts.append("window.__OFFLINE_DATA__ = window.__WCL_HARDCORE_DATA__;")
    print("baked", len(source_map), "sources; primary =", primary_key)
else:
    parts.append("// No wcl_*.json found at build time.")
    print("WARNING: no wcl json files to bake")

verdict = root / "verdict_data.json"
if verdict.exists():
    raw = verdict.read_text(encoding="utf-8-sig")
    json.loads(raw)
    parts.append("window.__VERDICT_DATA__ = " + raw + ";")
    print("baked verdict_data.json ->", verdict.stat().st_size, "bytes")

# Refresh packaged manifest from baked keys.
manifest = {
    "schemaVersion": 1,
    "files": [
        {"path": key, "name": key.split("/")[-1], "label": key, "size": 0, "mtime": 0}
        for key in source_map
    ],
}
data_out = target / "data"
data_out.mkdir(parents=True, exist_ok=True)
(data_out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

out = vendor / "wcl_hardcore_api.js"
out.write_text("\n".join(parts) + "\n", encoding="utf-8")
print("wrote", out, "size", out.stat().st_size)
