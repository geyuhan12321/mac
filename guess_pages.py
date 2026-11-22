"""从说明页里反推「整页在讲哪个字」。

线索：
 1. 冒号后紧跟的单字 + 空格，如「…：安 安心 安全」
 2. 页面里出现最多的「词首字」（组词都以该字开头）
 3. 「字形：左是X，右是Y」里 X/Y 组合不出目标字时，用词首字兜底
"""
from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

BASE = Path(r"C:\Users\ge\Downloads\collins-dict-desktop")
PPTX = Path(r"C:\Users\ge\.dsh\attachments\v1\files\23\232fecff6fc8e87523f02331a810ad837494cd1085501a30e90505197cc4005a\汉字字典（拼音顺序版）.pptx")
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
CJK = re.compile(r"[\u3400-\u9fff]")
PUNCT = re.compile(r"[：:，,。；;、！？（）()\[\]【】\s]")

lex = {e["headword"] for e in json.loads((BASE / "data" / "words.json").read_text(encoding="utf-8"))}

z = zipfile.ZipFile(PPTX)
slides = sorted([n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
                key=lambda n: int("".join(c for c in n if c.isdigit())))


def lines_of(name):
    root = ET.fromstring(z.read(name))
    out = []
    for para in root.iter(A + "p"):
        t = "".join(x.text or "" for x in para.iter(A + "t")).strip()
        if t:
            out.append(t)
    return out


def is_entry_page(head: str) -> bool:
    h = head.replace(" ", "").replace("\u3000", "").rstrip("：:")
    if len(h) == 1 and CJK.match(h):
        return True
    return bool(2 <= len(h) <= 3 and all(CJK.match(c) for c in h) and not PUNCT.search(h))


def guess_char(lines: list[str]) -> tuple[str, str]:
    """返回 (候选字, 依据)。"""
    body = "\n".join(lines)

    # 线索1：冒号后紧跟 单字+空格
    m = re.search(r"[：:]\s*([\u3400-\u9fff])\s", body)
    if m:
        return m.group(1), "冒号后单字"

    # 线索2：词首字统计（按空格/、/，分隔的词，取首字）
    tokens = re.findall(r"[\u3400-\u9fff]{1,6}", body.replace("、", " ").replace("，", " "))
    heads = Counter(t[0] for t in tokens if len(t) >= 2)
    if heads:
        ch, n = heads.most_common(1)[0]
        if n >= 3:
            return ch, f"词首字×{n}"

    # 线索3：行首的「X：」形式
    for line in lines:
        m2 = re.match(r"^([\u3400-\u9fff])[：:]", line)
        if m2:
            return m2.group(1), "行首字"

    return "", ""


def main() -> int:
    rows = []
    for idx, name in enumerate(slides, 1):
        ls = lines_of(name)
        if not ls:
            continue
        head = ls[0]
        if is_entry_page(head):
            continue
        ch, why = guess_char(ls)
        rows.append({"page": idx, "head": head[:40], "guess": ch, "why": why,
                     "missing": bool(ch and ch not in lex)})

    usable = [r for r in rows if r["guess"]]
    missing = [r for r in usable if r["missing"]]
    print(f"说明页 {len(rows)}，能猜出目标字 {len(usable)}，其中词库没有 {len(missing)}")

    print("\n可补的字（按出现顺序，去重）:")
    seen, chars = set(), []
    for r in missing:
        if r["guess"] not in seen:
            seen.add(r["guess"])
            chars.append(r["guess"])
    print(f"共 {len(chars)} 个: {''.join(chars[:80])}")

    print("\n样例：")
    for r in missing[:12]:
        print(f"  第{r['page']}页 [{r['why']}] → {r['guess']}   首行：{r['head'][:36]}")

    out = BASE / "data" / "guess_pages.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
