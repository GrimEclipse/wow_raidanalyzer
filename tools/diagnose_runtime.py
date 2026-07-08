from pathlib import Path
import os
import sys


def env_file_keys(root):
    env_path = root / ".env"
    if not env_path.exists():
        return []
    keys = []
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.append(line.split("=", 1)[0].strip())
    return keys


def main():
    root = Path(__file__).resolve().parents[1]
    analyze_path = root / "analyze.py"
    env_keys = env_file_keys(root)
    print("[diagnose] Python executable:", sys.executable, flush=True)
    print("[diagnose] Python version:", sys.version.replace("\n", " "), flush=True)
    print("[diagnose] Current working directory:", Path.cwd(), flush=True)
    print("[diagnose] This file:", Path(__file__).resolve(), flush=True)
    print("[diagnose] analyze.py:", analyze_path, flush=True)
    print("[diagnose] analyze.py exists:", analyze_path.exists(), flush=True)
    print("[diagnose] WCL_CLIENT_ID present:", bool(os.getenv("WCL_CLIENT_ID")), flush=True)
    print("[diagnose] WCL_CLIENT_SECRET present:", bool(os.getenv("WCL_CLIENT_SECRET")), flush=True)
    print("[diagnose] .env exists:", (root / ".env").exists(), flush=True)
    print("[diagnose] .env has WCL_CLIENT_ID:", "WCL_CLIENT_ID" in env_keys, flush=True)
    print("[diagnose] .env has WCL_CLIENT_SECRET:", "WCL_CLIENT_SECRET" in env_keys, flush=True)
    print("[diagnose] If you can see this, this terminal is executing project Python files correctly.", flush=True)


if __name__ == "__main__":
    main()
