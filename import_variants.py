"""导入「简繁并列」页：每页建一条（首字为主字），另一字记为繁体并参与搜索。"""
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
CJK = re.compile(r"[\u3400-\u9fff]")
PUNCT = re.compile(r"[：:，,。；;、！？（）()\[\]【】\s]")
TONE = "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü"
TAIL = re.compile(f"[:：]\\s*[a-zA-Z{TONE}]{{1,7}}\\s*[；;，,]?\\s*$")


def lines_of(z, name):
    root = ET.fromstring(z.read(name))
    out = []
    for para in root.iter(A + "p"):
        t = "".join(x.text or "" for x in para.iter(A + "t")).strip()
        if t:
            out.append(t)
    return out


def pinyin_of(body: str) -> str:
    found = []
    for line in body.splitlines():
        m = TAIL.search(line)
        if m:
            piece = line[m.start():].strip("：: ；;，,")
            if any(c in TONE for c in piece) and piece not in found:
                found.append(piece)
    return " / ".join(found[:4])


def main() -> int:
    apply = "--apply" in sys.argv
    words = json.loads(DATA.read_text(encoding="utf-8"))
    lex = {e["headword"] for e in words}
    xh = json.loads(XH.read_text(encoding="utf-8")) if XH.exists() else {}

    z = zipfile.ZipFile(PPTX)
    slides = sorted([n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
                    key=lambda n: int("".join(c for c in n if c.isdigit())))

    pages = []
    for idx, name in enumerate(slides, 1):
        ls = lines_of(z, name)
        if not ls:
            continue
        head = ls[0].replace(" ", "").replace("\u3000", "").rstrip("：:")
        if 2 <= len(head) <= 3 and not PUNCT.search(head) and all(CJK.match(c) for c in head):
            pages.append((idx, head, "\n".join(ls[1:]).strip()))

    print(f"简繁并列页 {len(pages)}")

    created, merged_alias = [], []
    for idx, head, body in pages:
        main, aliases = head[0], head[1:]
        existing = next((e for e in words if e["headword"] == main), None)
        if existing:
            ch = existing.setdefault("character", {}) or {}
            have = set(filter(None, (ch.get("traditional") or "")))
            add = "".join(a for a in aliases if a not in have)
            if add:
                ch["traditional"] = (ch.get("traditional") or "") + add
                existing["character"] = ch
                merged_alias.append((main, add))
            continue

        dup = next((e for e in created if e['headword'] == main), None)
        if dup is not None:
            old_body = dup['senses'][0]['definition']
            extra = [l for l in body.splitlines() if l not in set(old_body.splitlines())]
            if extra:
                dup['senses'][0]['definition'] = old_body.rstrip() + '\n' + '\n'.join(extra)
            continue

        info = xh.get(main) or {}
        created.append({
            "id": f"c-{main}",
            "headword": main,
            "lang": "zh",
            "frequency": None,
            "pronunciation": {"pinyin": pinyin_of(body) or info.get("pinyin", ""), "uk": "", "us": ""},
            "wordForms": [],
            "character": {"radical": info.get("radical", ""),
                          "strokes": str(info.get("strokes", "") or ""),
                          "traditional": "".join(aliases)},
            "senses": [{"pos": "", "definition": body, "definitionZh": "", "examples": [],
                        "synonyms": [], "collocations": [], "labels": [], "note": "", "images": []}],
            "phrases": [], "etymology": "", "images": [], "tags": ["繁简"],
        })

    print(f"新建 {len(created)} 条，给已有条目补繁体 {len(merged_alias)} 个")
    print("新建样例:", " ".join(e["headword"] + "(" + e["character"]["traditional"] + ")" for e in created[:20]))
    print("含「爱」:", any(e["headword"] == "爱" for e in created))
    for e in created[:4]:
        print(f"  【{e['headword']}】{e['pronunciation']['pinyin']} 繁{e['character']['traditional']} 部{e['character']['radical']}")
        print("     ", (e["senses"][0]["definition"].splitlines() or [""])[0][:60])

    if apply:
        words.extend(created)
        DATA.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n写入完成，共 {len(words)} 条")
    else:
        print("\n（预览，加 --apply 写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
