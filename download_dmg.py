"""多线程下载 GitHub Release（镜像选速 + 分块校验 + 失败重试 + sha256 比对）。

用法：
    python download_dmg.py                        # 最新发布里的 dmg
    python download_dmg.py --tag v1.2.2
    python download_dmg.py --file Dict-arm64.zip
    python download_dmg.py --threads 32 --out D:/x.dmg
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import sys
import threading
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
    "{gh}",
]


def api_asset(tag: str, name: str) -> dict:
    url = (f"https://api.github.com/repos/{REPO}/releases/tags/{tag}" if tag
           else f"https://api.github.com/repos/{REPO}/releases/latest")
    release = requests.get(url, headers=UA, timeout=30, verify=False).json()
    for a in release.get("assets", []):
        if a["name"] == name:
            return {
                "size": a["size"],
                "url": a["browser_download_url"],
                "digest": (a.get("digest") or "").replace("sha256:", ""),
                "tag": release["tag_name"],
            }
    raise SystemExit(f"发布里没有 {name}")


def probe(url: str, seconds: float = 2.0) -> float:
    """限时探测下载速度（MB/s）。"""
    t0 = time.time()
    got = 0
    try:
        r = requests.get(url, headers={**UA, "Range": "bytes=0-4194303"},
                         timeout=8, stream=True, verify=False)
        if r.status_code not in (200, 206):
            return 0.0
        for c in r.iter_content(65536):
            got += len(c)
            if time.time() - t0 > seconds:
                break
        r.close()
    except Exception:
        return 0.0
    return got / max(time.time() - t0, 0.01) / 1048576


def fetch_chunk(url: str, start: int, end: int, attempts: int = 5) -> bytes:
    """取一段，严格校验长度；服务器忽略 Range 时自己切。"""
    want = end - start + 1
    last = ""
    for i in range(attempts):
        try:
            r = requests.get(url, headers={**UA, "Range": f"bytes={start}-{end}"},
                             timeout=30, stream=True, verify=False)
            if r.status_code == 206:
                data = b"".join(r.iter_content(65536))
                r.close()
                if len(data) == want:
                    return data
                last = f"长度 {len(data)} != {want}"
                continue
            if r.status_code == 200:
                data = b"".join(r.iter_content(65536))
                r.close()
                piece = data[start:end + 1]
                if len(piece) == want:
                    return piece
                last = f"忽略 Range，切片后 {len(piece)}"
                continue
            last = f"HTTP {r.status_code}"
            r.close()
        except Exception as exc:
            last = f"{type(exc).__name__}: {str(exc)[:50]}"
        time.sleep(1.0 + i)
    raise RuntimeError(f"{start}-{end} 失败：{last}")


def download(url: str, out: Path, size: int, threads: int) -> None:
    part = out.with_suffix(out.suffix + ".part")
    part.unlink(missing_ok=True)
    part.parent.mkdir(parents=True, exist_ok=True)
    with open(part, "w+b") as f:
        f.truncate(size)

    block = max(1, size // (threads * 2))
    ranges = [(s, min(s + block - 1, size - 1)) for s in range(0, size, block)]
    done = [0] * len(ranges)
    errors: list[tuple[int, str]] = []
    lock = threading.Lock()
    t0 = time.time()

    def work(idx: int):
        s, e = ranges[idx]
        try:
            data = fetch_chunk(url, s, e)
            with lock:
                with open(part, "r+b") as f:
                    f.seek(s)
                    f.write(data)
                done[idx] = len(data)
        except Exception as exc:
            with lock:
                errors.append((idx, str(exc)))

    with cf.ThreadPoolExecutor(max_workers=threads) as pool:
        futs = [pool.submit(work, i) for i in range(len(ranges))]
        while not all(f.done() for f in futs):
            time.sleep(0.5)
            got = sum(done)
            el = max(time.time() - t0, 0.1)
            print(f"\r  {got/1048576:7.1f}/{size/1048576:.1f} MB  "
                  f"{got/el/1048576:5.2f} MB/s", end="", flush=True)
        for f in futs:
            f.result()          # 让异常浮出来

    total = sum(done)
    print(f"\r  {total/1048576:7.1f}/{size/1048576:.1f} MB  用时 {time.time()-t0:.0f}s")
    if errors or total != size:
        raise RuntimeError(f"{len(errors)} 块失败，共收到 {total}/{size} 字节")

    part.replace(out)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="")
    ap.add_argument("--file", default="Dict-arm64.dmg")
    ap.add_argument("--out", default="")
    ap.add_argument("--threads", type=int, default=32)
    args = ap.parse_args()

    info = api_asset(args.tag, args.file)
    size, want = info["size"], info["digest"]
    out = Path(args.out) if args.out else Path.home() / "Downloads" / args.file
    print(f"{info['tag']} / {args.file}  {size/1048576:.1f} MB")

    if out.exists() and out.stat().st_size == size:
        if not want or sha256(out) == want:
            print("已存在且校验通过:", out)
            return 0
        print("已有文件不正确，重新下载")

    scored = []
    for tpl in MIRRORS:
        cand = tpl.format(gh=info["url"])
        sp = probe(cand)
        print(f"  {cand.split('/')[2]:28} {sp:6.2f} MB/s")
        if sp > 0:
            scored.append((sp, cand))
    if not scored:
        print("没有可用镜像")
        return 1
    scored.sort(reverse=True)

    for attempt in range(min(3, len(scored))):
        sp, url = scored[attempt]
        print(f"\n第 {attempt + 1} 次：{url.split('/')[2]}（{sp:.2f} MB/s）")
        try:
            download(url, out, size, args.threads)
        except Exception as exc:
            print("  失败:", exc)
            continue
        got = sha256(out)
        if not want or got == want:
            print("sha256 一致:", got)
            print("保存于:", out)
            return 0
        print("  sha256 不一致，换镜像重试")
        out.unlink(missing_ok=True)

    print("三个镜像都未能下成，稍后再试")
    return 1


if __name__ == "__main__":
    sys.exit(main())
