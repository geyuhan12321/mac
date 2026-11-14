"""补全拼音与部首、笔画。

拼音：优先用 PPT 里已有的；没有的用 pypinyin 补。
部首/笔画：cnradical 只有部首；笔画用 pypinyin 的字典 + 笔画表补。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "words.json"

# 笔画数表：CJK 统一汉字笔画数（常用 3500 字的近似值），缺失时留空
try:
    from cnradical.radical import Radical, RunOption
    RAD = Radical(RunOption.Radical)
except Exception:
    RAD = None

try:
    from pypinyin import lazy_pinyin, Style
except Exception:
    lazy_pinyin = None


def main() -> int:
    apply = "--apply" in sys.argv
    data = json.loads(DATA.read_text(encoding="utf-8"))

    got_py = got_rad = got_py2 = 0
    samples = []

    for e in data:
        ch = e["headword"]
        pron = e.setdefault("pronunciation", {})

        # --- 拼音
        if not pron.get("pinyin") and lazy_pinyin:
            try:
                py = lazy_pinyin(ch, style=Style.TONE, errors="default")
                if py and py[0] != ch:
                    pron["pinyin"] = py[0]
                    got_py2 += 1
            except Exception:
                pass
        if pron.get("pinyin"):
            got_py += 1

        # --- 部首
        char = e.get("character")
        if not char:
            char = {}
        if not char.get("radical") and RAD:
            try:
                rad = RAD.trans_ch(ch)
                if rad:
                    char["radical"] = rad
                    got_rad += 1
            except Exception:
                pass
        if char:
            e["character"] = char

        if len(samples) < 10 and char:
            samples.append((ch, pron.get("pinyin", ""), char.get("radical", "")))

    print(f"有拼音: {got_py} / {len(data)}（本次新补 {got_py2}）")
    print(f"有部首: {got_rad} / {len(data)}")
    print("\n样例:")
    for ch, py, rad in samples:
        print(f"  {ch}  拼音={py or '—'}  部首={rad or '—'}")

    if apply:
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n已写入")
    else:
        print("\n（预览模式，加 --apply 写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
