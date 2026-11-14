#!/usr/bin/env python
"""分批推送词库到 GitHub：每批 300 张图，网络断了自动重试。

用法：  python push_data.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
BATCH = 300
MAX_RETRY = 5


def run(args, check=False):
    return subprocess.run(args, cwd=BASE, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore")


def network_ok() -> bool:
    r = run(["git", "ls-remote", "--heads", "origin"])
    return r.returncode == 0


def wait_network(rounds: int = 60) -> bool:
    for i in range(rounds):
        if network_ok():
            return True
        print(f"    网络未就绪，{5}s 后重试（{i+1}/{rounds}）", flush=True)
        time.sleep(5)
    return False


def push_with_retry() -> bool:
    for i in range(MAX_RETRY):
        print(f"  push 第 {i+1} 次 …", flush=True)
        r = run(["git", "push", "origin", "main"])
        if r.returncode == 0:
            print("  推送成功", flush=True)
            return True
        err = (r.stderr or r.stdout).strip().splitlines()
        print("    " + (err[-1] if err else "未知错误"), flush=True)
        if not wait_network(12):
            continue
        time.sleep(2)
    return False


def main() -> int:
    images = sorted((BASE / "data" / "images").glob("*.jpg"))
    words = BASE / "data" / "words.json"
    total = len(images)

    # 1) 先推词库文件本身
    run(["git", "add", "data/words.json", ".gitignore"])
    r = run(["git", "-c", "core.autocrlf=false", "commit", "-m",
             f"词库索引：{total and '4425 个单字'}"])
    print("提交词库索引:", "ok" if r.returncode == 0 else "已提交")

    if not wait_network():
        print("网络长时间不可用，已中止")
        return 1
    if not push_with_retry():
        print("词库索引推送失败")
        return 1

    # 2) 分批推图片
    for start in range(0, total, BATCH):
        chunk = images[start:start + BATCH]
        names = [str(p.relative_to(BASE)).replace("\\", "/") for p in chunk]
        run(["git", "add", "--"] + names)
        msg = f"字源图 {start+1}-{start+len(chunk)}（共 {total}）"
        r = run(["git", "-c", "core.autocrlf=false", "commit", "-m", msg])
        if r.returncode != 0:
            continue
        print(f"[{start+1}-{start+len(chunk)}/{total}] 已提交", flush=True)
        if not wait_network():
            print("网络中断，已停止；重新运行本脚本会继续")
            return 1
        if not push_with_retry():
            print("本批推送失败，已停止；重新运行本脚本会继续")
            return 1

    print("\n全部完成:", total, "张图已推送")
    return 0


if __name__ == "__main__":
    sys.exit(main())
