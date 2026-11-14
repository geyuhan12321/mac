"""从 zdic.net 抓「部首 / 部外笔画 / 总笔画」，写进 data/zdic.json。

页面结构：
    <span class="meta-badge">部首</span><a class="meta-radical">阝</a>
    <span class="meta-badge">部外</span><span class="meta-value">5</span>
    <span class="meta-badge">总笔画</span><span class="meta-value">7</span>

用法：
    python fetch_zdic.py            # 抓取（有缓存，中断可续）
    python fetch_zdic.py --apply    # 并入 words.json
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings()

BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "words.json"
CACHE = BASE / "data" / "zdic.json"
PROXY = "http://127.0.0.1:26561"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

RAD = re.compile(r'class="meta-radical">([^<]+)</a>')
STROKES = re.compile(r'总笔画</span><span class="meta-value">(\d+)<')
OUTER = re.compile(r'部外</span><span class="meta-value">(\d+)<')


def fetch_one(ch: str, session: requests.Session):
    try:
        url = "https://www.zdic.net/hans/" + quote(ch)
        r = session.get(url, headers=UA, timeout=20, verify=False,
                        proxies={"http": PROXY, "https": PROXY})
        if r.status_code != 200:
            return ch, None
        html = r.text
        m_rad = RAD.search(html)
        m_st = STROKES.search(html)
        m_out = OUTER.search(html)
        if not (m_rad or m_st):
            return ch, None
        return ch, {
            "radical": m_rad.group(1).strip() if m_rad else "",
            "strokes": int(m_st.group(1)) if m_st else None,
            "outer": int(m_out.group(1)) if m_out else None,
        }
    except Exception:
        return ch, None


def main() -> int:
    apply = "--apply" in sys.argv
    data = json.loads(DATA.read_text(encoding="utf-8"))
    chars = [e["headword"] for e in data if len(e["headword"]) == 1]

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = [c for c in chars if c not in cache]
    print(f"缓存 {len(cache)}，待抓 {len(todo)}，总计 {len(chars)}")

    if todo:
        done, t0 = 0, time.time()
        with requests.Session() as s:
            with ThreadPoolExecutor(max_workers=10) as pool:
                futs = {pool.submit(fetch_one, c, s): c for c in todo}
                for fut in as_completed(futs):
                    ch, info = fut.result()
                    if info:
                        cache[ch] = info
                    done += 1
                    if done % 200 == 0:
                        el = max(time.time() - t0, 1)
                        print(f"  {done}/{len(todo)}  成功 {len(cache)}  {done/el:.0f}/s", flush=True)
                    if done % 500 == 0:
                        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    print(f"\n共获得 {len(cache)} / {len(chars)} 个字的部首笔画")

    if apply:
        n = 0
        for e in data:
            info = cache.get(e["headword"])
            if not info:
                continue
            char = e.get("character") or {}
            if info.get("radical"):
                char["radical"] = info["radical"]
            if info.get("strokes"):
                char["strokes"] = str(info["strokes"])
            e["character"] = char
            n += 1
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已并入 words.json：{n} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
