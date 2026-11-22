"""把 PPT 里同一字的后续页内容合并进已有词条（不新增字，只补内容）。"""
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
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
CJK = re.compile(r"[\u3400-\u9fff]")


def page_lines(z, name: str) -> list[str]:
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
    by_head = {e["headword"]: e for e in words if len(e["headword"]) == 1}

    z = zipfile.ZipFile(PPTX)
    slides = sorted([n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
                    key=lambda n: int("".join(c for c in n if c.isdigit())))

    pages: dict[str, list[tuple[int, list[str]]]] = {}
    for idx, name in enumerate(slides, 1):
        lines = page_lines(z, name)
        if not lines:
            continue
        head = lines[0]
        if len(head) == 1 and CJK.match(head):
            pages.setdefault(head, []).append((idx, lines))

    merged_chars, added_lines = [], 0
    samples = []
    for head, plist in pages.items():
        if len(plist) < 2:
            continue
        entry = by_head.get(head)
        if not entry:
            continue
        sense = (entry.get("senses") or [{}])[0]
        have = [l.strip() for l in sense.get("definition", "").splitlines()]
        have_set = set(have)
        extra = []
        for _idx, lines in plist[1:]:
            for line in lines[1:]:
                s = line.strip()
                if s and s not in have_set and s not in extra:
                    extra.append(s)
        if not extra:
            continue
        merged_chars.append(head)
        added_lines += len(extra)
        if len(samples) < 8:
            samples.append((head, plist[0][0], [p[0] for p in plist[1:]], extra[:3]))
        if apply:
            sense["definition"] = (sense.get("definition", "").rstrip()
                                   + "\n" + "\n".join(extra))

    print(f"重复页的字 {sum(1 for p in pages.values() if len(p) > 1)}，"
          f"可合并 {len(merged_chars)} 个，补入 {added_lines} 行")
    for head, p0, ps, extra in samples:
        print(f"\n【{head}】主页 {p0}，补充页 {ps}")
        for l in extra:
            print("    +", l[:70])

    if apply:
        DATA.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已写入，共 {len(words)} 条")
    else:
        print("\n（预览，加 --apply 写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
