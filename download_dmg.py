"""多线程下载 GitHub Release 文件（镜像加速 + 分块重试 + 校验）。

用法：
    python download_dmg.py                     # 默认下 v1.2.1 的 dmg
    python download_dmg.py --tag v1.2.1 --file Dict-arm64.dmg
    python download_dmg.py --out D:/Dict.dmg
    python download_dmg.py --threads 24
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import os
import sys
import time
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()

REPO = "geyuhan12321/mac"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

MIRRORS = [
    "https://ghproxy.sakuramoe.dev/{gh}",
    "https://ghfast.top/{gh}",
    "https://ghfile.geekertao.top/{gh}",
    "https://gh-proxy.com/{gh}",
    "https://ghproxy.cfd/{gh}",
    "{gh}",                      # 直连兜底
]


def api_asset(tag: str, name: str) -> dict:
    url = f"https://api.github.com/repos/{REPO}/releases/tags/{tag}"
    r = requests.get(url, headers=UA, timeout=30, verify=False)
    r.raise_for_status()
    for a in r.json().get("assets", []):
        if a["name"] == name:
            return {"size": a["size"], "url": a["browser_download_url"],
                    "digest": a.get("digest") or ""}
    raise SystemExit(f"发布里没有 {name}")


def probe(url: str) -> float:
    """测速：拉 1MB 看看。"""
    t0 = time.time()
    try:
        r = requests.get(url, headers={**UA, "Range": "bytes=0-1048575"},
                         timeout=8, stream=True, verify=False)
        if r.status_code not in (200, 206):
            return 0.0
        got = 0
        for c in r.iter_content(65536):
            got += len(c)
            if got >= 1048576:
                break
        r.close()
        return got / max(time.time() - t0, 0.01) / 1024 / 1024
    except Exception:
        return 0.0


def pick_source(gh_url: str) -> tuple[str, float]:
    best, best_speed = "", 0.0
    for tpl in MIRRORS:
        cand = tpl.format(gh=gh_url)
        speed = probe(cand)
        host = cand.split("/")[2]
        print(f"  {host:28} {speed:6.2f} MB/s")
        if speed > best_speed:
            best, best_speed = cand, speed
    return best, best_speed


def download(url: str, out: Path, size: int, threads: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(out.suffix + ".part")
    if part.exists():
        part.unlink()

    block = max(1, size // (threads * 4))
    ranges = [(s, min(s + block - 1, size - 1)) for s in range(0, size, block)]
    done = [0] * len(ranges)
    lock = __import__("threading").Lock()

    def fetch(idx: int):
        start, end = ranges[idx]
        for attempt in range(4):
            try:
                r = requests.get(url, headers={**UA, "Range": f"bytes={start}-{end}"},
                                 timeout=30, stream=True, verify=False)
                if r.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {r.status_code}")
                data = b"".join(r.iter_content(262144))
                r.close()
                if len(data) != end - start + 1:
                    raise RuntimeError(f"长度不符 {len(data)}")
                with lock:
                    with open(part, "r+b") as f:
                        f.seek(start)
                        f.write(data)
                    done[idx] = len(data)
                return
            except Exception as exc:
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))

    part.touch()
    with open(part, "r+b") as f:
        f.truncate(size)

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=threads) as pool:
        futs = [pool.submit(fetch, i) for i in range(len(ranges))]
        last = 0
        for n, _ in enumerate(cf.as_completed(futs), 1):
            got = sum(done)
            if n % 8 == 0 or n == len(futs):
                el = max(time.time() - t0, 0.1)
                print(f"\r  {got/1048576:7.1f}/{size/1048576:.1f} MB  "
                      f"{got/el/1048576:5.2f} MB/s", end="", flush=True)
            last = got
    print()

    part.replace(out)
    print(f"  完成 {out}  {out.stat().st_size/1048576:.1f} MB  "
          f"用时 {time.time()-t0:.0f}s")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v1.2.1")
    ap.add_argument("--file", default="Dict-arm64.dmg")
    ap.add_argument("--out", default="")
    ap.add_argument("--threads", type=int, default=24)
    args = ap.parse_args()

    info = api_asset(args.tag, args.file)
    size = info["size"]
    out = Path(args.out) if args.out else Path.home() / "Downloads" / args.file
    print(f"目标 {args.file}  {size/1048576:.1f} MB")
    if out.exists() and out.stat().st_size == size:
        print("已经下好了，直接校验")
    else:
        print("测速选源…")
        src, speed = pick_source(info["url"])
        if not src:
            print("所有镜像都不可用")
            return 1
        print(f"用 {src.split('/')[2]}（{speed:.2f} MB/s）\n下载中…")
        download(src, out, size, args.threads)

    digest = sha256(out)
    print(f"本地 sha256 {digest}")
    if info["digest"].startswith("sha256:"):
        want = info["digest"].split(":", 1)[1]
        print("一致" if digest == want else f"不一致！应为 {want}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
