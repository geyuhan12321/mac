"""从释义里抽例句（严格版）。

只认两类：
  A. 带「——」出处标记的引文        ← 一定是例句
  B. 冒号后面跟完整句子，且句子含句末标点 / 引号 / 感叹
     （「字形：」「字义：」这类解释行一律排除）

用法：python extract_examples.py [--apply]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "words.json"

CITE = re.compile(r"——|\u2014\u2014")
# 这些行首是解释，不是例句
EXPLAIN = ("字形", "字义", "本义", "释义", "引申", "通假", "参见", "同", "注")
SENTENCE = re.compile(r"[。！？!?]")


def split_cite(text):
    m = CITE.search(text)
    if not m:
        return text.strip(), ""
    return text[:m.start()].strip(), text[m.end():].strip().rstrip("。").strip()


def clean(s):
    return s.strip().strip("「」“”\"'").rstrip("。；;，,").strip()


def extract(definition: str) -> list[dict]:
    out = []
    for raw in definition.splitlines():
        line = raw.strip()
        if not line or len(line) < 6:
            continue
        if line.startswith(EXPLAIN):
            continue                       # 「字形：…」这类跳过

        # A. 带出处的引文
        if CITE.search(line):
            body, src = split_cite(line)
            body = clean(body)
            # 去掉冒号前的引导语
            if "：" in body:
                head, tail = body.split("：", 1)
                if len(head) < 30:
                    body = clean(tail)
            if len(body) >= 6:
                out.append({"text": body, "translation": "", "source": src})
            continue

        # B. 冒号后是完整句子
        if "：" in line or ":" in line:
            head, tail = re.split(r"[：:]", line, maxsplit=1)
            tail = tail.strip()
            if len(head) >= 30:
                continue
            if SENTENCE.search(tail) and len(tail) >= 8:
                body, src = split_cite(tail)
                body = clean(body)
                if len(body) >= 6:
                    out.append({"text": body, "translation": "", "source": src})
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    entries = json.loads(DATA.read_text(encoding="utf-8"))
    total, with_ex, samples = 0, 0, []

    for e in entries:
        if not e.get("senses"):
            continue
        s = e["senses"][0]
        ex = extract(s.get("definition", ""))
        if ex:
            with_ex += 1
            total += len(ex)
            if len(samples) < 10:
                samples.append((e["headword"], ex[:2]))
            if apply:
                s["examples"] = ex

    print(f"含例句的词条: {with_ex} / {len(entries)}")
    print(f"例句总数: {total}\n")
    for ch, ex in samples:
        print(f"  【{ch}】")
        for x in ex:
            src = f"   ——{x['source']}" if x["source"] else ""
            print(f"     {x['text']}{src}")

    if apply:
        DATA.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已写入 {DATA}")
    else:
        print("\n（预览模式，加 --apply 才写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
