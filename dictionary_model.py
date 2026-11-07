"""数据层：词条规范化、分词索引、CSV/JSON 导入导出。

与网页版 data/words.json 完全同构 —— 两边可以互相直接读写同一份文件。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import uuid
from typing import Any, Iterable

CJK_CHAR = re.compile(r"[\u3400-\u9fff]")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*|[\u3400-\u9fff]+|[^A-Za-z\u3400-\u9fff]+")

# 停用词不加链接，否则一屏都是下划线
STOP = {
    "the", "a", "an", "to", "of", "and", "or", "in", "on", "at", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "these", "those",
    "i", "you", "he", "she", "we", "they", "my", "your", "his", "her", "their",
    "as", "by", "from", "but", "not", "no", "do", "does", "did", "have", "has", "had",
    "will", "would", "can", "could", "so", "if", "than", "then", "there", "here",
    "very", "too", "me", "him", "them", "us", "its",
}


def has_cjk(s: Any) -> bool:
    return bool(CJK_CHAR.search(str(s or "")))


def norm_form(s: Any) -> str:
    """英文词形归一：小写、去掉撇号与标点。中文原样保留。"""
    t = str(s or "").lower()
    t = re.sub(r"[’']", "", t)
    t = re.sub(r"[^0-9a-z\u3400-\u9fff]", "", t)
    return t


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [_s(x) for x in v if _s(x)]
    return [p.strip() for p in re.split(r"[|｜]", _s(v)) if p.strip()]


def _examples(v: Any) -> list[dict]:
    out: list[dict] = []
    if isinstance(v, list):
        for x in v:
            if isinstance(x, str):
                out.append({"text": x, "translation": "", "source": ""})
            elif isinstance(x, dict):
                out.append({
                    "text": _s(x.get("text") or x.get("en") or x.get("sentence") or x.get("例句")),
                    "translation": _s(x.get("translation") or x.get("zh") or x.get("翻译") or x.get("译文")),
                    "source": _s(x.get("source") or x.get("来源")),
                })
    elif isinstance(v, str):
        out = [{"text": t, "translation": "", "source": ""} for t in _list(v)]
    return [x for x in out if x["text"] or x["translation"]]


def _forms(v: Any) -> list[dict]:
    if not v:
        return []
    if isinstance(v, str):
        return [{"label": "词形", "value": v.strip()}] if v.strip() else []
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, str):
                out.append({"label": "词形", "value": x})
            elif isinstance(x, dict):
                out.append({
                    "label": _s(x.get("label") or x.get("name")) or "词形",
                    "value": _s(x.get("value") or x.get("form")),
                })
        return [x for x in out if x["value"]]
    if isinstance(v, dict):
        return [{"label": _s(k), "value": _s(val)} for k, val in v.items() if _s(val)]
    return []


def _character(raw: dict) -> dict | None:
    c = raw.get("character") if isinstance(raw.get("character"), dict) else raw
    out = {
        "radical": _s(c.get("radical") or c.get("部首")),
        "strokes": _s(c.get("strokes") or c.get("笔画")),
        "traditional": _s(c.get("traditional") or c.get("繁体")),
        "variants": _list(c.get("variants") or c.get("异体")),
        "measureWords": _list(c.get("measureWords") or c.get("量词")),
    }
    if not any([out["radical"], out["strokes"], out["traditional"], out["variants"], out["measureWords"]]):
        return None
    return out


def _phrases(v: Any) -> list[dict]:
    if not v:
        return []
    out: list[dict] = []
    if isinstance(v, list):
        for x in v:
            if isinstance(x, str):
                parts = re.split(r"\s*[—–-]{1,2}\s*", x, maxsplit=1)
                out.append({"phrase": _s(parts[0]), "meaning": _s(parts[1]) if len(parts) > 1 else ""})
            elif isinstance(x, dict):
                out.append({
                    "phrase": _s(x.get("phrase") or x.get("p")),
                    "meaning": _s(x.get("meaning") or x.get("def") or x.get("mean")),
                })
    elif isinstance(v, dict):
        out = [{"phrase": _s(k), "meaning": _s(val)} for k, val in v.items()]
    return [x for x in out if x["phrase"]]


def _sense(raw: Any) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return {"pos": "", "definition": raw, "definitionZh": "", "examples": [],
                "synonyms": [], "collocations": [], "labels": [], "note": ""}
    if not isinstance(raw, dict):
        return None
    ex = _examples(raw.get("examples"))
    if not ex and (raw.get("example") or raw.get("example_zh")):
        left = _list(raw.get("example") or raw.get("例句"))
        right = _list(raw.get("example_zh") or raw.get("例句翻译"))
        ex = [{"text": t, "translation": right[i] if i < len(right) else "",
               "source": _s(raw.get("example_source") or raw.get("例句来源"))} for i, t in enumerate(left)]
    return {
        "pos": _s(raw.get("pos") or raw.get("词性")),
        "definition": _s(raw.get("definition") or raw.get("def") or raw.get("释义")),
        "definitionZh": _s(raw.get("definitionZh") or raw.get("definition_zh") or raw.get("中文释义")),
        "examples": ex,
        "synonyms": _list(raw.get("synonyms") or raw.get("同义词") or raw.get("近义词")),
        "collocations": _list(raw.get("collocations") or raw.get("搭配")),
        "labels": _list(raw.get("labels") or raw.get("标注")),
        "note": _s(raw.get("note") or raw.get("备注") or raw.get("用法")),
    }


def normalize_entry(raw: Any) -> dict | None:
    """把任意来源的一条数据整理成标准词条；缺词条名则返回 None。"""
    if not isinstance(raw, dict):
        return None
    headword = _s(raw.get("headword") or raw.get("word") or raw.get("term")
                  or raw.get("词条") or raw.get("单词") or raw.get("字"))
    if not headword:
        return None

    pron_raw = raw.get("pronunciation")
    pron = {"uk": "", "us": "", "pinyin": "", "audio": ""}
    if isinstance(pron_raw, str):
        pron["uk"] = pron_raw
    elif isinstance(pron_raw, dict):
        pron["uk"] = _s(pron_raw.get("uk") or pron_raw.get("ipa") or pron_raw.get("en"))
        pron["us"] = _s(pron_raw.get("us"))
        pron["pinyin"] = _s(pron_raw.get("pinyin"))
        pron["audio"] = _s(pron_raw.get("audio"))
    pron["uk"] = pron["uk"] or _s(raw.get("ipa_uk") or raw.get("ipa") or raw.get("英音"))
    pron["us"] = pron["us"] or _s(raw.get("ipa_us") or raw.get("美音"))
    pron["pinyin"] = pron["pinyin"] or _s(raw.get("pinyin") or raw.get("拼音"))

    freq = raw.get("frequency", raw.get("词频"))
    frequency = None
    if freq not in ("", None):
        try:
            frequency = max(1, min(5, int(round(float(freq)))))
        except (TypeError, ValueError):
            frequency = None

    senses = []
    if isinstance(raw.get("senses"), list):
        senses = [s for s in (_sense(x) for x in raw["senses"]) if s]
    elif isinstance(raw.get("senses"), dict):
        senses = [s for s in (_sense(x) for x in raw["senses"].values()) if s]
    if not senses and any(raw.get(k) for k in ("definition", "def", "释义", "definitionZh", "definition_zh")):
        senses = [_sense({
            "pos": raw.get("pos"),
            "definition": raw.get("definition") or raw.get("def") or raw.get("释义"),
            "definitionZh": raw.get("definitionZh") or raw.get("definition_zh"),
            "example": raw.get("example"),
            "example_zh": raw.get("example_zh"),
        })]

    homo = raw.get("homograph")
    try:
        homograph = 0 if homo in (0, "0") else (int(homo) if homo not in ("", None) else None)
    except (TypeError, ValueError):
        homograph = None

    return {
        "id": _s(raw.get("id")) or "w" + uuid.uuid4().hex[:8],
        "headword": headword,
        "homograph": homograph,
        "lang": _s(raw.get("lang")) or ("zh" if has_cjk(headword) else "en"),
        "frequency": frequency,
        "pronunciation": pron,
        "wordForms": _forms(raw.get("wordForms") or raw.get("word_forms") or raw.get("词形")),
        "character": _character(raw),
        "senses": senses,
        "phrases": _phrases(raw.get("phrases") or raw.get("短语")),
        "etymology": _s(raw.get("etymology") or raw.get("词源")),
        "tags": _list(raw.get("tags") or raw.get("分类")),
        "source": _s(raw.get("source") or raw.get("来源")),
        "updatedAt": _s(raw.get("updatedAt")) or time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ---------------------------------------------------------------- 分词 / 联想索引

class Index:
    """词形反查表 + 中文最长匹配 + 例句共现边（反链）。

    auto_new=True  ：没收录的英文词标成 miss（灰色可点 → 新建）
    auto_new=False ：严格模式，没收录的一律当普通文字，点不动
    """

    default_auto_new = True

    def __init__(self, entries: Iterable[dict], auto_new: bool | None = None):
        self.lemma: dict[str, str] = {}
        self.zh: set[str] = set()
        self.max_zh = 1
        self.inbound: dict[str, list[str]] = {}
        self.edges = 0
        self.auto_new = Index.default_auto_new if auto_new is None else bool(auto_new)
        self.entries: list[dict] = []
        self.rebuild(entries)

    def rebuild(self, entries: Iterable[dict]) -> None:
        entries = list(entries)
        self.entries = entries
        self.lemma.clear()
        self.zh.clear()
        self.inbound.clear()
        self.max_zh = 1
        self.edges = 0
        for e in entries:
            self._add(e["headword"], e["id"])
            for f in e.get("wordForms") or []:
                self._add(f.get("value", ""), e["id"])
        for e in entries:
            for s in e.get("senses") or []:
                for x in s.get("examples") or []:
                    for kind, _text, eid in self.tokenize(x.get("text", "")):
                        if kind != "link" or not eid or eid == e["id"]:
                            continue
                        bucket = self.inbound.setdefault(eid, [])
                        if e["id"] not in bucket:
                            bucket.append(e["id"])
                            self.edges += 1

    def _add(self, raw: Any, eid: str) -> None:
        for piece in re.split(r"[,，/、;；]", str(raw or "")):
            piece = piece.strip()
            if not piece:
                continue
            key = norm_form(piece)
            if not key:
                continue
            self.lemma.setdefault(key, eid)
            if has_cjk(piece):
                self.zh.add(piece)
                if len(piece) > self.max_zh:
                    self.max_zh = len(piece)

    def tokenize(self, text: Any) -> list[tuple[str, str, str | None]]:
        """把句子切成三种片段：

        link  词库里有这个字/词   → 渲染成可点链接
        miss  词库里没有的英文实词 → 渲染成灰色，点了去建词条
        text  标点、停用词、词库里没有的汉字 → 普通文字，不可点

        汉字永远只有 link / text 两种结果：库里有就点得进去，没有就是普通文字。
        """
        out: list[tuple[str, str, str | None]] = []
        for tok in TOKEN_RE.findall(str(text or "")):
            if CJK_CHAR.search(tok):
                i = 0
                while i < len(tok):
                    hit = ""
                    for size in range(min(self.max_zh, len(tok) - i), 0, -1):
                        cand = tok[i:i + size]
                        if cand in self.zh:
                            hit = cand
                            break
                    if hit:
                        out.append(("link", hit, self.lemma.get(norm_form(hit))))
                        i += len(hit)
                    else:
                        out.append(("text", tok[i], None))
                        i += 1
            elif tok[:1].isalpha():
                eid = self.lemma.get(norm_form(tok))
                if eid:
                    out.append(("link", tok, eid))
                elif norm_form(tok) in STOP or not self.auto_new:
                    out.append(("text", tok, None))
                else:
                    out.append(("miss", tok, None))
            else:
                out.append(("text", tok, None))
        return out

    def ledger(self, entry: dict) -> list[str]:
        """某词条例句里出现但词库还没收录的英文词。"""
        seen: list[str] = []
        for s in entry.get("senses") or []:
            for x in s.get("examples") or []:
                for kind, tok, _ in self.tokenize(x.get("text", "")):
                    if kind == "miss" and tok not in seen:
                        seen.append(tok)
        return seen


# ---------------------------------------------------------------- 存档

def load_entries(path: str | os.PathLike) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    arr = data if isinstance(data, list) else data.get("entries", [])
    return [e for e in (normalize_entry(x) for x in arr) if e]


def save_entries(path: str | os.PathLike, entries: list[dict]) -> None:
    folder = os.path.dirname(str(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


def entry_key(e: dict) -> str:
    return f"{e['headword']}||{'' if e.get('homograph') is None else e['homograph']}"


def merge(existing: list[dict], incoming: list[dict], mode: str = "upsert") -> list[dict]:
    """mode: upsert（同名词条覆盖）/ append（全量追加）/ replace（清空后导入）"""
    incoming = [e for e in incoming if e]
    if mode == "replace":
        return incoming
    if mode == "append":
        return existing + incoming
    table = {entry_key(e): e for e in existing}
    for e in incoming:
        old = table.get(entry_key(e))
        if old:
            e["id"] = old["id"]  # 保住链接稳定
        table[entry_key(e)] = e
    seen: set[str] = set()
    out = []
    for e in table.values():
        if e["id"] in seen:
            e["id"] = "w" + uuid.uuid4().hex[:8]
        seen.add(e["id"])
        out.append(e)
    return out


# ---------------------------------------------------------------- CSV

CSV_FIELDS = {
    "headword": ["headword", "word", "term", "词条", "单词", "字", "词"],
    "lang": ["lang", "language", "语言"],
    "homograph": ["homograph", "同形词", "同形词编号", "编号"],
    "frequency": ["frequency", "freq", "词频", "频段"],
    "pinyin": ["pinyin", "拼音"],
    "ipa_uk": ["ipa_uk", "uk", "英音", "英式音标"],
    "ipa_us": ["ipa_us", "us", "美音", "美式音标"],
    "pos": ["pos", "partofspeech", "词性"],
    "definition": ["definition", "def", "释义", "英文释义"],
    "definition_zh": ["definition_zh", "definitionzh", "译文", "中文释义", "汉语释义"],
    "example": ["example", "examples", "例句"],
    "example_zh": ["example_zh", "examplezh", "例句翻译", "例句译文"],
    "example_source": ["example_source", "来源", "例句来源"],
    "synonyms": ["synonyms", "synonym", "同义词", "近义词"],
    "collocations": ["collocations", "collocation", "搭配"],
    "labels": ["labels", "label", "标注", "标签"],
    "note": ["note", "备注", "用法"],
    "radical": ["radical", "部首"],
    "strokes": ["strokes", "笔画"],
    "traditional": ["traditional", "繁体", "繁体字"],
    "tags": ["tags", "tag", "分类"],
}

CSV_HEADER = ["headword", "lang", "homograph", "frequency", "pinyin", "ipa_uk", "ipa_us", "pos",
              "definition", "definition_zh", "example", "example_zh", "example_source",
              "synonyms", "collocations", "labels", "note", "radical", "strokes", "traditional", "tags"]


def _col_map(header: list[str]) -> dict[str, int]:
    norm = [h.strip().lower().replace(" ", "") for h in header]
    out: dict[str, int] = {}
    for field, aliases in CSV_FIELDS.items():
        for i, h in enumerate(norm):
            if h in [a.lower().replace(" ", "") for a in aliases]:
                out[field] = i
                break
    return out


def entries_from_csv(text: str) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if len(rows) < 2:
        return [], ["CSV 至少需要表头 + 一行数据"]
    cmap = _col_map(rows[0])
    if "headword" not in cmap:
        return [], ["CSV 表头缺少 headword / 词条 列"]

    groups: dict[tuple[str, str], dict] = {}
    for n, row in enumerate(rows[1:], start=2):
        def get(field: str) -> str:
            i = cmap.get(field)
            return "" if i is None or i >= len(row) else str(row[i]).strip()

        hw = get("headword")
        if not hw:
            errors.append(f"第 {n} 行：headword 为空，已跳过")
            continue
        homo = get("homograph")
        key = (hw, homo)
        if key not in groups:
            groups[key] = {
                "headword": hw, "homograph": homo, "lang": get("lang"),
                "frequency": get("frequency"), "pinyin": get("pinyin"),
                "ipa_uk": get("ipa_uk"), "ipa_us": get("ipa_us"),
                "radical": get("radical"), "strokes": get("strokes"),
                "traditional": get("traditional"), "tags": get("tags"), "senses": [],
            }
        en = [s.strip() for s in re.split(r"[|｜]", get("example")) if s.strip()]
        zh = [s.strip() for s in re.split(r"[|｜]", get("example_zh"))]
        groups[key]["senses"].append({
            "pos": get("pos"), "definition": get("definition"),
            "definition_zh": get("definition_zh"),
            "examples": [{"text": t, "translation": zh[i] if i < len(zh) else "",
                          "source": get("example_source")} for i, t in enumerate(en)],
            "synonyms": _list(get("synonyms")), "collocations": _list(get("collocations")),
            "labels": _list(get("labels")), "note": get("note"),
        })
    entries = [e for e in (normalize_entry(x) for x in groups.values()) if e]
    return entries, errors


def entries_to_csv(entries: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for e in entries:
        pron = e.get("pronunciation") or {}
        char = e.get("character") or {}
        senses = e.get("senses") or [{}]
        for s in senses:
            ex = s.get("examples") or []
            writer.writerow([
                e["headword"], e.get("lang", ""), e.get("homograph") if e.get("homograph") is not None else "",
                e.get("frequency") if e.get("frequency") is not None else "",
                pron.get("pinyin", ""), pron.get("uk", ""), pron.get("us", ""),
                s.get("pos", ""), s.get("definition", ""), s.get("definitionZh", ""),
                "|".join(x.get("text", "") for x in ex),
                "|".join(x.get("translation", "") for x in ex),
                ex[0].get("source", "") if ex else "",
                "|".join(s.get("synonyms") or []), "|".join(s.get("collocations") or []),
                "|".join(s.get("labels") or []), s.get("note", ""),
                char.get("radical", ""), char.get("strokes", ""), char.get("traditional", ""),
                "|".join(e.get("tags") or []),
            ])
    return buf.getvalue()
