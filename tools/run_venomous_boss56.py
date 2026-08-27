"""Re-run Venomous Abyss boss 5/6 analysis against WCL and refresh sample JSON."""

from __future__ import annotations

import json
from pathlib import Path

from boss_plugins.venomous_abyss.sszorak import analyze as analyze_sszorak
from boss_plugins.venomous_abyss.twinfangs import analyze as analyze_twinfangs

REPORT_ID = "ZTcf3gMPmnBFVtvx"
ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "assets" / "samples"


def main():
    outputs = {
        "sszorak": SAMPLES / f"wcl_{REPORT_ID}_sszorak_all.json",
        "twinfangs": SAMPLES / f"wcl_{REPORT_ID}_twinfangs_all.json",
    }
    summary = []
    for boss_key, output_path in outputs.items():
        print(f"[run] analyzing {boss_key} -> {output_path}", flush=True)
        analyze_fn = analyze_sszorak if boss_key == "sszorak" else analyze_twinfangs
        output = analyze_fn(REPORT_ID, output_path=output_path)
        payload = json.loads(Path(output).read_text(encoding="utf-8")) if not isinstance(output, dict) else output
        pulls = len(payload.get("data", {}).get("page1_wipeAnalysis", []))
        summary.append({
            "boss": boss_key,
            "report": REPORT_ID,
            "file": output_path.name,
            "status": "ok",
            "pulls": pulls,
        })
        print(f"[run] {boss_key}: {pulls} pulls", flush=True)

    manifest = {
        "schemaVersion": 1,
        "files": [
            {
                "path": f"assets/samples/wcl_{REPORT_ID}_sszorak_all.json",
                "name": f"wcl_{REPORT_ID}_sszorak_all.json",
                "label": "5 号斯索拉克 · ZTcf3gMPmnBFVtvx · 英雄（含场地回放）",
            },
            {
                "path": f"assets/samples/wcl_{REPORT_ID}_twinfangs_all.json",
                "name": f"wcl_{REPORT_ID}_twinfangs_all.json",
                "label": "6 号双子毒牙 · ZTcf3gMPmnBFVtvx · 英雄",
            },
        ],
    }
    (SAMPLES / "report_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (ROOT / "cache" / "venomous_run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("[run] done", flush=True)


if __name__ == "__main__":
    main()
