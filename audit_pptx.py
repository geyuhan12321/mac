"""逐页核对 PPT 与词库：找出被漏掉的字。

输出：
  data/ppt_audit.json   结构化结果
  preview/ppt_audit.md  可读报告
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

BASE = Path(r"C:\Users\ge\Downloads\collins-dict-desktop")
PPTX = Path(r"C:\Users\ge\.dsh\attachments\v1\files\23\232fecff6fc8e87523f02331a810ad837494cd1085501a30e90505197cc4005a\汉字字典（拼音顺序版）.pptx")
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
CJK = re.compile(r"[\u3400-\u9fff]")
BAD = re.compile(r"[：:，,。；;、！？（）()\[\]【】\s]")


def main() -> int:
    words = json.loads((BASE / "data" / "words.json").read_text(encoding="utf-8"))
    lexicon = {e["headword"] for e in words}
    print(f"词库 {len(lexicon)} 个字")

    z = zipfile.ZipFile(PPTX)
    slides = sorted(
        [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
        key=lambda n: int("".join(c for c in n if c.isdigit())),
    )
    print(f"PPT {len(slides)} 页")

    rows = []
    for idx, name in enumerate(slides, 1):
        root = ET.fromstring(z.read(name))
        lines = []
        for para in root.iter(A + "p"):
            t = "".join(x.text or "" for x in para.iter(A + "t")).strip()
            if t:
                lines.append(t)
        head = lines[0] if lines else ""
        head_ns = head.replace(" ", "").replace("\u3000", "")
        chars = [c for c in head_ns if CJK.match(c)]
        # 单字页，或「简繁并列」页（2-3 字、无标点）
        single = bool(len(head) == 1 and CJK.match(head)) or (
            bool(2 <= len(head_ns) <= 3 and all(CJK.match(c) for c in head_ns)
                 and not re.search(r"[：:，,。；;、！？（）()\[\]【】]", head_ns)))
        rows.append({
            "page": idx,
            "head": head[:40],
            "single": single,
            "chars": chars,
            "in_lexicon": (head_ns[0] in lexicon) if single else None,
            "any_in": [c for c in chars if c in lexicon],
            "lines": len(lines),
        })

    single_pages = [r for r in rows if r["single"]]
    multi_pages = [r for r in rows if not r["single"] and r["head"]]
    empty_pages = [r for r in rows if not r["head"]]

    missing_single = [r for r in single_pages if not r["in_lexicon"]]
    # 多字页里出现、但词库没收的字
    multi_missing = {}
    for r in multi_pages:
        for c in r["chars"]:
            if c not in lexicon:
                multi_missing.setdefault(c, []).append(r["page"])

    print(f"\n单字页 {len(single_pages)}，其中词库缺失 {len(missing_single)}")
    print(f"多字页 {len(multi_pages)}，空白页 {len(empty_pages)}")

    # 单字页缺失 = 真正的遗漏
    miss_chars = sorted({r["head"].replace(" ", "")[0] for r in missing_single})
    print(f"单字页缺失的字 {len(miss_chars)}: {''.join(miss_chars)}")

    report = []
    report.append("# PPT 逐页核对报告\n")
    report.append(f"- PPT 页数：{len(slides)}")
    report.append(f"- 词库字数：{len(lexicon)}")
    report.append(f"- 单字页：{len(single_pages)}（其中词库缺失 {len(missing_single)}）")
    report.append(f"- 多字页：{len(multi_pages)}")
    report.append(f"- 空白页：{len(empty_pages)}\n")

    report.append("## 一、单字页里词库没有的（真正的遗漏）\n")
    if missing_single:
        report.append(f"共 {len(missing_single)} 页，涉及 {len(miss_chars)} 个字：\n")
        report.append("```")
        report.append("".join(miss_chars))
        report.append("```\n")
        report.append("| 页码 | 首行 |")
        report.append("|---|---|")
        for r in missing_single[:200]:
            report.append(f"| {r['page']} | {r['head']} |")
    else:
        report.append("无。\n")

    report.append("\n## 二、多字页里出现、词库未收的字\n")
    if multi_missing:
        items = sorted(multi_missing.items(), key=lambda kv: -len(kv[1]))
        report.append(f"共 {len(items)} 个字（这些页不是单字条目，仅供补录参考）：\n")
        report.append("| 字 | 出现页数 | 示例页 |")
        report.append("|---|---|---|")
        for ch, pages in items[:120]:
            report.append(f"| {ch} | {len(pages)} | {pages[0]} |")
    else:
        report.append("无。\n")

    report.append("\n## 三、重复页（同一字出现多次）\n")
    seen = {}
    for r in single_pages:
        seen.setdefault(r["head"], []).append(r["page"])
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    if dups:
        report.append("| 字 | 页 |")
        report.append("|---|---|")
        for ch, pages in sorted(dups.items())[:80]:
            report.append(f"| {ch} | {', '.join(map(str, pages))} |")
    else:
        report.append("无。\n")

    out_json = BASE / "data" / "ppt_audit.json"
    out_json.write_text(json.dumps({
        "pages": len(slides),
        "lexicon": len(lexicon),
        "single_pages": len(single_pages),
        "missing_single_pages": len(missing_single),
        "missing_chars": miss_chars,
        "multi_missing": {k: v for k, v in multi_missing.items()},
        "duplicates": dups,
        "rows": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    md = BASE / "preview" / "ppt_audit.md"
    md.parent.mkdir(exist_ok=True)
    md.write_text("\n".join(report), encoding="utf-8")

    print(f"\n报告：{md}")
    print(f"数据：{out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
