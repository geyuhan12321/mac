"""补录缺口字（清洗版）：只取新华字典的简明义项，去掉古注引用。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "words.json"
FULL = BASE / "data" / "xinhua_full.json"

NUM = re.compile(r"[⒈⒉⒊⒋⒌⒍⒎⒏⒐⒑]")
CITE = re.compile(r"--[^》]*》?")


def clean(expl: str) -> str:
    """把冗长的字典原文压成几条简明释义。"""
    text = expl.replace("\r", "")
    pos = text.find("⒈")
    core = text[pos:] if pos >= 0 else text
    parts = NUM.split(core)
    out = []
    for p in parts:
        p = CITE.sub("", p)
        p = re.sub(r"\(.*?\)", "", p)
        p = re.sub(r"（.*?）", "", p)
        p = re.sub(r"\s+", " ", p).strip(" 。，,;；")
        if len(p) < 2:
            continue
        out.append(p)
        if len(out) >= 3:
            break
    if not out:
        first = re.split(NUM, text)[0]
        out = [re.sub(r"\s+", " ", first).strip()[:120]] if first.strip() else []
    return "\n".join(out)


def main() -> int:
    apply = "--apply" in sys.argv
    words = json.loads(DATA.read_text(encoding="utf-8"))
    heads = {e["headword"] for e in words}
    table = json.loads(FULL.read_text(encoding="utf-8"))

    corpus = []
    for e in words:
        for s in e.get("senses") or []:
            corpus += [s.get("definition", ""), s.get("definitionZh", "")]
            corpus += [x.get("text", "") for x in s.get("examples") or []]
        corpus.append(e.get("etymology", ""))
    text = "\n".join(corpus)

    seen, missing = set(), []
    for ch in text:
        if "\u3400" <= ch <= "\u9fff" and ch not in heads and ch not in seen:
            seen.add(ch)
            missing.append(ch)

    added = []
    for ch in missing:
        info = table.get(ch)
        if not info:
            continue
        body = clean(info["explanation"])
        if not body:
            continue
        added.append({
            "id": f"c-{ch}",
            "headword": ch,
            "lang": "zh",
            "frequency": None,
            "pronunciation": {"pinyin": info["pinyin"].replace(",", " / "), "uk": "", "us": ""},
            "wordForms": [],
            "character": {"radical": info["radical"], "strokes": info["strokes"],
                          "traditional": ""},
            "senses": [{"pos": "", "definition": body, "definitionZh": "",
                        "examples": [], "synonyms": [], "collocations": [],
                        "labels": [], "note": "", "images": []}],
            "phrases": [], "etymology": "", "images": [], "tags": ["补录"],
        })

    print(f"词库 {len(heads)}；文中未收录 {len(missing)}；可补 {len(added)}")
    print("\n样例：")
    for e in added[:6]:
        print(f"  【{e['headword']}】{e['pronunciation']['pinyin']}  部{e['character']['radical']}")
        for line in e["senses"][0]["definition"].splitlines():
            print("     ", line[:60])

    if apply:
        words.extend(added)
        DATA.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n写入完成，共 {len(words)} 条")
    else:
        print("\n（预览，加 --apply 写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
