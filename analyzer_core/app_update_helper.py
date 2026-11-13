"""Finish a fast-forward update after the standalone server has exited."""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from analyzer_core.app_update import git, local_update_blocker


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def wait_for_parent(pid: int, seconds: int = 60):
    if os.name == "nt":
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return True
        try:
            return kernel.WaitForSingleObject(handle, seconds * 1000) == 0
        finally:
            kernel.CloseHandle(handle)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.2)
    return False


def apply_commit(root: Path, commit: str):
    if not COMMIT_RE.fullmatch(commit):
        raise ValueError("无效的提交编号。")
    blocker = local_update_blocker(root)
    if blocker:
        raise RuntimeError(blocker)
    fetched = git(root, "fetch", "origin", "main", timeout=60)
    if fetched.returncode:
        raise RuntimeError("下载 GitHub 更新失败：" + fetched.stderr.strip()[-300:])
    fetched_commit = git(root, "rev-parse", "FETCH_HEAD")
    if fetched_commit.returncode or fetched_commit.stdout.strip() != commit:
        raise RuntimeError("GitHub 上的提交已变化，请重新检查更新。")
    ancestor = git(root, "merge-base", "--is-ancestor", "HEAD", commit)
    if ancestor.returncode:
        raise RuntimeError("目标提交不是当前分支的快进更新。")
    merged = git(root, "merge", "--ff-only", commit, timeout=60)
    if merged.returncode:
        raise RuntimeError("应用 GitHub 更新失败：" + merged.stderr.strip()[-300:])


def restart_server(root: Path, host: str, port: int):
    log_path = root / "data" / "app_update.log"
    log_path.parent.mkdir(exist_ok=True)
    with log_path.open("ab") as log:
        subprocess.Popen([sys.executable, str(root / "server.py"), "--host", host,
                          "--port", str(port)], cwd=root, stdin=subprocess.DEVNULL,
                         stdout=log, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                         start_new_session=os.name != "nt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if not wait_for_parent(args.parent_pid):
        raise SystemExit("服务未停止，更新已取消。")
    try:
        apply_commit(root, args.commit)
    except Exception as error:
        with (root / "data" / "app_update.log").open("a", encoding="utf-8") as log:
            log.write(f"更新 {args.commit} 失败：{error}\n")
    finally:
        restart_server(root, args.host, args.port)


if __name__ == "__main__":
    main()
