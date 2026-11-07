"""渲染层：把词条拼成 Qt 富文本（QTextBrowser 能吃的那部分 HTML）。

黑白灰排版，参照柯林斯词典的词条页：一套字号层级 + 细线 + 留白，
不用填充色块、不用彩色标签。Qt 富文本只认 CSS 2.1 子集，所以结构一律用 table 搭。
"""
from __future__ import annotations

from html import escape
from urllib.parse import quote

INK = "#111111"       # 正文/词目
GRAY = "#5f5f5f"      # 次级说明
MUTED = "#9a9a9a"     # 标签、注释
LINE = "#e6e6e6"      # 细线
HAIR = "#efefef"
SOFT = "#f7f7f7"

SERIF = "Georgia,'Times New Roman',SimSun,serif"
SANS = "'Microsoft YaHei UI','Microsoft YaHei',Segoe UI,sans-serif"


def esc(text) -> str:
    return escape(str(text or ""), quote=False)


def attr(text) -> str:
    return escape(str(text or ""), quote=True)


def href_entry(eid: str) -> str:
    return f"app://w/{quote(str(eid), safe='')}"


def href_new(word: str) -> str:
    return f"app://new/{quote(str(word), safe='')}"


def href_act(name: str) -> str:
    return f"app://act/{quote(str(name), safe='')}"


SUP = str.maketrans("0123456789", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079")


def sup(n) -> str:
    return str(n).translate(SUP)


def rule(width: str = "100%", color: str = LINE) -> str:
    """1px 细线：靠 1pt 字号的小格压出高度，避免整行被撑粗。"""
    return f'<hr width="{width}" style="color:{color};background-color:{color};border:none;">' 


def freq_html(n, small: bool = False) -> str:
    level = int(n or 0)
    size = "8pt" if small else "9pt"
    cells = "".join(
        f'<span style="color:{INK if i < level else "#dcdcdc"};">\u25a0</span>'
        for i in range(5)
    )
    return f'<span style="font-size:{size};">{cells}</span>'


def link_html(text: str, entry: dict, index) -> str:
    """例句里的词：已收录=黑色下划线可点；未收录=灰色可点建条；当前词=加粗。"""
    parts: list[str] = []
    for kind, tok, eid in index.tokenize(text):
        if kind == "text":
            parts.append(esc(tok))
        elif kind == "link":
            if entry and eid == entry.get("id"):
                parts.append(f'<span style="font-weight:bold;color:{INK};">{esc(tok)}</span>')
            else:
                parts.append(
                    f'<a href="{attr(href_entry(eid))}" style="color:{INK};text-decoration:underline;">'
                    f'{esc(tok)}</a>'
                )
        else:
            parts.append(
                f'<a href="{attr(href_new(tok))}" style="color:{MUTED};text-decoration:underline;">'
                f'{esc(tok)}</a>'
            )
    return "".join(parts)


def _meta(sense: dict) -> str:
    groups: list[str] = []
    if sense.get("synonyms"):
        groups.append("同义词 " + "、".join(sense["synonyms"]))
    if sense.get("collocations"):
        groups.append("搭配 " + "、".join(sense["collocations"]))
    if sense.get("labels"):
        groups.append("、".join(sense["labels"]))
    if not groups:
        return ""
    sep = '<span style="color:#d6d6d6;">\u3000\uff5c\u3000</span>'
    return f'<p style="margin:9px 0 0;font-size:9pt;color:{GRAY};">{sep.join(groups)}</p>'


def _sense(sense: dict, idx: int, entry: dict, index) -> str:
    bits: list[str] = []
    if sense.get("pos"):
        bits.append(
            f'<p style="margin:0 0 3px;color:{MUTED};font-size:8pt;letter-spacing:1px;">'
            f'{esc(sense["pos"]).upper()}</p>'
        )
    if sense.get("definition"):
        bits.append(f'<p style="margin:0 0 4px;color:{INK};font-size:11.5pt;">'
                    f'{esc(sense["definition"])}</p>')
    if sense.get("definitionZh"):
        bits.append(f'<p style="margin:0 0 7px;color:{GRAY};font-size:10pt;">'
                    f'{esc(sense["definitionZh"])}</p>')

    for ex in sense.get("examples") or []:
        inner = f'<span style="font-size:10.5pt;color:#333333;">{link_html(ex.get("text", ""), entry, index)}</span>'
        if ex.get("translation"):
            inner += (f'<p style="margin:3px 0 0;color:{MUTED};font-size:9pt;">'
                      f'{esc(ex["translation"])}</p>')
        if ex.get("source"):
            inner += (f'<p style="margin:2px 0 0;color:#b3b3b3;font-size:8pt;">'
                      f'{esc(ex["source"])}</p>')
        bits.append(
            f'<table width="100%" cellspacing="0" cellpadding="5"><tr>'
            f'<td style="border-left:2px solid #e0e0e0;">{inner}</td></tr></table>'
        )
    if sense.get("note"):
        bits.append(f'<p style="margin:5px 0 0;color:{MUTED};font-size:9pt;">'
                    f'用法 {esc(sense["note"])}</p>')
    bits.append(_meta(sense))

    body = "".join(bits)
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
        f'<td width="26" valign="top" align="right">'
        f'<span style="color:{MUTED};font-size:10pt;font-family:{SERIF};">{idx + 1}</span>'
        f'</td><td width="10"></td>'
        f'<td valign="top">{body}</td></tr></table>'
        f'<p style="margin:0;font-size:12pt;"></p>'
    )


def _char_bar(entry: dict) -> str:
    char = entry.get("character")
    if not char:
        return ""
    cells = []
    for label, value in (
        ("部首", char.get("radical")),
        ("笔画", char.get("strokes")),
        ("繁体", char.get("traditional")),
        ("异体", " ".join(char.get("variants") or [])),
        ("量词", " ".join(char.get("measureWords") or [])),
    ):
        if not value:
            continue
        cells.append(
            f'<td bgcolor="#ffffff" width="{100 // 5}%" style="padding:7px 10px;">'
            f'<span style="color:{MUTED};font-size:8pt;">{label}</span><br>'
            f'<span style="color:{INK};font-size:11pt;">{esc(value)}</span></td>'
        )
    if not cells:
        return ""
    return (f'<table width="100%" cellspacing="1" cellpadding="0" bgcolor="{LINE}">'
            f'<tr>{"".join(cells)}</tr></table>'
            f'<p style="margin:0;font-size:10pt;"></p>')


def _section(title: str, body: str) -> str:
    return (f'<p style="margin:20px 0 6px;color:{MUTED};font-size:8pt;letter-spacing:1px;">'
            f'{title}</p>{body}')


def entry_html(entry: dict, index, backlinks: list[dict], occurrences: list[dict] | None = None) -> str:
    pron = entry.get("pronunciation") or {}
    homo = entry.get("homograph")

    # ---- 词目
    head = (
        f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td>'
        f'<span style="font-family:{SERIF};font-size:30pt;font-weight:bold;color:{INK};">'
        f'{esc(entry["headword"])}</span>'
        + (f'<span style="font-size:11pt;color:{MUTED};">&nbsp;{sup(homo)}</span>' if homo else "")
        + '</td><td align="right" valign="top">'
        f'<span style="color:{MUTED};font-size:8pt;letter-spacing:1px;">'
        f'{"中文" if entry.get("lang") == "zh" else "ENGLISH"}</span></td></tr></table>'
    )

    # ---- 读音行
    sub: list[str] = []
    if entry.get("lang") == "zh" and pron.get("pinyin"):
        sub.append(f'<span style="color:{INK};font-size:11.5pt;">{esc(pron["pinyin"])}</span>')
    for label, key in (("英", "uk"), ("美", "us")):
        if pron.get(key):
            sub.append(f'<span style="color:{MUTED};font-size:8pt;">{label}</span>'
                       f'<span style="color:{INK};font-size:10pt;">&nbsp;{esc(pron[key])}</span>')
    if entry.get("frequency"):
        sub.append(freq_html(entry["frequency"]))
    subline = (
        (f'<p style="margin:4px 0 0;font-size:10pt;">'
         + '<span style="color:#d0d0d0;">&nbsp;&nbsp;</span>'.join(sub) + '</p>')
        if sub else ""
    )

    top = head + subline + '<p style="margin:6px 0 0;"></p>' + rule("100%", "#cfcfcf")

    # ---- 词形
    forms = ""
    if entry.get("wordForms"):
        pieces = "&nbsp;&nbsp;".join(
            f'<span style="color:{MUTED};font-size:8pt;">{esc(f.get("label"))}</span>'
            f'<span style="color:{INK};font-size:9.5pt;">&nbsp;{esc(f.get("value"))}</span>'
            for f in entry["wordForms"]
        )
        forms = (f'<p style="margin:9px 0 0;font-size:9.5pt;">'
                 f'<span style="color:{MUTED};font-size:8pt;letter-spacing:1px;">词形</span>'
                 f'&nbsp;&nbsp;{pieces}</p>')

    senses = "".join(_sense(s, i, entry, index) for i, s in enumerate(entry.get("senses") or []))
    if not senses:
        senses = (
            f'<p style="margin:10px 0 4px;color:{GRAY};font-size:10pt;">这个词条还是空的（只有词条名）。</p>'
            f'<p style="margin:0;font-size:10pt;">'
            f'<a href="{attr(href_act("edit"))}" style="color:{INK};">补一条释义 →</a></p>'
        )

    phrases = ""
    if entry.get("phrases"):
        rows = "".join(
            f'<p style="margin:0 0 4px;font-size:10pt;">'
            f'{esc(p.get("phrase"))}'
            f'{("　" + esc(p.get("meaning"))) if p.get("meaning") else ""}</p>'
            for p in entry["phrases"]
        )
        phrases = _section("短语 / 习语", rows)

    etymology = ""
    if entry.get("etymology"):
        etymology = _section("词源", f'<p style="margin:0;font-size:9.5pt;color:{GRAY};">'
                                    f'{esc(entry["etymology"])}</p>')

    actions = (
        f'<p style="margin:26px 0 0;font-size:9.5pt;">'
        f'<a href="{attr(href_act("copy"))}" style="color:{GRAY};text-decoration:none;">复制 JSON</a>'
        f'<span style="color:#d6d6d6;">&nbsp;&nbsp;·&nbsp;&nbsp;</span>'
        f'<a href="{attr(href_act("edit"))}" style="color:{GRAY};text-decoration:none;">编辑</a>'
        f'<span style="color:#d6d6d6;">&nbsp;&nbsp;·&nbsp;&nbsp;</span>'
        f'<a href="{attr(href_act("new"))}" style="color:{GRAY};text-decoration:none;">新建词条</a>'
        f'<span style="color:#d6d6d6;">&nbsp;&nbsp;·&nbsp;&nbsp;</span>'
        f'<a href="{attr(href_act("del"))}" style="color:{MUTED};text-decoration:none;">删除词条</a>'
        f'</p>'
    )

    main = top + forms + _char_bar(entry) + '<p style="margin:0;font-size:6pt;"></p>' + senses + phrases + etymology + actions

    # ---- 侧栏（无边框，只有小标题 + 细线）
    side: list[str] = []
    side.append(rule("100%", HAIR))
    if entry.get("frequency"):
        side.append(_section("词频", f'<p style="margin:0;font-size:9pt;">{freq_html(entry["frequency"])}'
                                     f'<span style="color:{MUTED};">&nbsp;{entry["frequency"]}/5</span></p>'))
    if entry.get("wordForms"):
        side.append(_section("词形变化", "".join(
            f'<p style="margin:0 0 2px;font-size:9pt;">'
            f'<span style="color:{MUTED};">{esc(f.get("label"))}</span>&nbsp;'
            f'<span style="color:{INK};">{esc(f.get("value"))}</span></p>' for f in entry["wordForms"])))
    if entry.get("tags"):
        side.append(_section("分类", f'<p style="margin:0;font-size:9pt;color:{GRAY};">'
                                    f'{"、".join(esc(t) for t in entry["tags"])}</p>'))
    if backlinks:
        links = "、".join(
            f'<a href="{attr(href_entry(o["id"]))}" style="color:{INK};text-decoration:none;">{esc(o["headword"])}</a>'
            for o in backlinks[:10]
        )
        side.append(_section("被这些词条的例句用到", f'<p style="margin:0;font-size:9pt;">{links}</p>'))

    occs = occurrences or []
    if occs:
        rows = []
        for o in occs[:5]:
            rows.append(
                f'<p style="margin:0 0 6px;font-size:9.5pt;">{link_html(o["text"], entry, index)}'
                f'<span style="color:{MUTED};font-size:8pt;">&nbsp;&nbsp;{esc(o["headword"])}</span></p>'
            )
        side.append(_section("出现在这些例句", "".join(rows)))

    misses = index.ledger(entry)
    if misses:
        items = "、".join(
            f'<a href="{attr(href_new(w))}" style="color:{MUTED};text-decoration:none;">{esc(w)}</a>'
            for w in misses[:8]
        )
        more = f'<span style="color:{MUTED};font-size:8pt;">　还有 {len(misses) - 8} 个</span>' if len(misses) > 8 else ""
        side.append(_section("例句里还没收录的词", f'<p style="margin:0;font-size:9pt;">{items}{more}</p>'))

    aside = '<table width="100%" cellspacing="0" cellpadding="0"><tr><td>' + "".join(side) + '</td></tr></table>'

    return (
        '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
        f'<td width="71%" valign="top" style="padding-right:26px;">{main}</td>'
        f'<td width="29%" valign="top">{aside}</td>'
        '</tr></table>'
    )


def welcome_html(total: int, senses: int, edges: int) -> str:
    if total == 0:
        return (
            f'<p style="font-size:21pt;font-family:{SERIF};color:{INK};margin:34px 0 8px;">'
            f'词库还是空的</p>'
            f'<p style="color:{GRAY};font-size:10.5pt;margin:0 0 6px;line-height:1.7;">'
            f'用「文件 → 导入 CSV / JSON」把词放进来，或点右上角「示例」先看版式。</p>'
            + rule("60%") +
            f'<p style="color:{GRAY};font-size:10pt;margin:16px 0 0;line-height:1.8;">'
            f'联想是这么走的：点进一个词 → 读它的例句 → 例句里的词可以继续点 → 换到那个词 → 再读它的例句。<br>'
            f'已收录的词是黑色下划线；没收录的英文词是灰色，点一下就新建。</p>'
        )
    return (
        f'<p style="font-size:18pt;font-family:{SERIF};color:{INK};margin:30px 0 8px;">'
        f'选一个词条开始</p>'
        + rule("60%") +
        f'<p style="color:{GRAY};font-size:10pt;margin:16px 0 0;line-height:1.8;">'
        f'当前 {total} 条词条 · {senses} 个义项 · {edges} 条例句内联想边。<br>'
        f'左侧点选，或在例句里点带下划线的词继续联想。</p>'
    )
