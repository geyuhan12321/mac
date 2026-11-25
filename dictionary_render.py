"""渲染层：把词条拼成 Qt 富文本（QTextBrowser 能吃的那部分 HTML）。

黑白灰排版，参照柯林斯词典的词条页：一套字号层级 + 细线 + 留白，
不用填充色块、不用彩色标签。Qt 富文本只认 CSS 2.1 子集，所以结构一律用 table 搭。
"""
from __future__ import annotations

import os
from html import escape
from pathlib import Path
from urllib.parse import quote

# 图片根目录，由 app.py 启动时设置（data/images）
IMAGE_ROOT = ""
IMAGE_ROOTS: list[str] = []
IMAGE_WIDTH = 520          # 页面里图片显示宽度（px），0 = 按原图
EMBED_SCHEME = "dictimg"   # 正文图片用自定义 scheme，由程序喂像素

INK = "#111111"       # 正文/词目
GRAY = "#5f5f5f"      # 次级说明
MUTED = "#9a9a9a"     # 标签、注释
LINE = "#e6e6e6"      # 细线
HAIR = "#efefef"
SOFT = "#f7f7f7"

# ---------------------------------------------------------------- 字号系统
# 每个槽位的默认磅值；运行时用 set_font_delta() 整体增减，所有位置同步变化。
BASE_SIZES = {
    "hw":      30.0,   # 词目大字
    "h2":      21.0,   # 欢迎页主标题
    "h3":      18.0,   # 欢迎页次标题
    "def":     11.5,   # 释义正文
    "ex":      10.5,   # 例句
    "zh":      10.0,   # 译文 / 次级正文
    "val":     11.0,   # 汉字信息条的值（足 / 12 / 車）
    "label":    8.0,   # 各类小标签
    "note":     9.0,   # 次要说明
    "side":     9.0,   # 侧栏正文
    "sub":      9.5,   # 词形 / 短语 / 操作行
    "meta":     9.0,   # 同义词 / 搭配 / 标注
    "num":     10.0,   # 义项编号
    "pron":    10.0,   # 英音 / 美音
    "pinyin":  11.5,   # 拼音
    "list":    10.5,   # 左侧列表：词目
    "list_sub": 8.5,   # 左侧列表：音标
    "ui":      10.0,   # 界面外壳基础
    "ui_small": 8.5,   # 状态栏 / 计数
    "rule":     6.0,   # 占位空行，不参与缩放
}

FIXED_SLOTS = {"rule"}   # 不随增量变化、也不受下限约束
MIN_PT = 6.0             # 任何槽位缩放后的最小值

_delta = 0.0             # 当前增量（pt），全模块共享


def set_font_delta(delta: float) -> None:
    """设置全局字号增量：正数放大，负数缩小。"""
    global _delta
    _delta = float(delta)


def get_font_delta() -> float:
    return _delta


def pt(slot: str) -> float:
    """返回槽位的数值磅值（给 Qt 控件用）。"""
    base = BASE_SIZES.get(slot, BASE_SIZES["zh"])
    if slot in FIXED_SLOTS:
        return base
    size = base + _delta
    if size < MIN_PT:
        size = MIN_PT
    return round(size * 2) / 2


def fs(slot: str) -> str:
    """返回槽位的字号字符串，如 '13.5pt'。"""
    return f"{pt(slot):g}pt"


SERIF = "Georgia,'Times New Roman',SimSun,serif"
SANS = "'Microsoft YaHei UI','Microsoft YaHei',Segoe UI,sans-serif"


def set_image_root(path) -> None:
    """兼容旧调用：设置单一图片目录。"""
    set_image_roots([path])


def set_image_width(px: int) -> None:
    """设置图片显示宽度；0 表示按图片原始尺寸。"""
    global IMAGE_WIDTH
    IMAGE_WIDTH = max(0, int(px))


def get_image_width() -> int:
    return IMAGE_WIDTH


def _img_tag(url: str) -> str:
    """按当前设置生成 img 标签。"""
    w = IMAGE_WIDTH
    if w > 0:
        return f'<img src="{attr(url)}" width="{w}">'
    return f'<img src="{attr(url)}">'


def set_image_roots(paths) -> None:
    """图片可能分放多处（用户目录 + 只读资源），按顺序查找。"""
    global IMAGE_ROOT, IMAGE_ROOTS
    IMAGE_ROOTS = [str(x) for x in paths if x]
    IMAGE_ROOT = IMAGE_ROOTS[0] if IMAGE_ROOTS else ""


def image_url(filename: str) -> str:
    """相对文件名 → file:// 地址；依次在各搜索目录里找。"""
    f = str(filename or "").strip()
    if not f:
        return ""
    if os.path.isabs(f):
        return Path(f).as_uri() if os.path.exists(f) else ""
    for root in (IMAGE_ROOTS or [""]):
        cand = os.path.join(root, f) if root else f
        if os.path.exists(cand):
            try:
                return Path(cand).as_uri()
            except ValueError:
                return ""
    return ""


def image_path(filename: str):
    """在搜索目录里找这张图，返回 Path 或 None。"""
    f = str(filename or "").strip()
    if not f:
        return None
    if os.path.isabs(f):
        return Path(f) if os.path.exists(f) else None
    for root in (IMAGE_ROOTS or [""]):
        cand = os.path.join(root, f) if root else f
        if os.path.exists(cand):
            return Path(cand)
    return None


def image_src(filename: str) -> str:
    """正文里用的图片地址：自定义 scheme，配合 addResource 提供像素。"""
    if image_path(filename) is None:
        return ""
    from urllib.parse import quote
    return f"{EMBED_SCHEME}://{quote(str(filename))}"


def nl(html_text: str) -> str:
    """换行 → <br>，行首缩进 → &nbsp;，让输入的内容原样显示。"""
    text = html_text.replace("\r\n", "\n").replace("\t", "    ").replace("\u3000", "  ")
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        lead = len(line) - len(stripped)
        out.append("&nbsp;" * lead + stripped if lead else stripped)
    return "<br>".join(out)


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
    size = fs("label") if small else fs("note")
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
    """近义 / 搭配 / 标注：每项占一行，原样显示。"""
    items = (sense.get("synonyms") or []) + (sense.get("collocations") or []) \
        + (sense.get("labels") or [])
    items = [i for i in items if str(i).strip()]
    if not items:
        return ""
    body = "<br>".join(nl(esc(i)) for i in items)
    return (f'<p style="margin:9px 0 0;font-size:{fs('meta')};color:{GRAY};'
            f'line-height:1.6;">{body}</p>')


def _sense(sense: dict, idx: int, entry: dict, index) -> str:
    bits: list[str] = []
    if sense.get("pos"):
        bits.append(
            f'<p style="margin:0 0 3px;color:{MUTED};font-size:{fs('label')};letter-spacing:1px;">'
            f'{esc(sense["pos"]).upper()}</p>'
        )
    if sense.get("definition"):
        body = nl(link_html(sense["definition"], entry, index))
        bits.append(f'<p style="margin:0 0 4px;color:{INK};font-size:{fs('def')};line-height:1.75;">'
                    f'{body}</p>')
    # 译文按要求不再显示

    for ex in sense.get("examples") or []:
        inner = f'<span style="font-size:{fs('ex')};color:#333333;">{nl(link_html(ex.get("text", ""), entry, index))}</span>'

        if ex.get("source"):
            inner += (f'<p style="margin:2px 0 0;color:#b3b3b3;font-size:{fs('label')};">'
                      f'{nl(esc(ex["source"]))}</p>')
        bits.append(
            f'<table width="100%" cellspacing="0" cellpadding="5"><tr>'
            f'<td style="border-left:2px solid #e0e0e0;">{inner}</td></tr></table>'
        )
    if sense.get("note"):
        bits.append(f'<p style="margin:5px 0 0;color:{MUTED};font-size:{fs('note')};">'
                    f'用法 {nl(esc(sense["note"]))}</p>')
    bits.append(_meta(sense))
    for im in sense.get("images") or []:
        url = image_src(im.get("file", ""))
        if not url:
            continue
        cap = im.get("caption") or ""
        bits.append(
            f'<p style="margin:6px 0 10px;">{_img_tag(url)}'
            + (f'<br><span style="color:{MUTED};font-size:{fs("label")};">{esc(cap)}</span>' if cap else "")
            + "</p>"
        )

    body = "".join(bits)
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
        f'<td width="26" valign="top" align="right">'
        f'<span style="color:{MUTED};font-size:{fs('num')};font-family:{SERIF};">{idx + 1}</span>'
        f'</td><td width="10"></td>'
        f'<td valign="top">{body}</td></tr></table>'
        f'<p style="margin:0;font-size:{fs('rule')};"></p>'
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
            f'<span style="color:{MUTED};font-size:{fs('label')};">{label}</span><br>'
            f'<span style="color:{INK};font-size:{fs('val')};">{esc(value)}</span></td>'
        )
    if not cells:
        return ""
    return (f'<table width="100%" cellspacing="1" cellpadding="0" bgcolor="{LINE}">'
            f'<tr>{"".join(cells)}</tr></table>'
            f'<p style="margin:0;font-size:{fs('rule')};"></p>')


def _section(title: str, body: str) -> str:
    return (f'<p style="margin:20px 0 6px;color:{MUTED};font-size:{fs('label')};letter-spacing:1px;">'
            f'{title}</p>{body}')


def _head_image(entry: dict, hw_pt: float) -> str:
    """第一张图（甲骨文）跟在字右边，高度约等于字高。"""
    imgs = entry.get("images") or []
    if not imgs:
        return ""
    url = image_src(imgs[0].get("file", ""))
    if not url:
        return ""
    px = max(28, int(hw_pt * 1.333 * 1.15))     # pt → px，再略放大一点
    return (f'&nbsp;&nbsp;<img src="{attr(url)}" height="{px}" '
            f'style="vertical-align:middle;">')


def _main_image(entry: dict) -> str:
    """词条处显示的第一张图（甲骨文/字源）。"""
    imgs = entry.get("images") or []
    if not imgs:
        return ""
    url = image_src(imgs[0].get("file", ""))
    if not url:
        return ""
    cap = imgs[0].get("caption") or ""
    wide = IMAGE_WIDTH if IMAGE_WIDTH else 0
    style = f"width:{wide}px;" if wide else ""
    return (f'<p style="margin:8px 0 2px;text-align:center;">'
            f'<img src="{attr(url)}" style="{style} max-width:100%;">'
            + (f'<br><span style="color:{MUTED};font-size:{fs("label")};">{esc(cap)}</span>' if cap else "")
            + "</p>")


def _image_row(entry: dict) -> str:
    """其余图片并排一行，宽度统一压到 120px。"""
    imgs = (entry.get("images") or [])[1:]
    if not imgs:
        return ""
    cells = []
    for im in imgs:
        url = image_src(im.get("file", ""))
        if not url:
            continue
        cells.append(
            f'<td align="center" style="padding:0 6px 0 0;">'
            f'<img src="{attr(url)}" width="120"></td>'
        )
    if not cells:
        return ""
    return (f'<table cellspacing="0" cellpadding="0" style="margin:6px 0 2px;"><tr>'
            f'{"".join(cells)}</tr></table>')


def _images_block(entry: dict) -> str:
    imgs = entry.get("images") or []
    if not imgs:
        return ""
    rows = []
    for im in imgs:
        url = image_src(im.get("file", ""))
        if not url:
            continue
        cap = im.get("caption") or ""
        line = f'<p style="margin:0 0 10px;">{_img_tag(url)}'
        if cap:
            line += f'<br><span style="color:{MUTED};font-size:{fs("label")};">{esc(cap)}</span>'
        rows.append(line + "</p>")
    if not rows:
        return ""
    # 紧跟在汉字信息条下面，标题上边距小一点
    head = (f'<p style="margin:10px 0 4px;color:{MUTED};font-size:{fs("label")};'
            f'letter-spacing:1px;">图片</p>')
    return head + "".join(rows)


def entry_html(entry: dict, index, backlinks: list[dict], occurrences: list[dict] | None = None,
               relations: dict | None = None) -> str:
    pron = entry.get("pronunciation") or {}
    homo = entry.get("homograph")

    # ---- 词目（标题过长时自动缩小，避免撑出版面）
    hw_pt = pt("hw")
    hw_len = len(entry["headword"])
    if hw_len <= 3:
        hw_size = fs("hw")
    elif hw_len <= 6:
        hw_size = f"{round(pt('hw') * 0.55 * 2) / 2:g}pt"
    elif hw_len <= 12:
        hw_size = f"{round(pt('hw') * 0.36 * 2) / 2:g}pt"
    else:
        hw_size = f"{max(12.0, round(pt('hw') * 0.26 * 2) / 2):g}pt"

    head = (
        f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td>'
        f'<span style="font-family:{SERIF};font-size:{hw_size};font-weight:bold;color:{INK};">'
        f'{esc(entry["headword"])}</span>'
        + (f'<span style="font-size:{fs('val')};color:{MUTED};">&nbsp;{sup(homo)}</span>' if homo else "")
        + _head_image(entry, hw_pt)
        + '</td><td align="right" valign="top">'
        f'<span style="color:{MUTED};font-size:{fs('label')};letter-spacing:1px;">'
        f'{"中文" if entry.get("lang") == "zh" else "ENGLISH"}</span></td></tr></table>'
    )

    # ---- 读音行
    sub: list[str] = []
    if entry.get("lang") == "zh" and pron.get("pinyin"):
        sub.append(f'<span style="color:{INK};font-size:{fs('pinyin')};">{esc(pron["pinyin"])}</span>')
    for label, key in (("英", "uk"), ("美", "us")):
        if pron.get(key):
            sub.append(f'<span style="color:{MUTED};font-size:{fs('label')};">{label}</span>'
                       f'<span style="color:{INK};font-size:{fs('pron')};">&nbsp;{esc(pron[key])}</span>')
    if entry.get("frequency"):
        sub.append(freq_html(entry["frequency"]))
    subline = (
        (f'<p style="margin:4px 0 0;font-size:{fs('pron')};">'
         + '<span style="color:#d0d0d0;">&nbsp;&nbsp;</span>'.join(sub) + '</p>')
        if sub else ""
    )

    top = (head + subline + _image_row(entry)
           + '<p style="margin:6px 0 0;"></p>' + rule("100%", "#cfcfcf"))

    # 词形变化按要求不再显示（数据保留在 JSON 里）

    senses = "".join(_sense(s, i, entry, index) for i, s in enumerate(entry.get("senses") or []))
    if not senses:
        senses = (
            f'<p style="margin:10px 0 4px;color:{GRAY};font-size:{fs('zh')};">这个词条还是空的（只有词条名）。</p>'
            f'<p style="margin:0;font-size:{fs('zh')};">'
            f'<a href="{attr(href_act("edit"))}" style="color:{INK};">补一条释义 →</a></p>'
        )

    phrases = ""
    if entry.get("phrases"):
        rows = "".join(
            f'<p style="margin:0 0 4px;font-size:{fs('zh')};">'
            f'{esc(p.get("phrase"))}'
            f'{("　" + nl(esc(p.get("meaning")))) if p.get("meaning") else ""}</p>'
            for p in entry["phrases"]
        )
        phrases = _section("短语 / 习语", rows)

    etymology = ""
    if entry.get("etymology"):
        etymology = _section("词源", f'<p style="margin:0;font-size:{fs('sub')};color:{GRAY};">'
                                    f'{nl(esc(entry["etymology"]))}</p>')

    actions = (
        f'<p style="margin:26px 0 0;font-size:{fs('sub')};">'
        f'<a href="{attr(href_act("copy"))}" style="color:{GRAY};text-decoration:none;">复制 JSON</a>'
        f'<span style="color:#d6d6d6;">&nbsp;&nbsp;·&nbsp;&nbsp;</span>'
        f'<a href="{attr(href_act("edit"))}" style="color:{GRAY};text-decoration:none;">编辑</a>'
        f'<span style="color:#d6d6d6;">&nbsp;&nbsp;·&nbsp;&nbsp;</span>'
        f'<a href="{attr(href_act("new"))}" style="color:{GRAY};text-decoration:none;">新建词条</a>'
        f'<span style="color:#d6d6d6;">&nbsp;&nbsp;·&nbsp;&nbsp;</span>'
        f'<a href="{attr(href_act("del"))}" style="color:{MUTED};text-decoration:none;">删除词条</a>'
        f'</p>'
    )

    # 部首笔画、译文、词形都不再显示；图片已在顶部
    main = (top + senses + phrases + etymology + actions)

    # ---- 侧栏：按部首与发音给出的关联字
    rel = relations or {}
    side: list[str] = []
    side.append(rule("100%", HAIR))

    def rel_links(items: list[dict], limit: int = 24) -> str:
        return "　".join(
            f'<a href="{attr(href_entry(o["id"]))}" style="color:{INK};text-decoration:none;">'
            f'{esc(o["headword"])}</a>'
            for o in items[:limit]
        )

    for title, key in (("同音", "homophones"), ("近音", "near"),
                       ("同部首", "same_radical"), ("同源字", "contains")):
        items = rel.get(key) or []
        if not items:
            continue
        more = (f'<span style="color:{MUTED};font-size:{fs("label")};">　…共 {len(items)} 个</span>'
                if len(items) > 24 else "")
        side.append(_section(title,
                             f'<p style="margin:0;font-size:{fs("side")};line-height:1.9;">'
                             f'{rel_links(items)}{more}</p>'))

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
            f'<p style="font-size:{fs('h2')};font-family:{SERIF};color:{INK};margin:34px 0 8px;">'
            f'词库还是空的</p>'
            f'<p style="color:{GRAY};font-size:{fs('ex')};margin:0 0 6px;line-height:1.7;">'
            f'用「文件 → 导入」把词放进来，或点「新建」写第一条。</p>'
            + rule("60%") +
            f'<p style="color:{GRAY};font-size:{fs('zh')};margin:16px 0 0;line-height:1.8;">'

            f'</p>'
        )
    return (
        f'<p style="font-size:{fs('h3')};font-family:{SERIF};color:{INK};margin:30px 0 8px;">'
        f'选一个词条开始</p>'
        + rule("60%") +
        f'<p style="color:{GRAY};font-size:{fs('zh')};margin:16px 0 0;line-height:1.8;">'
        f'</p>'

    )
