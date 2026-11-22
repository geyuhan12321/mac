"""把「行内讲解」的字补成条目。

例：
    古代都城，王城：亳 亳城 亳水 亳州        → 亳
    持有物待在旁边照顾人：侍 侍奉 侍臣…      → 侍
    径直->轻                                 → 轻（整页都是它的）
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

BASE = Path(r"C:\Users\ge\Downloads\collins-dict-desktop")
PPTX = Path(r"C:\Users\ge\.dsh\attachments\v1\files\23\232fecff6fc8e87523f02331a810ad837494cd1085501a30e90505197cc4005a\汉字字典（拼音顺序版）.pptx")
DATA = BASE / "data" / "words.json"
XH = BASE / "data" / "xinhua.json"

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
TONE = "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü"
PY_RE = re.compile(rf"^[a-zA-Z{TONE}\s/]+$")
AFTER_COLON = re.compile(r"[：:]\s*([\u3400-\u9fff])[\s、，,]")
ARROW = re.compile(r"->\s*([\u3400-\u9fff])\s*$")
LINE_HEAD = re.compile(r"^([\u3400-\u9fff])[：:]")
TAIL_PY = re.compile(rf"[:：]\s*([a-zA-Z{TONE}]{{1,7}})\s*[；;，,]?\s*$")


def lines_of(z, name):
    root = ET.fromstring(z.read(name))
    out = []
    for para in root.iter(A + "p"):
        t = "".join(x.text or "" for x in para.iter(A + "t")).strip()
        if t:
            out.append(t)
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    words = json.loads(DATA.read_text(encoding="utf-8"))
    lex = {e["headword"] for e in words}
    xh = json.loads(XH.read_text(encoding="utf-8")) if XH.exists() else {}

    z = zipfile.ZipFile(PPTX)
    slides = sorted([n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
                    key=lambda n: int("".join(c for c in n if c.isdigit())))

    collected: dict[str, dict] = {}
    for idx, name in enumerate(slides, 1):
        ls = lines_of(z, name)
        if not ls:
            continue
        page_py = ls[0] if PY_RE.match(ls[0]) and len(ls[0]) < 24 else ""

        # 整页式：X->Y
        m_arrow = ARROW.search(ls[0])
        if m_arrow:
            target = m_arrow.group(1)
            if target not in lex:
                item = collected.setdefault(target, {"lines": [], "pages": [], "py": ""})
                item["pages"].append(idx)
                for line in ls[1:]:
                    if line not in item["lines"]:
                        item["lines"].append(line)
                m_py = TAIL_PY.search("\n".join(ls[1:]))
                if m_py and not item["py"]:
                    item["py"] = m_py.group(1)

        for line in ls:
            cands = AFTER_COLON.findall(line) + LINE_HEAD.findall(line)
            for ch in cands:
                if ch in lex:
                    continue
                item = collected.setdefault(ch, {"lines": [], "pages": [], "py": ""})
                if idx not in item["pages"]:
                    item["pages"].append(idx)
                if line not in item["lines"] and len(item["lines"]) < 6:
                    item["lines"].append(line)
                if page_py and not item["py"] and ch in line:
                    item["py"] = page_py

    print(f"可补 {len(collected)} 个字")
    print("样例:", "".join(list(collected)[:60]))

    new_entries = []
    for ch, item in collected.items():
        body = "\n".join(item["lines"]).strip()
        if not body:
            continue
        info = xh.get(ch) or {}
        new_entries.append({
            "id": f"c-{ch}",
            "headword": ch,
            "lang": "zh",
            "frequency": None,
            "pronunciation": {"pinyin": item.get("py") or info.get("pinyin", ""), "uk": "", "us": ""},
            "wordForms": [],
            "character": {"radical": info.get("radical", ""),
                          "strokes": str(info.get("strokes", "") or ""), "traditional": ""},
            "senses": [{"pos": "", "definition": body, "definitionZh": "", "examples": [],
                        "synonyms": [], "collocations": [], "labels": [], "note": "", "images": []}],
            "phrases": [], "etymology": "", "images": [], "tags": ["行内"],
        })

    for e in new_entries[:10]:
        print(f"\n  【{e['headword']}】{e['pronunciation']['pinyin']} 部{e['character']['radical']}")
        for line in e["senses"][0]["definition"].splitlines()[:2]:
            print("     ", line[:70])

    if apply:
        words.extend(new_entries)
        DATA.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n写入完成，共 {len(words)} 条")
    else:
        print("\n（预览，加 --apply 写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
