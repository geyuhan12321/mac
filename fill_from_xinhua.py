"""用 chinese-xinhua 数据集补全部首、笔画、拼音。

数据集来自 GitHub（新华字典全量），字段：
    word / oldword / strokes / pinyin / radicals / explanation / more

优先用 zdic 已抓到的，缺失的用这个补。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()

BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "words.json"
ZDIC = BASE / "data" / "zdic.json"
CACHE = BASE / "data" / "xinhua.json"
PROXY = {"http": "http://127.0.0.1:26561", "https": "http://127.0.0.1:26561"}
URL = "https://raw.githubusercontent.com/pwxcoo/chinese-xinhua/master/data/word.json"


def load_xinhua() -> dict:
    if CACHE.exists() and CACHE.stat().st_size > 1_000_000:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    print("下载新华字典数据 …")
    r = requests.get(URL, proxies=PROXY, timeout=120, verify=False)
    r.raise_for_status()
    raw = r.json()
    table = {}
    for item in raw:
        w = (item.get("word") or "").strip()
        if len(w) != 1:
            continue
        table.setdefault(w, {
            "radical": (item.get("radicals") or "").strip(),
            "strokes": str(item.get("strokes") or "").strip(),
            "pinyin": (item.get("pinyin") or "").strip(),
        })
    CACHE.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    print(f"  收录单字 {len(table)}")
    return table


def main() -> int:
    apply = "--apply" in sys.argv
    data = json.loads(DATA.read_text(encoding="utf-8"))
    xh = load_xinhua()
    zd = json.loads(ZDIC.read_text(encoding="utf-8")) if ZDIC.exists() else {}

    stat = {"rad_zdic": 0, "rad_xh": 0, "st_zdic": 0, "st_xh": 0,
            "py_ppt": 0, "py_xh": 0, "none": []}

    for e in data:
        ch = e["headword"]
        char = e.setdefault("character", {}) or {}
        pron = e.setdefault("pronunciation", {})

        # 部首：zdic 优先
        z = zd.get(ch) or {}
        if z.get("radical"):
            char["radical"] = z["radical"]
            stat["rad_zdic"] += 1
        elif xh.get(ch, {}).get("radical"):
            char["radical"] = xh[ch]["radical"]
            stat["rad_xh"] += 1

        # 笔画：zdic 优先
        if z.get("strokes"):
            char["strokes"] = str(z["strokes"])
            stat["st_zdic"] += 1
        elif xh.get(ch, {}).get("strokes"):
            char["strokes"] = xh[ch]["strokes"]
            stat["st_xh"] += 1

        # 拼音：PPT 抽到的优先
        if pron.get("pinyin"):
            stat["py_ppt"] += 1
        elif xh.get(ch, {}).get("pinyin"):
            pron["pinyin"] = xh[ch]["pinyin"].replace(",", " / ")
            stat["py_xh"] += 1

        e["character"] = char
        if not char.get("radical") and not char.get("strokes"):
            stat["none"].append(ch)

    n = len(data)
    print(f"词条 {n}")
    print(f"  部首：zdic {stat['rad_zdic']} + 新华 {stat['rad_xh']} = {stat['rad_zdic']+stat['rad_xh']}")
    print(f"  笔画：zdic {stat['st_zdic']} + 新华 {stat['st_xh']} = {stat['st_zdic']+stat['st_xh']}")
    print(f"  拼音：PPT {stat['py_ppt']} + 新华 {stat['py_xh']}")
    if stat["none"]:
        print(f"  仍缺部首笔画：{len(stat['none'])} 个 {''.join(stat['none'][:20])}")

    if apply:
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("已写入 words.json")
    else:
        print("（预览，加 --apply 写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
