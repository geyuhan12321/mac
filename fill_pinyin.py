"""从 PPT 释义里抽取拼音，写入 pronunciation.pinyin。

规则：找「：」或「:」后面紧跟拼音音节的模式，例如
    字义：开口合不上了： hā          → hā
    ā 叹词，表示赞叹或惊异：啊，这…  → ā
用于「嗳」这类多音字时保留全部，用「/」分隔。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "words.json"

TONE = "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüńň"
TONE_RE = re.compile(f"[{TONE}]")
# 音节：声母+韵母，可带声调
SYL = f"[a-zA-Z{TONE}]{{1,7}}"
TAIL = re.compile(f"[:：]\\s*({SYL})\\s*[；;，,]?\\s*$")
HEAD = re.compile(f"^\\s*({SYL})\\s*(?=[\\u3400-\\u9fff])")     # 行首音节
STANDALONE = re.compile(f"^\\s*({SYL})\\s*$")


def valid(s: str) -> bool:
    s = s.strip()
    if not s or len(s) > 7:
        return False
    if not re.fullmatch(f"[a-z{TONE}]+", s):
        return False
    if not TONE_RE.search(s):       # 必须带声调，避免把英文单词当拼音
        return False
    return True


def extract(definition: str) -> list[str]:
    out: list[str] = []
    for line in definition.splitlines():
        m = TAIL.search(line)
        if m and valid(m.group(1)):
            out.append(m.group(1).strip())
            continue
        m = HEAD.match(line)
        if m and valid(m.group(1)):
            out.append(m.group(1).strip())
            continue
        m = STANDALONE.match(line)
        if m and valid(m.group(1)):
            out.append(m.group(1).strip())
    # 去重保序
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def main() -> int:
    apply = "--apply" in sys.argv
    data = json.loads(DATA.read_text(encoding="utf-8"))

    filled, multi, samples = 0, 0, []
    for e in data:
        if e.get("pronunciation", {}).get("pinyin"):
            continue
        s = e.get("senses") or [{}]
        line = s[0].get("definition", "")
        pys = extract(line)
        if not pys:
            # 再看其它行（有些字音在第二行）
            for ln in line.splitlines()[1:]:
                pys = extract(ln)
                if pys:
                    break
        if pys:
            filled += 1
            if len(pys) > 1:
                multi += 1
            if len(samples) < 10:
                samples.append((e["headword"], pys))
            if apply:
                e["pronunciation"]["pinyin"] = " / ".join(pys)

    print(f"已补拼音: {filled} / {len(data)}")
    print(f"其中多音: {multi}")
    print("\n样例:")
    for ch, pys in samples:
        print(f"  {ch}: {' / '.join(pys)}")

    if apply:
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已写入")
    else:
        print("\n（预览模式，加 --apply 写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
