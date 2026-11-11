"""Check published Git tags without spending Warcraft Logs API points."""

from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path


APP_VERSION = "2.0.2"
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
CHECK_INTERVAL_SECONDS = 15 * 60
_lock = threading.Lock()
_cached = None
_checked_at = 0.0


def version_tuple(value: str):
    match = TAG_RE.fullmatch(value if value.startswith("v") else "v" + value)
    return tuple(map(int, match.groups())) if match else None


def latest_tag(refs: str):
    tags = set()
    for line in refs.splitlines():
        fields = line.split()
        if len(fields) != 2 or not fields[1].startswith("refs/tags/"):
            continue
        tag = fields[1].removeprefix("refs/tags/").removesuffix("^{}")
        if version_tuple(tag):
            tags.add(tag)
    return max(tags, key=version_tuple, default=None)


def git(root: Path, *args: str, timeout: int = 15):
    return subprocess.run(["git", *args], cwd=root, text=True, encoding="utf-8",
                          errors="replace", capture_output=True,
                          timeout=timeout, check=False)


def local_update_blocker(root: Path):
    branch = git(root, "branch", "--show-current")
    if branch.returncode or branch.stdout.strip() != "main":
        return "自动更新仅支持 main 分支。"
    status = git(root, "status", "--porcelain", "--untracked-files=normal")
    if status.returncode:
        return "无法检查 Git 工作区。"
    if status.stdout.strip():
        return "工作区有未提交或未跟踪文件，请先处理本地改动。"
    return None


def update_status(root: Path, *, now=None, force=False):
    global _cached, _checked_at
    now = time.time() if now is None else now
    with _lock:
        if force or _cached is None or now - _checked_at >= CHECK_INTERVAL_SECONDS:
            remote = git(root, "ls-remote", "--tags", "origin", "v*", timeout=8)
            _cached = {"tag": latest_tag(remote.stdout) if remote.returncode == 0 else None,
                       "error": "GitHub 版本检查暂不可用。" if remote.returncode else None}
            _checked_at = now
        tag = _cached["tag"]
        available = bool(tag and version_tuple(tag) > version_tuple(APP_VERSION))
        blocker = local_update_blocker(root) if available else None
        return {"currentVersion": APP_VERSION, "latestVersion": tag[1:] if tag else None,
                "tag": tag, "updateAvailable": available,
                "canApply": available and blocker is None,
                "blocker": blocker, "error": _cached["error"], "checkedAt": _checked_at}
