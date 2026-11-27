

from __future__ import annotations

import json
import re
import os
import pathlib
import shutil
import sys
import uuid
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import Qt, QSize, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetrics, QIcon, QImage, QKeySequence,
                           QPixmap, QShortcut, QDesktopServices)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QInputDialog, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QSplitter, QStyledItemDelegate, QStyle, QTextBrowser,
    QToolButton, QVBoxLayout, QWidget,
)

import dictionary_model as dm
import dictionary_render as rw

APP_DIR = Path(__file__).resolve().parent


_TONE_MAP = str.maketrans(
    "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜńňḿ",
    "aaaaeeeeiiiioooouuuuüüüünnm",
)


def _strip_tone(text: str) -> str:
    """去掉拼音声调，便于「ai」搜「ài」。"""
    return (text or "").translate(_TONE_MAP).lower()


_TONE_MAP_ALL = {
    "ā": ("a", 1), "á": ("a", 2), "ǎ": ("a", 3), "à": ("a", 4),
    "ē": ("e", 1), "é": ("e", 2), "ě": ("e", 3), "è": ("e", 4),
    "ī": ("i", 1), "í": ("i", 2), "ǐ": ("i", 3), "ì": ("i", 4),
    "ō": ("o", 1), "ó": ("o", 2), "ǒ": ("o", 3), "ò": ("o", 4),
    "ū": ("u", 1), "ú": ("u", 2), "ǔ": ("u", 3), "ù": ("u", 4),
    "ǖ": ("v", 1), "ǘ": ("v", 2), "ǚ": ("v", 3), "ǜ": ("v", 4),
    "ü": ("v", 0), "ń": ("n", 2), "ň": ("n", 3), "ḿ": ("m", 2),
}


def pinyin_keys(entry: dict) -> set[tuple[str, int]]:
    """把 "ā / á" 拆成 {("a",1),("a",2)}。"""
    raw = (entry.get("pronunciation") or {}).get("pinyin", "") or ""
    out: set[tuple[str, int]] = set()
    for piece in raw.replace(",", " ").replace("/", " ").split():
        base, tone = [], 0
        for ch in piece.strip():
            if ch in _TONE_MAP_ALL:
                b, t = _TONE_MAP_ALL[ch]
                base.append(b)
                tone = t
            elif ch.isalpha():
                base.append(ch.lower())
        if base:
            out.add(("".join(base), tone))
    return out


def sound_relatives(entry: dict, entries: list[dict]) -> list[str]:
    """同音 + 近音合并：同音节同调算同音，同音节不同调算近音。"""
    keys = pinyin_keys(entry)
    if not keys:
        return []
    bases = {k[0] for k in keys}
    exact, near = [], []
    for e in entries:
        if e.get("id") == entry.get("id"):
            continue
        ek = pinyin_keys(e)
        if not ek:
            continue
        if ek & keys:
            exact.append(e["headword"])
        elif {k[0] for k in ek} & bases:
            near.append(e["headword"])
    seen, merged = set(), []
    for ch in exact + near:
        if ch not in seen:
            seen.add(ch)
            merged.append(ch)
    return merged


def radical_relatives(entry: dict, entries: list[dict]) -> list[str]:
    """同形：偏旁部首相同的字。"""
    rad = (entry.get("character") or {}).get("radical") or ""
    if not rad:
        # 新词条还没存部首，借词库里同名字的
        same = next((e for e in entries if e["headword"] == entry.get("headword")), None)
        rad = ((same or {}).get("character") or {}).get("radical") or ""
    if not rad:
        return []
    out, seen = [], set()
    for e in entries:
        if e.get("id") == entry.get("id"):
            continue
        if ((e.get("character") or {}).get("radical") or "") != rad:
            continue
        ch = e["headword"]
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


def dm_factor(delta: float) -> float:
    """把增量夹到 -4 ~ +10 之间，并按 0.5 对齐。"""
    d = max(-4.0, min(10.0, float(delta)))
    return round(d * 2) / 2


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bundle_data_dir() -> Path | None:
    """打包进程序的只读数据目录（词库 + 图片）。"""
    cands: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        mp = Path(meipass)
        cands += [mp / "data", mp.parent / "Resources" / "data", mp.parent / "data"]
    exe = Path(sys.executable).resolve()
    # macOS .app: Contents/MacOS/Dict → Contents/Resources/data
    cands += [
        exe.parent.parent / "Resources" / "data",
        exe.parent / "data",
        exe.parent.parent / "data",
    ]
    cands.append(APP_DIR / "data")
    for c in cands:
        if (c / "words.json").exists():
            return c
    return None


def _writable(path: Path) -> bool:
    """真去写一个探针文件，确认目录可用。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".writable"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError as exc:
        DIR_ERRORS.append(f"{type(exc).__name__}: {exc}")
        return False


def _app_tag() -> str:
    """应用标识：空白版与正式版各用各的数据目录，互不干扰。"""
    exe = Path(sys.executable).name
    if "DictBlank" in exe:
        return "DictBlank"
    if "Dict" in exe:
        return "Dict"
    return "Dict"


def _user_data_dir() -> Path:
    """可写的用户数据目录，按顺序尝试几个常见位置。"""
    tag = _app_tag()
    cands: list[Path] = []
    if sys.platform == "darwin":
        cands.append(Path.home() / "Library" / "Application Support" / tag / "data")
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        local = os.environ.get("LOCALAPPDATA")
        if appdata:
            cands.append(Path(appdata) / tag / "data")
        if local:
            cands.append(Path(local) / tag / "data")
    cands.append(Path.home() / tag / "data")
    cands.append(Path.home() / f".{tag.lower()}" / "data")

    for c in cands:
        good = _writable(c)
        DIR_ATTEMPTS.append(f"{'ok ' if good else 'no '} {c}")
        if good:
            return c
    return cands[-1]


COPY_ERROR = ""
DIR_ATTEMPTS: list[str] = []
DIR_ERRORS: list[str] = []
BUNDLE_DATA = _bundle_data_dir()

# 数据目录优先级：环境变量 > 源码旁边 > 用户目录
_env_dir = os.environ.get("DICT_DATA_DIR", "").strip()
if _env_dir:
    DATA_DIR = Path(_env_dir).expanduser()
elif not _is_frozen() and (APP_DIR / "data" / "words.json").exists():
    DATA_DIR = APP_DIR / "data"
else:
    DATA_DIR = _user_data_dir()

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
WORDS_PATH = DATA_DIR / "words.json"

# 首次运行：把随包词库复制到用户目录，之后改的是这一份
if not WORDS_PATH.exists() and BUNDLE_DATA and (BUNDLE_DATA / "words.json").exists():
    try:
        shutil.copy2(BUNDLE_DATA / "words.json", WORDS_PATH)
    except OSError as exc:
        COPY_ERROR = f"{type(exc).__name__}: {exc}"
        WORDS_PATH = BUNDLE_DATA / "words.json"

IMAGES_DIR = DATA_DIR / "images"
try:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

def _bundle_images_readable(folder: Path) -> bool:
    """用 Qt 真读一张，确认包内图片能解码（macOS 上偶尔读不到）。"""
    try:
        from PySide6.QtGui import QImage
    except Exception:
        return False
    for f in sorted(folder.glob("*.jpg"))[:1]:
        img = QImage(str(f))
        if not img.isNull():
            return True
    return False


def _copy_bundle_images(folder: Path) -> int:
    """把随包图片复制到用户目录，返回复制数量。"""
    n = 0
    for f in folder.glob("*.jpg"):
        target = IMAGES_DIR / f.name
        if target.exists():
            continue
        try:
            shutil.copy2(f, target)
            n += 1
        except OSError:
            pass
    return n


# 图片：先找用户目录（新粘贴的），再找随包资源；
# 包里那张读不出来时，把图片搬到用户目录，保证能显示
_IMAGE_ROOTS: list[Path] = [IMAGES_DIR]  # 去重后使用
IMG_SOURCE = "用户目录"
if BUNDLE_DATA and (BUNDLE_DATA / "images").is_dir():
    _bundle = BUNDLE_DATA / "images"
    if _bundle_images_readable(_bundle):
        if _bundle.resolve() != IMAGES_DIR.resolve():
            _IMAGE_ROOTS.append(_bundle)
        IMG_SOURCE = "随包资源"
    else:
        _copied = _copy_bundle_images(_bundle)
        IMG_SOURCE = f"已从包内复制 {_copied} 张到用户目录"
rw.set_image_roots(_IMAGE_ROOTS)


def verify_images() -> None:
    """确认能读到图片；包内文件读不了就复制到用户目录。"""
    global IMG_SOURCE
    if not _IMAGE_ROOTS:
        return
    sample = None
    for root in _IMAGE_ROOTS:
        for f in sorted(Path(root).glob("*.jpg"))[:1]:
            sample = f
            break
        if sample:
            break
    if sample is None:
        IMG_SOURCE = "没有找到任何图片"
        return

    from PySide6.QtGui import QImage

    if not QImage(str(sample)).isNull():
        return                       # 能读，保持原样

    if BUNDLE_DATA and (BUNDLE_DATA / "images").is_dir():
        n = _copy_bundle_images(BUNDLE_DATA / "images")
        rw.set_image_roots([IMAGES_DIR])
        IMG_SOURCE = f"包内图读不了，已复制 {n} 张到用户目录"


def build_qss() -> str:
    """按当前字号增量生成样式表：外壳所有文字与正文同步缩放。"""
    ui = max(9.0, min(30.0, 13.0 + rw.get_font_delta() * 1.333))     # 1pt ≈ 1.333px
    small = max(8.0, min(26.0, 11.0 + rw.get_font_delta() * 1.333))
    # 编辑器用到的正文级字号，直接取自同一套槽位
    hw = rw.pt('hw')
    sub = rw.pt('sub')
    zh = rw.pt('zh')
    label = rw.pt('label')
    num = rw.pt('num')
    ui_small = rw.pt('ui_small')
    return f"""
QWidget {{ background: #ffffff; color: #111111; font-size: {ui:.1f}px; }}
#Header {{ background: #ffffff; border-bottom: 1px solid #e6e6e6; }}
#Count {{ background: transparent; }}
QLineEdit#Search {{
    background: #ffffff; border: 1px solid #dcdcdc; border-radius: 4px;
    padding: 6px 10px; color: #111111;
    selection-background-color: #111111; selection-color: #ffffff;
}}
QLineEdit#Search:focus {{ border-color: #111111; }}
QPushButton#Top {{ background: transparent; border: none; color: #5f5f5f; padding: 6px 10px; }}
QPushButton#Top:hover {{ color: #111111; background: #f4f4f4; border-radius: 4px; }}
QPushButton#Nav {{
    background: transparent; border: none; color: #444444;
    font-size: {ui:.1f}px; padding: 0;
}}
QPushButton#Nav:hover {{ color: #111111; background: #f4f4f4; border-radius: 6px; }}
QPushButton#Nav:disabled {{ color: #d8d8d8; }}
QListWidget#WordList {{ border: none; background: #ffffff; outline: none; }}
QListWidget#WordList::item {{ border: none; }}
QTextBrowser#EntryView {{ border: none; background: #ffffff; }}
QSplitter::handle {{ background: #ffffff; }}
QSplitter::handle:horizontal {{ width: 1px; background: #e6e6e6; }}
QComboBox {{ border: none; background: #ffffff; color: #5f5f5f; padding: 3px 4px; }}
QComboBox:hover {{ color: #111111; }}
QComboBox::drop-down {{ border: none; width: 14px; }}
QComboBox QAbstractItemView {{
    border: 1px solid #e6e6e6; background: #ffffff;
    selection-background-color: #f2f2f2; selection-color: #111111;
}}
QLabel#Count {{ color: #9a9a9a; font-size: {small:.1f}px; }}
QStatusBar {{ color: #9a9a9a; font-size: {small:.1f}px; border-top: 1px solid #eeeeee; }}
QMenuBar {{ background: #ffffff; border-bottom: 1px solid #eeeeee; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; color: #333333; }}
QMenuBar::item:selected {{ background: #f4f4f4; }}

/* ---------------- 编辑器：与词条页同版式 ---------------- */
QScrollArea#EditorScroll {{ border: none; background: #ffffff; }}
QWidget#EditorPage {{ background: #ffffff; }}

QLineEdit#Headline {{
    border: none; border-bottom: 1px dashed #dcdcdc; background: transparent;
    font-family: Georgia, 'Times New Roman', SimSun, serif;
    font-size: {hw:.0f}pt; font-weight: bold; color: #111111; padding: 2px 0 4px 0;
}}
QLineEdit#Headline:focus {{ border-bottom: 1px solid #111111; }}

QLineEdit#Subline {{
    border: none; border-bottom: 1px dashed #e4e4e4; background: transparent;
    font-size: {sub:.0f}pt; color: #111111; padding: 3px 0;
}}
QLineEdit#Subline:focus {{ border-bottom: 1px solid #999999; }}

QLineEdit#EditorField, QLineEdit#CharField, QLineEdit#SenseTag {{
    border: none; border-bottom: 1px dashed #e4e4e4; background: transparent;
    font-size: {zh:.0f}pt; color: #333333; padding: 3px 0;
}}
QLineEdit#EditorField:focus, QLineEdit#CharField:focus, QLineEdit#SenseTag:focus {{
    border-bottom: 1px solid #999999;
}}
QLineEdit#SenseTag {{ color: #9a9a9a; font-size: {label:.0f}pt; letter-spacing: 1px; }}

QPlainTextEdit#EditorArea {{
    border: 1px solid #ececec; border-radius: 4px; background: #fdfdfd;
    font-size: {zh:.0f}pt; color: #333333; padding: 4px 6px;
}}
QPlainTextEdit#EditorArea:focus {{ border-color: #bbbbbb; background: #ffffff; }}

QLabel#EditorSection {{
    color: #9a9a9a; font-size: {label:.0f}pt; letter-spacing: 1px;
    margin-top: 12px; background: transparent;
}}
QLabel#EditorHint {{ color: #b0b0b0; font-size: {ui_small:.0f}pt; background: transparent; }}
QLabel#FreqDots {{ color: #111111; font-size: {ui:.0f}pt; letter-spacing: 2px; background: transparent; }}
QWidget#CharBar {{ background: transparent; }}
QWidget#CharCell {{ background: #ffffff; border: 1px solid #e6e6e6; }}
QPlainTextEdit#EditorArea QScrollBar:vertical {{
    width: 7px; background: transparent; margin: 0;
}}
QPlainTextEdit#EditorArea QScrollBar::add-line:vertical,
QPlainTextEdit#EditorArea QScrollBar::sub-line:vertical {{
    height: 0; background: transparent; border: none;
}}
QPlainTextEdit#EditorArea QScrollBar::add-page:vertical,
QPlainTextEdit#EditorArea QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QPlainTextEdit#EditorArea QScrollBar::handle:vertical {{
    background: #d8d8d8; min-height: 18px; border-radius: 3px;
}}
QPlainTextEdit#EditorArea QScrollBar::handle:vertical:hover {{
    background: #bdbdbd;
}}
QLabel#DupHint {{
    color: #8a8a8a; font-size: 8pt; letter-spacing: 1px;
    padding-left: 2px;
}}
QLabel#EditorCap {{
    color: #9a9a9a; font-size: {ui_small:.0f}pt; letter-spacing: 1px;
    background: transparent; padding-top: 4px;
}}
QLabel#SenseNum {{
    color: #9a9a9a; font-family: Georgia, serif; font-size: {num:.0f}pt; background: transparent;
}}
QFrame#EditorRule {{ border: none; border-top: 1px solid #111111; max-height: 1px; }}

QPushButton#EditorGhost {{
    border: 1px solid #e6e6e6; border-radius: 4px; background: #ffffff;
    color: #5f5f5f; padding: 5px 12px; font-size: {ui:.0f}px;
}}
QPushButton#EditorGhost:hover {{ color: #111111; border-color: #cfcfcf; }}
QPushButton#EditorPrimary {{
    border: none; border-radius: 4px; background: #111111;
    color: #ffffff; padding: 6px 18px; font-size: {ui:.0f}px;
}}
QPushButton#EditorPrimary:hover {{ background: #333333; }}
QPushButton#SenseRemove {{
    border: none; background: transparent; color: #b0b0b0; font-size: {ui_small:.0f}pt;
}}
QPushButton#SenseRemove:hover {{ color: #b3261e; }}
QPushButton#Thumb {{ border: 1px solid #e6e6e6; border-radius: 4px; background: #ffffff; }}
QPushButton#Thumb:hover {{ border-color: #b3261e; }}
QSpinBox#FreqEdit {{ border: 1px solid #e6e6e6; border-radius: 4px; padding: 3px; }}
QWidget#EditorBar {{ background: #ffffff; border-top: 1px solid #eeeeee; }}
"""


QSS = build_qss()   # 默认字号下的快照，供外部引用


class WordDelegate(QStyledItemDelegate):
    """列表项：半粗词目 + 灰色读音；选中/悬停只有浅灰底，不描边。"""

    def sizeHint(self, option, index):
        return QSize(180, int(18 + rw.pt("list") * 1.7))

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QColor("#f2f2f2"))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor("#fafafa"))

        head = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        pron = index.data(Qt.ItemDataRole.UserRole + 2) or ""

        f1 = QFont(option.font)
        f1.setPointSizeF(rw.pt("list"))
        f1.setWeight(QFont.Weight.DemiBold)
        painter.setFont(f1)
        painter.setPen(QColor("#111111"))
        painter.drawText(rect.adjusted(14, 0, -8, 0),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), head)

        if pron:
            width = QFontMetrics(f1).horizontalAdvance(head)
            f2 = QFont(option.font)
            f2.setPointSizeF(rw.pt("list_sub"))
            painter.setFont(f2)
            painter.setPen(QColor("#9a9a9a"))
            painter.drawText(rect.adjusted(14 + width + 10, 0, -8, 0),
                             int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), pron)
        painter.restore()


class EntryView(QTextBrowser):
    """词条正文：链接可点、悬停变手型。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EntryView")
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.document().setDocumentMargin(10)
        self.setFont(QFont("Microsoft YaHei UI", 10))

    def mouseMoveEvent(self, event):
        href = self.anchorAt(event.position().toPoint())
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if href else Qt.CursorShape.IBeamCursor
        )
        super().mouseMoveEvent(event)

    # ------------------------------------------------------------ 图片右键
    def image_at(self, pos) -> str:
        """判断点是否落在图片上，返回图片名字（拿不到名字就给空串）。"""
        from PySide6.QtGui import QTextCursor

        cur = self.cursorForPosition(pos)
        for probe in (cur, QTextCursor(cur)):
            fmt = probe.charFormat()
            if fmt.isImageFormat():
                return str(fmt.toImageFormat().name() or "image")
        # 点在大图内部时，光标往往落在图片字符之后，往左再看一格
        prev = QTextCursor(cur)
        if prev.movePosition(QTextCursor.MoveOperation.PreviousCharacter):
            if prev.charFormat().isImageFormat():
                rect = self.cursorRect(prev)
                if rect.left() - 40 <= pos.x() <= rect.right() + 800:
                    return str(prev.charFormat().toImageFormat().name() or "image")
        return ""

    def _copy_image(self, src: str) -> bool:
        """把正文里那张图片放回剪贴板。"""
        from urllib.parse import unquote

        fname = unquote(str(src or "").replace(rw.EMBED_SCHEME + "://", ""))
        path = rw.image_path(fname)
        if path is None:
            return False
        img = QImage(str(path))
        if img.isNull():
            return False
        QApplication.clipboard().setImage(img)
        win = self.window()
        if hasattr(win, "statusBar"):
            win.statusBar().showMessage("已复制图片，可直接粘贴到编辑框", 3000)
        return True

    def contextMenuEvent(self, event):
        pos = event.pos()
        name = self.image_at(pos)
        menu = QMenu(self)
        if name:
            title = menu.addAction("这张图片")
            title.setEnabled(False)
            menu.addSeparator()
            copy_img = menu.addAction("复制这张图片")
            copy_img.setData("copyimg")
            menu.addSeparator()
        else:
            title = menu.addAction("页面图片大小")
            title.setEnabled(False)
        menu.addSeparator()
        for label, px in (("小  320", 320), ("中  420", 420), ("大  520", 520),
                          ("特大  680", 680), ("原始尺寸", 0)):
            act = menu.addAction(label)
            act.setData(px)
        menu.addSeparator()
        custom = menu.addAction("自定义…")
        custom.setData(-1)
        menu.addSeparator()
        copy_act = menu.addAction("复制")
        copy_act.setData("copy")
        all_act = menu.addAction("全选")
        all_act.setData("all")

        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        data = chosen.data()
        if data == "copyimg":
            self._copy_image(name)
        elif data == "copy":
            self.copy()
        elif data == "all":
            self.selectAll()
        else:
            self.window().apply_image_menu(data)


class BulkAddDialog(QDialog):
    """一次粘一串字/词，只建最小词条，立刻参与例句联想。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量加字")
        self.setMinimumSize(560, 430)
        lay = QVBoxLayout(self)
        tip = QLabel("每行一个，或用空格、逗号分隔。不用写释义——加进去就能在例句里点。")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("我 你 他 她 吃 喝 走 看 说\n\n或者一行一个：\n我\n你\n他")
        lay.addWidget(self.text, 1)
        hint = QLabel("只会建「词条名 + 待补标签」的空词条；之后在词条页点「编辑」补释义。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#78828c;font-size:11px;background:transparent;")
        lay.addWidget(hint)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("全部加入")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def terms(self) -> list[str]:
        out, seen = [], set()
        for piece in re.split(r"[\s,\uff0c\u3001;\uff1b]+", self.text.toPlainText()):
            piece = piece.strip()
            if piece and piece not in seen:
                seen.add(piece)
                out.append(piece)
        return out


IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")


def clipboard_image() -> "QImage | None":
    """从剪贴板取图，兼容三种情况：
    1. 位图（截图工具 / 网页图片右键复制）
    2. 复制的是图片文件（Finder / 资源管理器里 Cmd+C）
    3. 复制的是图片路径文本
    """
    cb = QApplication.clipboard()
    img = cb.image()
    if not img.isNull():
        return img

    md = cb.mimeData()
    if md is not None and md.hasUrls():
        for url in md.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if path.lower().endswith(IMG_EXTS) and os.path.exists(path):
                im = QImage(path)
                if not im.isNull():
                    return im

    text = (cb.text() or "").strip().strip('"')
    if 0 < len(text) < 400 and text.lower().endswith(IMG_EXTS) and os.path.exists(text):
        im = QImage(text)
        if not im.isNull():
            return im
    return None


class MainImageButton(QToolButton):
    """主图按钮：左键选/换图，右键可删除。"""

    def contextMenuEvent(self, event):
        has_img = bool(self.icon().pixmap(8, 8).size().width())
        menu = QMenu(self)
        copy_act = menu.addAction("复制这张图片")
        copy_act.setEnabled(has_img)
        menu.addSeparator()
        replace = menu.addAction("更换图片")
        delete = menu.addAction("删除这张主图")
        delete.setEnabled(has_img)
        chosen = menu.exec(event.globalPos())
        win = self.window()
        if chosen is copy_act:
            if hasattr(win, "_copy_editor_image"):
                win._copy_editor_image(0)
        elif chosen is replace:
            self.click()
        elif chosen is delete:
            if hasattr(win, "_drop_main_image"):
                win._drop_main_image()


class PasteLineEdit(QLineEdit):
    """普通输入框，但 Ctrl+V 粘贴的是图片时不当文本处理。"""

    imagePasted = Signal()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            if clipboard_image() is not None:
                self.imagePasted.emit()
                return
        super().keyPressEvent(event)


class PasteTextEdit(QPlainTextEdit):
    """多行输入框，同样支持粘贴图片。"""

    imagePasted = Signal()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            if clipboard_image() is not None:
                self.imagePasted.emit()
                return
        super().keyPressEvent(event)


class EntryEditor(QDialog):
    """与词条页同版式的编辑器：71/29 双栏、同样的字号层级与细线位置。

    左边是正文（词目、读音、词形、汉字信息、义项、短语、词源），
    右边是侧栏（词频、词形汇总、分类、图片）。每个字段都是输入框，
    样式做成「下划虚线 / 细框」，填了内容也能看出是什么。
    """

    def __init__(self, parent=None, entry: dict | None = None, prefill: str = "",
                 existing: set[str] | None = None):
        super().__init__(parent)
        self.entry = entry
        if existing is None and parent is not None and hasattr(parent, "entries"):
            existing = {e["headword"] for e in parent.entries}
        self.existing: set[str] = set(existing or ())
        self.dup_head = ""          # 若用户坚持重名保存，这里记下名字
        self._main_image: dict | None = None   # 甲骨文 / 主图
        self._extras: list[dict] = []          # 其它图片
        self._sense_rows: list[dict] = []

        self.setWindowTitle("编辑词条" if entry else "新建词条")
        self.resize(1000, 880)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("EditorScroll")
        page = QWidget()
        page.setObjectName("EditorPage")

        # 与词条页一致：左 71% / 右 29%，中间 26px 间距
        cols = QHBoxLayout(page)
        cols.setContentsMargins(24, 18, 24, 18)
        cols.setSpacing(26)

        left = QWidget()
        self.form = QVBoxLayout(left)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(0)
        cols.addWidget(left, 62)

        right = QWidget()
        self.side = QVBoxLayout(right)
        self.side.setContentsMargins(0, 0, 0, 0)
        self.side.setSpacing(0)
        cols.addWidget(right, 38)

        senses_val = (entry or {}).get("senses") or [{}]
        pron = (entry or {}).get("pronunciation") or {}
        char = (entry or {}).get("character") or {}

        # ======================================================= 左栏：词目
        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        self.f_head = self._line("词条", entry["headword"] if entry else prefill, "Headline")
        self.f_head.textChanged.connect(self._sync_lang)
        self.f_head.textChanged.connect(self._sync_dup)
        self.lang_hint = QLabel("中文")
        self.lang_hint.setObjectName("EditorHint")
        self.lang_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        head_box = QVBoxLayout()
        head_box.setContentsMargins(0, 0, 0, 0)
        head_box.setSpacing(2)
        head_box.addWidget(self._wrap(self.f_head))
        self.dup_hint = QLabel("")
        self.dup_hint.setObjectName("DupHint")
        self.dup_hint.setVisible(False)
        head_box.addWidget(self.dup_hint)
        head_row.addLayout(head_box, 1)

        self.btn_main_img = MainImageButton()
        self.btn_main_img.setObjectName("MainImg")
        self.btn_main_img.setFixedSize(58, 58)
        self.btn_main_img.setToolTip("左键选/换甲骨文图，右键可删除")
        self.btn_main_img.clicked.connect(self._pick_main_image)
        head_row.addWidget(self.btn_main_img)
        head_row.addSpacing(8)
        head_row.addWidget(self.lang_hint)
        self.form.addLayout(head_row)

        # 读音行（词条页：拼音 / 英音 / 美音 / 词频方块）
        pron_row = QHBoxLayout()
        pron_row.setContentsMargins(0, 4, 0, 0)
        pron_row.setSpacing(10)
        self.f_pron = self._line("拼音或音标，如 pǎo / /rʌn/",
                                 pron.get("pinyin") or pron.get("uk") or pron.get("us") or "",
                                 "Subline")
        self.freq_dots = QLabel("")
        self.freq_dots.setObjectName("FreqDots")
        pron_row.addWidget(self._wrap(self.f_pron), 1)
        pron_row.addWidget(self.freq_dots)
        self.form.addLayout(pron_row)

        self.form.addSpacing(6)
        self.form.addWidget(self._rule())

        # 词形变化不再提供输入（数据保留在 JSON 里）

        # 其余图片（主图之外的）
        self.form.addWidget(self._section("其他图片"))
        self.extra_bar = QHBoxLayout()
        self.extra_bar.setSpacing(6)
        btn_more = QPushButton("＋ 添加")
        btn_more.setObjectName("EditorGhost")
        btn_more.setFixedSize(88, 88)
        btn_more.clicked.connect(self._add_extra_image)
        self.extra_bar.addWidget(btn_more)
        self.extra_bar.addStretch(1)
        self.form.addLayout(self.extra_bar)

        # 专属粘贴框：焦点在这里按 Ctrl+V 直接贴图
        self.paste_box = PasteTextEdit()
        self.paste_box.setObjectName("PasteArea")
        self.paste_box.setPlaceholderText("在这里 Ctrl+V 粘贴图片")
        self.paste_box.setFixedHeight(56)
        self.paste_box.imagePasted.connect(self._paste_here)
        self.form.addWidget(self.paste_box)

        # 义项
        self.form.addSpacing(8)
        self.sense_box = QVBoxLayout()
        self.sense_box.setContentsMargins(0, 0, 0, 0)
        self.sense_box.setSpacing(14)
        self.form.addLayout(self.sense_box)

        add_row = QHBoxLayout()
        add_sense = QPushButton("＋ 添加义项")
        add_sense.setObjectName("EditorGhost")
        add_sense.clicked.connect(lambda: self._add_sense())
        add_row.addWidget(add_sense)
        add_row.addStretch(1)
        self.form.addLayout(add_row)

        # 短语 / 词源
        self.form.addWidget(self._section("短语 / 习语"))
        self.f_phrases = self._line("跑题—偏离主题|跑腿—奔走做杂事",
                                    "|".join(f'{x.get("phrase")}—{x.get("meaning")}'
                                             for x in (entry or {}).get("phrases") or []))
        self.form.addWidget(self._wrap(self.f_phrases))

        self.form.addWidget(self._section("词源"))
        self.f_etym = self._area("如：形声字，从足包声（可换行）",
                                 (entry or {}).get("etymology", ""), 4, lines=True)
        self.f_etym.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.form.addWidget(self._wrap(self.f_etym))

        # ---- 关联字：整宽，四块
        self.form.addWidget(self._section("右侧栏关联字"))
        rel_hint = QLabel("按词条字自动识别，可改；空格 / 逗号 / 、分隔；留空表示不显示该栏")
        rel_hint.setObjectName("EditorHint")
        rel_hint.setWordWrap(True)
        self.form.addWidget(rel_hint)

        self.f_rel = {}
        for key, cap, hint in (("homophones", "同音", "已自动合并同音与近音，可增删"),
                               ("same_radical", "同形", "同偏旁部首，可手填"),
                               ("contains", "同源", "手动填写")):
            self.form.addWidget(self._cap(cap))
            box = self._area(hint, "", 4, lines=True)
            box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.f_rel[key] = box
            box.textChanged.connect(lambda b=box: setattr(b, "_touched", True))
            self.form.addWidget(box)

        self.form.addStretch(1)

        # ======================================================= 右栏：侧栏
        self.side.addWidget(self._rule())

        self.side.addWidget(self._section("词频"))
        freq_row = QHBoxLayout()
        self.f_freq = QSpinBox()
        self.f_freq.setRange(0, 5)
        self.f_freq.setSpecialValueText("未设置")
        self.f_freq.setValue((entry or {}).get("frequency") or 0)
        self.f_freq.setObjectName("FreqEdit")
        self.f_freq.valueChanged.connect(self._sync_freq)
        freq_row.addWidget(self.f_freq)
        freq_row.addStretch(1)
        self.side.addLayout(freq_row)

        self.side.addWidget(self._section("分类"))
        self.f_tags = self._line("动作、常用（用、或, 分隔）",
                                 "、".join((entry or {}).get("tags") or []))
        self.side.addWidget(self._wrap(self.f_tags))

        hint = QLabel("在任意输入框里 Ctrl+V 可直接粘贴图片，\n"
                      "缩略图只在这里显示，词条页显示的是大图。")
        hint.setObjectName("EditorHint")
        hint.setWordWrap(True)
        self.side.addWidget(self._section("插图"))
        self.side.addWidget(hint)

        self.side.addStretch(1)

        scroll.setWidget(page)

        # ======================================================= 底部按钮
        bar = QWidget()
        bar.setObjectName("EditorBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(24, 10, 24, 10)
        bl.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("EditorGhost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("EditorPrimary")
        save.clicked.connect(self._save)
        bl.addWidget(cancel)
        bl.addWidget(save)

        root.addWidget(scroll, 1)
        root.addWidget(bar)

        for sd in senses_val:
            self._add_sense(sd)
        if not senses_val:
            self._add_sense({})

        _imgs = [dict(x) for x in ((entry or {}).get("images") or [])]
        self._main_image = _imgs[0] if _imgs else None
        self._extras = _imgs[1:]
        self._refresh_main_image()
        self._refresh_extra_images()

        custom = (entry or {}).get("relations") or {}
        for key, box in self.f_rel.items():
            box.blockSignals(True)
            box.setPlainText(" ".join(custom.get(key) or []))
            box._touched = bool(custom.get(key))
            box.blockSignals(False)
        # 只有同音自动补；同形要求为空，不自动抓
        if not self.f_rel["homophones"].toPlainText().strip():
            self._fill_relations(force=True)
        self.f_head.textChanged.connect(lambda _: self._fill_relations())

        self._sync_lang()
        self._sync_freq()
        self._sync_forms()

    # ---------------------------------------------------------------- 小元件
    def _line(self, placeholder: str, value: str = "", obj: str = "EditorField") -> QLineEdit:
        w = PasteLineEdit(value or "")
        w.setPlaceholderText(placeholder)
        w.setObjectName(obj)
        w._img_list = []
        w.imagePasted.connect(lambda w=w: self._paste_into(w))
        return w

    def _area(self, placeholder: str, value: str = "", height: int = 60,
              lines: bool = False) -> QPlainTextEdit:
        w = PasteTextEdit(value or "")
        w.setPlaceholderText(placeholder)
        w.setObjectName("EditorArea")
        if lines:
            fm = w.fontMetrics()
            w.setFixedHeight(fm.lineSpacing() * height + 24)   # 按行数算高度
        else:
            w.setFixedHeight(height)
        w._img_list = []
        w.imagePasted.connect(lambda w=w: self._paste_into(w))
        return w

    # ---------------------------------------------------------------- 粘贴图片
    def _paste_into(self, field=None):
        """输入框粘贴图片：词条名那一行 → 甲骨文主图；其它 → 其他图片。"""
        img = clipboard_image()
        if img is None:
            return False
        name = self._save_pixmap(QPixmap.fromImage(img))
        if not name:
            QMessageBox.warning(self, "保存失败", "图片没能写入 data/images。")
            return False

        if field is not None and field is getattr(self, "f_head", None):
            self._main_image = {"file": name, "caption": ""}
            self._refresh_main_image()
        else:
            self._extras.append({"file": name, "caption": ""})
            self._refresh_extra_images()
        return True

    def _refresh_field_thumbs(self, field):
        row = getattr(field, "_thumb_row", None)
        if row is None:
            return
        while row.count():
            it = row.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        for i, im in enumerate(field._img_list):
            btn = QToolButton()
            btn.setObjectName("Thumb")
            btn.setToolTip("点击删除这张图")
            pix = QPixmap(str(rw.image_path(im["file"]) or ""))
            if not pix.isNull():
                btn.setIcon(QIcon(pix))
                btn.setIconSize(QSize(38, 38))
            btn.setFixedSize(44, 44)
            btn.clicked.connect(lambda _=False, f=field, idx=i: self._drop_field_image(f, idx))
            row.addWidget(btn)
        row.addStretch(1)

    def _drop_field_image(self, field, idx: int):
        if 0 <= idx < len(field._img_list):
            field._img_list.pop(idx)
            self._refresh_field_thumbs(field)

    # ---------------------------------------------------------------- 图片（主图 / 其余）
    def _all_images(self) -> list[dict]:
        """主图在前，其余在后。"""
        imgs = []
        if self._main_image:
            imgs.append(self._main_image)
        imgs.extend(self._extras)
        return imgs

    def _refresh_main_image(self):
        btn = self.btn_main_img
        if self._main_image:
            pix = QPixmap(str(rw.image_path(self._main_image["file"]) or ""))
            if not pix.isNull():
                btn.setIcon(QIcon(pix))
                btn.setIconSize(QSize(52, 52))
            btn.setText("")
        else:
            btn.setIcon(QIcon())
            btn.setText("＋图")

    def _refresh_extra_images(self):
        while self.extra_bar.count() > 2:          # 保留「添加」和弹簧
            it = self.extra_bar.takeAt(1)
            w = it.widget()
            if w:
                w.deleteLater()
        for i, im in enumerate(self._extras):
            btn = QToolButton()
            btn.setObjectName("Thumb")
            btn.setToolTip("左键删除，右键更多")
            pix = QPixmap(str(rw.image_path(im["file"]) or ""))
            if not pix.isNull():
                btn.setIcon(QIcon(pix))
                btn.setIconSize(QSize(82, 82))
            btn.setFixedSize(88, 88)
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, idx=i, b=btn: self._thumb_menu(idx, b))
            btn.clicked.connect(lambda _=False, idx=i: self._drop_extra_image(idx))
            self.extra_bar.insertWidget(self.extra_bar.count() - 1, btn)

    def _thumb_menu(self, idx: int, btn):
        """缩略图右键：复制 / 删除。"""
        menu = QMenu(btn)
        copy_act = menu.addAction("复制这张图片")
        menu.addSeparator()
        del_act = menu.addAction("删除这张图片")
        chosen = menu.exec(btn.mapToGlobal(btn.rect().center()))
        if chosen is copy_act:
            self._copy_editor_image(idx + 1)      # 0 是主图
        elif chosen is del_act:
            self._drop_extra_image(idx)

    def _copy_editor_image(self, idx: int) -> bool:
        """idx=0 主图，>=1 其余图片。"""
        imgs = self._all_images()
        if not (0 <= idx < len(imgs)):
            return False
        path = rw.image_path(imgs[idx]["file"])
        if path is None:
            return False
        img = QImage(str(path))
        if img.isNull():
            return False
        QApplication.clipboard().setImage(img)
        win = self.window()
        if hasattr(win, "statusBar"):
            win.statusBar().showMessage("已复制图片", 2500)
        return True

    def _drop_extra_image(self, idx: int):
        if 0 <= idx < len(self._extras):
            self._extras.pop(idx)
            self._refresh_extra_images()

    def _drop_main_image(self):
        """只清空主图位，其余图片保持不变。"""
        self._main_image = None
        self._refresh_main_image()

    def _pick_main_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选甲骨文 / 主图", str(pathlib.Path.home()),
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        name = self._save_pixmap(QPixmap(path))
        if not name:
            return
        self._main_image = {"file": name, "caption": ""}
        self._refresh_main_image()

    def _paste_here(self):
        """专属粘贴框：贴图进「其他图片」，并把框清空。"""
        if self._paste_into():
            self.paste_box.clear()
            self.paste_box.setPlaceholderText("已加入，可继续粘贴")

    def _add_extra_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "添加图片", str(pathlib.Path.home()),
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        name = self._save_pixmap(QPixmap(path))
        if not name:
            return
        self._extras.append({"file": name, "caption": ""})
        self._refresh_extra_images()

    # ---------------------------------------------------------------- 关联字
    def _fill_relations(self, force: bool = False):
        """同音（含近音）、同形（同偏旁）自动填；同源保持手填。"""
        head = self.f_head.text().strip()
        parent = self.parent()
        if not head or not hasattr(parent, "entries"):
            return

        probe = dict(self.entry or {})
        probe["headword"] = head
        probe["id"] = probe.get("id") or f"probe-{head}"
        same = next((e for e in parent.entries if e["headword"] == head), None)
        if same:
            if head != (self.entry or {}).get("headword"):
                probe["pronunciation"] = same.get("pronunciation")
            if not (probe.get("character") or {}).get("radical"):
                probe["character"] = dict(same.get("character") or {})

        autos = {
            "homophones": sound_relatives(probe, parent.entries),
        }
        for key, names in autos.items():
            box = self.f_rel.get(key)
            if box is None:
                continue
            if not force and getattr(box, "_touched", False):
                continue
            box.blockSignals(True)
            box.setPlainText(" ".join(names))
            box._touched = False
            box.blockSignals(False)

    def _collect_relations(self) -> dict:
        """只保存用户动过的栏，没动过的交给自动识别。"""
        out = {}
        for key, box in self.f_rel.items():
            text = (box.toPlainText().replace("、", " ").replace("，", " ")
                    .replace(",", " ").replace("/", " "))
            items = [x for x in text.split() if x]
            # 有内容就保存（同音是自动填的，也算）；空的只在动过时记录
            if not items and not getattr(box, "_touched", False):
                continue
            out[key] = items
        return out

    def _wrap(self, field) -> QWidget:
        """输入框 + 下方缩略图行，作为一个整体放进布局。"""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addWidget(field)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        v.addLayout(row)
        field._thumb_row = row
        return box

    @staticmethod
    def _save_pixmap(pix: QPixmap) -> str:
        """缩到 560 宽后存进 data/images，返回文件名。"""
        if pix.isNull():
            return ""
        if pix.width() > 560:
            pix = pix.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation)
        name = f"img-{uuid.uuid4().hex[:10]}.png"
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        if not pix.save(str(IMAGES_DIR / name), "PNG"):
            return ""
        return name
        if pix.width() > 560:
            pix = pix.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation)
        name = f"img-{uuid.uuid4().hex[:10]}.png"
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        if not pix.save(str(IMAGES_DIR / name), "PNG"):
            return ""
        return name

    def _rule(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("EditorRule")
        return line

    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("EditorSection")
        return lbl

    def _cap(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("EditorCap")
        return lbl

    # ---------------------------------------------------------------- 查重
    def _is_dup(self, head: str) -> bool:
        """这个词头是否与词库里已有条目重名（编辑自己不算）。"""
        head = (head or "").strip()
        if not head or head not in self.existing:
            return False
        if self.entry and self.entry.get("headword") == head:
            return False
        return True

    def _sync_dup(self):
        head = self.f_head.text().strip()
        if self._is_dup(head):
            self.dup_hint.setText(f"词库里已有「{head}」")
            self.dup_hint.setVisible(True)
        else:
            self.dup_hint.setVisible(False)

    def _ask_duplicate(self, head: str) -> bool:
        """重名时弹窗；返回 True 表示继续保存。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("查重")
        box.setText(f"词库里已经有「{head}」了。")
        box.setInformativeText("重名保存会产生两条同名词条，链接会指向先出现的那条。")
        b_back = box.addButton("返回修改", QMessageBox.ButtonRole.RejectRole)
        b_save = box.addButton("仍然保存", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(b_back)
        box.exec()
        return box.clickedButton() is b_save

    # ---------------------------------------------------------------- 联动
    def _sync_lang(self):
        zh = dm.has_cjk(self.f_head.text())
        self.lang_hint.setText("中文" if zh else "ENGLISH")

    def _sync_freq(self):
        level = self.f_freq.value()
        dots = "".join("■" if i < level else "□" for i in range(5))
        self.freq_dots.setText(dots)

    def _sync_forms(self):
        """词形变化已不显示，保留空实现。"""

    # ---------------------------------------------------------------- 义项
    def _add_sense(self, data: dict | None = None):
        data = data or {}
        row = QWidget()
        outer = QHBoxLayout(row)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        num = QLabel(str(len(self._sense_rows) + 1))
        num.setObjectName("SenseNum")
        num.setFixedWidth(26)
        num.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(1)
        f_pos = self._line("动词 / VERB", data.get("pos", ""), "SenseTag")
        f_def = self._area("柯林斯式整句释义最佳", data.get("definition", ""), 5, lines=True)

        ex = (data.get("examples") or [{}])[0]
        f_ex = self._area("可选；写进去以后句中的词也能点", ex.get("text", ""), 5, lines=True)

        f_meta = self._area(
            "每行一项，也可用 | 分隔",
            "\n".join((data.get("synonyms") or []) + (data.get("collocations") or [])
                      + (data.get("labels") or [])),
            5, lines=True,
        )
        for cap, w in (("词性", f_pos), ("释义", f_def),
                       ("例句", f_ex), ("近义 / 搭配 / 标注", f_meta)):
            col.addWidget(self._cap(cap))
            col.addWidget(self._wrap(w))

        # 该义项已带的图片（来自编辑已有词条）
        sense_imgs = [dict(x) for x in (data.get("images") or [])]

        remove = QPushButton("删除")
        remove.setObjectName("SenseRemove")
        remove.clicked.connect(lambda: self._remove_sense(row))
        head = QHBoxLayout()
        head.addStretch(1)
        head.addWidget(remove)

        right = QVBoxLayout()
        right.setSpacing(2)
        right.addLayout(head)
        right.addLayout(col)

        outer.addWidget(num)
        outer.addLayout(right, 1)
        self._sense_rows.append({
            "widget": row, "num": num, "pos": f_pos, "def": f_def,
            "ex": f_ex, "meta": f_meta,
            "images": sense_imgs,
        })
        self.sense_box.addWidget(row)
        self._renumber()

    def _remove_sense(self, widget):
        self._sense_rows = [r for r in self._sense_rows if r["widget"] is not widget]
        widget.setParent(None)
        widget.deleteLater()
        self._renumber()

    def _renumber(self):
        for i, r in enumerate(self._sense_rows, 1):
            r["num"].setText(str(i))

    # ---------------------------------------------------------------- 保存
    def _save(self):
        head = self.f_head.text().strip()
        if not head:
            QMessageBox.warning(self, "缺词条", "词条名不能为空。")
            return

        # 查重：词头与已有条目重名时先问
        self.dup_head = ""
        if self._is_dup(head):
            if not self._ask_duplicate(head):
                self.f_head.setFocus()
                self.f_head.selectAll()
                return
            self.dup_head = head

        # 词条级图片：主图在前，其余在后
        entry_imgs = self._all_images()

        senses = []
        for r in self._sense_rows:
            definition = r["def"].toPlainText().rstrip()
            if not definition:
                continue
            example = r["ex"].toPlainText().rstrip()
            senses.append({
                "pos": r["pos"].text().strip(),
                "definition": definition,
                "definitionZh": "",
                "images": (r.get("images") or []) + [
                    im for f in (r["pos"], r["def"], r["ex"], r["meta"])
                    for im in (getattr(f, "_img_list", []) or [])
                ],
                "examples": ([{"text": example, "translation": ""}]
                             if example else []),
                "synonyms": [
                    item.strip()
                    for line in r["meta"].toPlainText().splitlines()
                    for item in re.split(r"[|｜]", line)
                    if item.strip()
                ],
            })
        if not senses:
            QMessageBox.warning(self, "缺释义", "至少写一条释义。")
            return

        phrases = []
        for piece in self.f_phrases.text().split("|"):
            piece = piece.strip()
            if not piece:
                continue
            if "—" in piece:
                a, b = piece.split("—", 1)
                phrases.append({"phrase": a.strip(), "meaning": b.strip()})
            else:
                phrases.append({"phrase": piece, "meaning": ""})

        zh = dm.has_cjk(head)
        pron = self.f_pron.text().strip()
        raw = {
            "headword": head,
            "lang": "zh" if zh else "en",
            "frequency": self.f_freq.value() or None,
            "pronunciation": {"pinyin": pron} if zh else {"uk": pron},
            "wordForms": (self.entry or {}).get("wordForms") or [],
            "senses": senses,
            "phrases": phrases,
            "etymology": self.f_etym.toPlainText().rstrip(),
            "images": entry_imgs,
            "relations": self._collect_relations(),
            "tags": [t.strip() for t in self.f_tags.text().replace(",", "、").split("、") if t.strip()],
        }
        if zh:
            # 部首/笔画/繁体不再编辑，原样保留
            raw["character"] = dict((self.entry or {}).get("character") or {})
        if self.entry:
            raw["id"] = self.entry["id"]
        elif self.dup_head:
            raw["id"] = ""      # 交给 normalize 生成唯一 id，避免撞车
        self.result_entry = dm.normalize_entry(raw)
        if not self.result_entry:
            QMessageBox.warning(self, "保存失败", "数据不完整。")
            return
        self.accept()


def pathlib_home() -> pathlib.Path:
    return pathlib.Path.home()


class DictWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("词典")
        self.resize(1240, 820)
        self.setMinimumSize(980, 620)

        self.entries: list[dict] = dm.load_entries(WORDS_PATH)
        self.index = dm.Index(self.entries, auto_new=dm.Index.default_auto_new)
        self.current_id: str | None = None
        self._silent = False
        self._font_delta = self._load_font_delta()
        rw.set_font_delta(self._font_delta)
        self._image_width = self._load_setting("image_width", 420)
        rw.set_image_width(self._image_width)

        self._history: list[str] = []   # 浏览过的词条 id
        self._hist_pos: int = -1        # 当前所处位置
        self._first_open = True         # 启动时自动选中不计入历史

        self._build_ui()
        self._build_menu()
        self._apply_ui_font()      # 把保存的字号增量应用到菜单/列表/状态栏
        self.refresh_list()
        self.show_welcome()
        self.setAcceptDrops(True)
        self.listw.setFocus()

    # ---------------------------------------------------------------- UI
    def eventFilter(self, obj, event):
        """鼠标侧键（后退/前进）。"""
        if obj is getattr(self, "browser", None) and event.type() == event.Type.MouseButtonPress:
            btn = event.button()
            if btn == Qt.MouseButton.BackButton:
                self.go_back()
                return True
            if btn == Qt.MouseButton.ForwardButton:
                self.go_forward()
                return True
        return super().eventFilter(obj, event)

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶栏
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(54)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 8, 16, 8)
        h.setSpacing(10)

        self.btn_back = QPushButton("\u2039")
        self.btn_back.setObjectName("Nav")
        self.btn_back.setFixedSize(28, 28)
        self.btn_back.setToolTip("后退（Alt+\u2190，或鼠标侧键）")
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setEnabled(False)
        self.btn_back.clicked.connect(self.go_back)

        self.btn_forward = QPushButton("\u203a")
        self.btn_forward.setObjectName("Nav")
        self.btn_forward.setFixedSize(28, 28)
        self.btn_forward.setToolTip("前进（Alt+\u2192，或鼠标侧键）")
        self.btn_forward.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_forward.setEnabled(False)
        self.btn_forward.clicked.connect(self.go_forward)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("搜索词条 / 拼音 / 释义")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(280)
        self.search.textChanged.connect(self.refresh_list)
        self.search.returnPressed.connect(self._open_first)

        btn_import = QPushButton("导入")
        btn_import.setObjectName("Top")
        btn_import.clicked.connect(self.import_dialog)
        btn_new = QPushButton("新建")
        btn_new.setObjectName("Top")
        btn_new.clicked.connect(lambda: self.new_entry())

        self.search.setMaximumWidth(560)
        h.addWidget(self.btn_back)
        h.addWidget(self.btn_forward)
        h.addSpacing(6)
        h.addWidget(self.search)
        h.addStretch(1)
        h.addWidget(btn_import)
        h.addWidget(btn_new)

        # 主体
        self.listw = QListWidget()
        self.listw.setObjectName("WordList")
        self.listw.setItemDelegate(WordDelegate(self.listw))
        self.listw.setMouseTracking(True)
        self.listw.setUniformItemSizes(True)
        self.listw.currentItemChanged.connect(self._on_item_changed)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        bar = QHBoxLayout()
        self.lang_filter = QComboBox()
        self.lang_filter.addItems(["全部", "中文", "英文"])
        self.lang_filter.currentIndexChanged.connect(self.refresh_list)
        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("Count")
        bar.addWidget(self.lang_filter)
        bar.addStretch(1)
        bar.addWidget(self.count_label)
        lv.addLayout(bar)
        lv.addWidget(self.listw, 1)

        self.browser = EntryView()
        self.browser.anchorClicked.connect(self.on_anchor)
        self.browser.installEventFilter(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])
        splitter.setChildrenCollapsible(False)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(18, 10, 18, 6)
        bl.addWidget(splitter)

        root.addWidget(header)
        root.addWidget(body, 1)
        self.setCentralWidget(central)

    def _build_menu(self):
        bar = self.menuBar()

        m_file = bar.addMenu("文件(&F)")
        self._action(m_file, "导入 CSV…", self.import_dialog)
        self._action(m_file, "导入 JSON…", lambda: self.import_dialog(json_only=True))
        m_file.addSeparator()
        self._action(m_file, "导出 JSON…", self.export_json)
        self._action(m_file, "导出 CSV…", self.export_csv)
        m_file.addSeparator()
        self._action(m_file, "数据信息", self.show_data_info)
        self._action(m_file, "打开数据文件夹", self.open_data_dir)
        m_file.addSeparator()
        self._action(m_file, "退出", self.close, "Ctrl+Q")

        m_entry = bar.addMenu("词条(&E)")
        self._action(m_entry, "新建词条", lambda: self.new_entry(), "Ctrl+N")
        self._action(m_entry, "编辑当前词条", self.edit_current, "Ctrl+E")
        self._action(m_entry, "批量加字…", self.bulk_add, "Ctrl+B")
        self._action(m_entry, "删除当前词条", self.delete_current)
        self._action(m_entry, "复制当前词条 JSON", self.copy_current)
        m_entry.addSeparator()

        m_view = bar.addMenu("视图(&V)")
        self._action(m_view, "后退", self.go_back, "Alt+Left")
        self._action(m_view, "前进", self.go_forward, "Alt+Right")
        m_view.addSeparator()
        zoom_in = self._action(m_view, "放大正文", lambda: self.bump_font(+1.0))
        zoom_in.setShortcuts([QKeySequence(k) for k in
                              ("Ctrl+=", "Ctrl++", "Ctrl+Shift+=", "Ctrl+Shift++")])
        zoom_out = self._action(m_view, "缩小正文", lambda: self.bump_font(-1.0))
        zoom_out.setShortcuts([QKeySequence(k) for k in
                               ("Ctrl+-", "Ctrl+Shift+-", "Ctrl+_")])
        self._action(m_view, "重置字号", self.reset_zoom, "Ctrl+0")
        m_view.addSeparator()
        for step in (2, 4, -2):
            label = f"{'+' if step > 0 else ''}{step}pt"
            self._action(m_view, f"整体{label}",
                         lambda checked=False, v=step: self.set_font_delta(v))
        m_view.addSeparator()
        self._action(m_view, "搜索框", self.focus_search, "Ctrl+F")
        m_view.addSeparator()
        self.strict_action = QAction("只让库里的字可点（严格模式）", self, checkable=True)
        self.strict_action.setChecked(not dm.Index.default_auto_new)
        self.strict_action.toggled.connect(self.toggle_strict)
        m_view.addAction(self.strict_action)

        m_img = m_view.addMenu("图片大小")
        for label, px in (("小 320", 320), ("中 420", 420), ("大 520", 520),
                          ("特大 680", 680), ("原始尺寸", 0)):
            act = QAction(label, self)
            act.triggered.connect(lambda checked=False, v=px: self.set_image_width(v))
            m_img.addAction(act)

        m_tool = bar.addMenu("工具(&T)")
        # 批量加字已在「词条」菜单里（Ctrl+B），这里不重复注册，否则快捷键会冲突
        self._action(m_tool, "图片诊断", self.show_image_info)
        self._action(m_tool, "从例句自动收词（把句子里出现过的汉字都收进库）",
                     self.auto_collect_chars)

        m_help = bar.addMenu("帮助(&H)")
        self._action(m_help, "关于", self.about)

        self._slash = QShortcut(QKeySequence("/"), self)
        self._slash.activated.connect(self.focus_search)

    def _action(self, menu, text, slot, shortcut=None) -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    # ---------------------------------------------------------------- 数据
    def _persist(self) -> bool:
        """写盘并重建索引；写不进去时提示，不抛异常。"""
        try:
            dm.save_entries(WORDS_PATH, self.entries)
        except OSError as exc:
            QMessageBox.warning(
                self, "保存失败",
                f"写不进词库文件：\n{WORDS_PATH}\n\n{exc}\n\n"
                "「文件 → 数据信息」可以查看当前数据目录；\n"
                "也可以设置环境变量 DICT_DATA_DIR 指到一个可写的位置。")
            return False
        self.index = dm.Index(self.entries, auto_new=dm.Index.default_auto_new)
        return True

    def _commit(self):
        """写盘 → 重建索引 → 刷新列表 → 重画当前词条：新词立刻在句子里可点。"""
        if not self._persist():
            return
        self.refresh_list()
        self._rerender()

    def _rerender(self):
        entry = next((x for x in self.entries if x["id"] == self.current_id), None)
        if not entry:
            self.show_welcome()
            return
        pos = self.browser.verticalScrollBar().value()
        backs = [x for x in self.entries if x["id"] in (self.index.inbound.get(entry["id"]) or [])]
        self._apply_entry_html(entry, rw.entry_html(
            entry, self.index, backs, None, self.relations_for(entry)))
        self.browser.verticalScrollBar().setValue(pos)

    def _occurrences(self, entry: dict) -> list[dict]:
        """哪些例句里出现了这个词（句子本身也带链接）。"""
        out: list[dict] = []
        for o in self.entries:
            for s in o.get("senses") or []:
                for x in s.get("examples") or []:
                    text = x.get("text", "")
                    if any(k == "link" and eid == entry["id"]
                           for k, _t, eid in self.index.tokenize(text)):
                        out.append({"headword": o["headword"], "id": o["id"], "text": text})
        return out

    def _hits_for(self, ids: set[str]) -> tuple[int, int]:
        """新词在现有例句里被命中的处数 / 涉及词条数。"""
        hits, src = 0, set()
        for e in self.entries:
            for s in e.get("senses") or []:
                for x in s.get("examples") or []:
                    for kind, _tok, eid in self.index.tokenize(x.get("text", "")):
                        if kind == "link" and eid in ids and eid != e["id"]:
                            hits += 1
                            src.add(e["id"])
        return hits, len(src)

    def filtered(self) -> list[dict]:
        q = self.search.text().strip().lower()
        lang = self.lang_filter.currentText()
        out = []
        for e in self.entries:
            if lang == "中文" and e.get("lang") != "zh":
                continue
            if lang == "英文" and e.get("lang") != "en":
                continue
            if q:
                py = (e.get("pronunciation") or {}).get("pinyin", "")
                hay = " ".join([
                    e["headword"],
                    py,
                    _strip_tone(py),          # ai 也能搜到 ài
                    (e.get("pronunciation") or {}).get("uk", ""),
                    (e.get("character") or {}).get("traditional", ""),   # 繁体也能搜
                    " ".join(e.get("tags") or []),
                ] + [s.get("definition", "") + " " + s.get("definitionZh", "")
                     + " " + " ".join(x.get("text", "") for x in s.get("examples") or [])
                     for s in e.get("senses") or []]).lower()
                if q not in hay:
                    continue
            out.append(e)
        if q:
            ql = q.lower()

            def rank(e):
                head = e["headword"].lower()
                py = _strip_tone((e.get("pronunciation") or {}).get("pinyin", ""))
                if head == ql:
                    return 0          # 完全等于词条名
                if head.startswith(ql):
                    return 1          # 以它开头
                if ql in py:
                    return 2          # 拼音命中
                return 3              # 释义里出现
            out.sort(key=rank)
        return out

    def refresh_list(self):
        self.listw.blockSignals(True)
        self.listw.clear()
        rows = self.filtered()
        for e in rows:
            item = QListWidgetItem(self._item_text(e))
            item.setData(Qt.ItemDataRole.UserRole, e["id"])
            head, pron = self._item_parts(e)
            item.setData(Qt.ItemDataRole.UserRole + 1, head)
            item.setData(Qt.ItemDataRole.UserRole + 2, pron)
            item.setToolTip(self._item_tooltip(e))
            self.listw.addItem(item)
        self.listw.blockSignals(False)
        self.count_label.setText(f"{len(rows)} 条")

    @staticmethod
    def _item_parts(e: dict):
        pron = e.get("pronunciation") or {}
        p = pron.get("pinyin") or pron.get("uk") or pron.get("us") or ""
        homo = rw.sup(e["homograph"]) if e.get("homograph") else ""
        return f"{e['headword']}{homo}", p

    @staticmethod
    def _item_text(e: dict) -> str:
        pron = e.get("pronunciation") or {}
        p = pron.get("pinyin") or pron.get("uk") or pron.get("us") or ""
        homo = rw.sup(e["homograph"]) if e.get("homograph") else ""
        return f"{e['headword']}{homo}    {p}"

    @staticmethod
    def _item_tooltip(e: dict) -> str:
        first = (e.get("senses") or [{}])[0]
        return first.get("definitionZh") or first.get("definition") or "（无释义）"

    # ---------------------------------------------------------------- 联想
    def _select_in_list(self, eid: str):
        self._silent = True
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == eid:
                self.listw.setCurrentItem(item)
                self.listw.scrollToItem(item)
                break
        self._silent = False

    def _on_item_changed(self, current, previous):
        if self._silent or current is None:
            return
        eid = current.data(Qt.ItemDataRole.UserRole)
        record = not self._first_open
        self._first_open = False
        self.open_entry(eid, record=record)

    def open_entry(self, eid: str, record: bool = True):
        entry = next((x for x in self.entries if x["id"] == eid), None)
        if not entry:
            return
        if record:
            self._push_history(eid)
        self.current_id = eid
        backs = [x for x in self.entries if x["id"] in (self.index.inbound.get(eid) or [])]
        self._apply_entry_html(entry, rw.entry_html(
            entry, self.index, backs, None, self.relations_for(entry)))
        self.browser.verticalScrollBar().setValue(0)
        self._select_in_list(eid)
        self._update_nav()
        self.statusBar().showMessage(
            f"{entry['headword']} · {len(entry.get('senses') or [])} 个义项", 3000
        )

    # ---------------------------------------------------------------- 前进 / 后退
    def _push_history(self, eid: str):
        """把新词条压入历史；若正处在中间位置，先砍掉后面的前进记录。"""
        if 0 <= self._hist_pos < len(self._history) and self._history[self._hist_pos] == eid:
            return
        del self._history[self._hist_pos + 1:]
        self._history.append(eid)
        self._hist_pos = len(self._history) - 1
        if len(self._history) > 100:          # 只留最近 100 条
            self._history.pop(0)
            self._hist_pos -= 1

    def _update_nav(self):
        self.btn_back.setEnabled(self._hist_pos > 0)
        self.btn_forward.setEnabled(0 <= self._hist_pos < len(self._history) - 1)

    def go_back(self):
        if self._hist_pos <= 0:
            return
        self._hist_pos -= 1
        self._open_at_history()

    def go_forward(self):
        if self._hist_pos >= len(self._history) - 1:
            return
        self._hist_pos += 1
        self._open_at_history()

    def _open_at_history(self):
        """跳到历史当前位置；跳过已被删除的词条。"""
        step = -1 if self._hist_pos > 0 and self.current_id == self._history[min(self._hist_pos + 1, len(self._history) - 1)] else 1
        while 0 <= self._hist_pos < len(self._history):
            eid = self._history[self._hist_pos]
            if any(x["id"] == eid for x in self.entries):
                self.open_entry(eid, record=False)
                return
            # 该词条已被删除，继续朝同方向找
            nxt = self._hist_pos + step
            if not (0 <= nxt < len(self._history)):
                break
            self._hist_pos = nxt
        self._update_nav()

    def relations_for(self, entry: dict) -> dict:
        """同音（含近音）自动合并；同形、同源只看人工填写。"""
        custom = entry.get("relations") or {}
        by_head = getattr(self, "_by_head", None)
        if by_head is None:
            self._by_head = {e["headword"]: e for e in self.entries}
            by_head = self._by_head

        # 同音：优先用手工/已存的值，没有就自动算（同音+近音合并）
        names = custom.get("homophones") or []
        if not names:
            names = sound_relatives(entry, self.entries)

        shape = custom.get("same_radical") or []

        return {
            "homophones": [by_head[n] for n in names if n in by_head],
            "near": [],
            "same_radical": [by_head[n] for n in shape if n in by_head],
            "contains": [by_head[n] for n in (custom.get("contains") or [])
                          if n in by_head],
        }

    def _apply_entry_html(self, entry: dict, html: str):
        """放入 HTML，并把用到的图片作为资源交给文档（不依赖 file://）。"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QImage, QTextDocument

        self.browser.setHtml(html)
        names = [im.get("file", "") for im in entry.get("images") or []]
        for sense in entry.get("senses") or []:
            names += [im.get("file", "") for im in sense.get("images") or []]
        doc = self.browser.document()
        for name in names:
            path = rw.image_path(name)
            if path is None:
                continue
            img = QImage(str(path))
            if img.isNull():
                continue
            doc.addResource(QTextDocument.ResourceType.ImageResource,
                            QUrl(rw.image_src(name)), img)
        doc.markContentsDirty(0, max(1, doc.characterCount()))

    def show_welcome(self):
        senses = sum(len(e.get("senses") or []) for e in self.entries)
        self.browser.setHtml(rw.welcome_html(len(self.entries), senses, self.index.edges))

    def on_anchor(self, url: QUrl):
        if url.scheme() != "app":
            return
        host = url.host()
        target = unquote(url.path().lstrip("/"))
        if host == "w":
            self.open_entry(target)
        elif host == "new":
            self.new_entry(prefill=target)
        elif host == "act":
            if target == "del":
                self.delete_current()
            elif target == "copy":
                self.copy_current()
            elif target == "new":
                self.new_entry()
            elif target == "edit":
                self.edit_current()

    # ---------------------------------------------------------------- 词条操作
    def new_entry(self, prefill: str = ""):
        dlg = EntryEditor(self, prefill=prefill,
                          existing={e["headword"] for e in self.entries})
        if dlg.exec() == QDialog.DialogCode.Accepted:
            entry = dlg.result_entry
            if not entry:
                return
            self.entries.append(entry)
            self._commit()
            self.open_entry(entry["id"])

    def edit_current(self):
        entry = next((x for x in self.entries if x["id"] == self.current_id), None)
        if not entry:
            QMessageBox.information(self, "没有选中", "先在左侧选一个词条。")
            return
        dlg = EntryEditor(self, entry=entry,
                          existing={e["headword"] for e in self.entries})
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dlg.result_entry
        if not updated:
            return
        self.entries = [updated if x["id"] == entry["id"] else x for x in self.entries]
        self._commit()
        self.open_entry(updated["id"])
        self.statusBar().showMessage(f"已保存「{updated['headword']}」", 3000)

    def bulk_add(self):
        dlg = BulkAddDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        terms = dlg.terms()
        if not terms:
            return
        existing = {e["headword"] for e in self.entries}
        added, skipped = [], []
        for t in terms:
            if t in existing:
                skipped.append(t)
                continue
            e = dm.normalize_entry({"headword": t, "tags": ["待补"]})
            if e:
                self.entries.append(e)
                added.append(e)
                existing.add(t)
        if not added:
            QMessageBox.information(self, "没有新增", f"{len(skipped)} 个都已在词库里。")
            return
        self._commit()
        hits, src = self._hits_for({e["id"] for e in added})
        names = "、".join(e["headword"] for e in added[:14]) + (" …" if len(added) > 14 else "")
        msg = f"新增 {len(added)} 个：{names}"
        if skipped:
            msg += f"\n已在词库、跳过 {len(skipped)} 个。"
        if hits:
            msg += f"\n\n其中 {hits} 处已经在现有例句里变成可点链接（涉及 {src} 条词条）——现在就能点着走。"
        else:
            msg += "\n\n这些字还没出现在任何例句里，但已进词库；等你写例句时会自动可点。"
        QMessageBox.information(self, "加好了", msg)

    def toggle_strict(self, on: bool):
        """严格模式：库外的词一律不可点。"""
        dm.Index.default_auto_new = not on
        self._commit()
        tip = "严格模式：只有词库里的字可点" if on else "普通模式：未收录的英文词也能点了建条"
        self.statusBar().showMessage(tip, 4000)

    def auto_collect_chars(self):
        """扫全库例句，把出现过的汉字补习进词库（跳过已在库里的）。"""
        have = {e["headword"] for e in self.entries}
        found: list[str] = []
        seen: set[str] = set()
        for e in self.entries:
            for s in e.get("senses") or []:
                for x in s.get("examples") or []:
                    for ch in x.get("text", ""):
                        if dm.has_cjk(ch) and ch not in have and ch not in seen:
                            seen.add(ch)
                            found.append(ch)
        if not found:
            QMessageBox.information(self, "没有新字", "例句里的汉字都已经在词库里了。")
            return
        if QMessageBox.question(
            self, "自动收词",
            f"例句里还有 {len(found)} 个汉字不在词库：\n\n{'  '.join(found[:40])}"
            + ("  …" if len(found) > 40 else "")
            + "\n\n把它们都加入词库？加入后这些字立刻可点。"
        ) != QMessageBox.StandardButton.Yes:
            return
        added = []
        for ch in found:
            e = dm.normalize_entry({"headword": ch, "tags": ["待补"]})
            if e:
                self.entries.append(e)
                added.append(e)
        self._commit()
        self.statusBar().showMessage(f"已收录 {len(added)} 个字，例句里已经可点", 5000)

    def delete_current(self):
        entry = next((x for x in self.entries if x["id"] == self.current_id), None)
        if not entry:
            QMessageBox.information(self, "没有选中", "先在左侧选一个词条。")
            return
        if QMessageBox.question(self, "删除词条",
                                f"删除「{entry['headword']}」？此操作不可撤销。") \
                != QMessageBox.StandardButton.Yes:
            return
        self.entries = [x for x in self.entries if x["id"] != entry["id"]]
        self.current_id = None
        self._history = [h for h in self._history if h != entry["id"]]
        self._hist_pos = min(self._hist_pos, len(self._history) - 1)
        self._update_nav()
        self._commit()

    def copy_current(self):
        entry = next((x for x in self.entries if x["id"] == self.current_id), None)
        if not entry:
            return
        QApplication.clipboard().setText(json.dumps(entry, ensure_ascii=False, indent=2))
        self.statusBar().showMessage("已复制该词条 JSON", 2500)

    # ---------------------------------------------------------------- 导入导出
    def import_dialog(self, json_only: bool = False):
        filters = "JSON 文件 (*.json)" if json_only else "词条文件 (*.csv *.json);;CSV 文件 (*.csv);;JSON 文件 (*.json)"
        path, _ = QFileDialog.getOpenFileName(self, "导入词条", str(APP_DIR), filters)
        if path:
            self.import_file(path)

    def import_file(self, path: str):
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except OSError as exc:
            QMessageBox.critical(self, "打不开文件", str(exc))
            return
        errors: list[str] = []
        if path.lower().endswith(".json"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                QMessageBox.critical(self, "JSON 解析失败", str(exc))
                return
            arr = data if isinstance(data, list) else data.get("entries", [])
            items = [dm.normalize_entry(x) for x in arr]
        else:
            items, errors = dm.entries_from_csv(text)
        items = [x for x in items if x]
        if not items:
            QMessageBox.warning(self, "没有可用词条",
                                "文件里没读到有效词条。\n" + "\n".join(errors[:6]))
            return
        mode = self._ask_mode(len(items))
        if not mode:
            return
        self.entries = dm.merge(self.entries, items, mode)
        self._commit()
        keys = {dm.entry_key(x) for x in items}
        new_ids = {e["id"] for e in self.entries if dm.entry_key(e) in keys}
        hits, src = self._hits_for(new_ids)
        msg = f"导入 {len(items)} 条，词库现有 {len(self.entries)} 条。"
        if hits:
            msg += f"\n\n其中 {hits} 处已经在现有例句里变成可点链接（涉及 {src} 条词条）。"
        if errors:
            msg += "\n\n提示：\n" + "\n".join(errors[:8])
        QMessageBox.information(self, "导入完成", msg)

    def _ask_mode(self, count: int) -> str | None:
        box = QMessageBox(self)
        box.setWindowTitle("导入方式")
        box.setText(f"读到 {count} 条词条，怎么合并？")
        b_upsert = box.addButton("合并（同名覆盖）", QMessageBox.ButtonRole.AcceptRole)
        b_append = box.addButton("追加", QMessageBox.ButtonRole.ActionRole)
        b_replace = box.addButton("覆盖全部", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_upsert:
            return "upsert"
        if clicked is b_append:
            return "append"
        if clicked is b_replace:
            return "replace"
        return None

    def export_json(self):
        if not self.entries:
            QMessageBox.information(self, "词库为空", "先导入或新建词条。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 JSON", str(APP_DIR / "words.json"),
                                              "JSON 文件 (*.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(self.entries, ensure_ascii=False, indent=2), encoding="utf-8")
        self.statusBar().showMessage(f"已导出 {len(self.entries)} 条到 {path}", 4000)

    def export_csv(self):
        if not self.entries:
            QMessageBox.information(self, "词库为空", "先导入或新建词条。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", str(APP_DIR / "words.csv"),
                                              "CSV 文件 (*.csv)")
        if not path:
            return
        Path(path).write_text(dm.entries_to_csv(self.entries), encoding="utf-8-sig")
        self.statusBar().showMessage(f"已导出 CSV 到 {path}", 4000)

    def show_image_info(self):
        """图片诊断：哪里找、读不读得出来、支持哪些格式。"""
        from PySide6.QtGui import QImage, QImageReader

        lines = [f"图片来源：{IMG_SOURCE}", ""]
        lines.append("搜索目录：")
        for i, root in enumerate(rw.IMAGE_ROOTS, 1):
            files = list(Path(root).glob("*.jpg")) if Path(root).is_dir() else []
            lines.append(f"  {i}. {root}")
            lines.append(f"     图片 {len(files)} 张")

        sample = None
        for root in rw.IMAGE_ROOTS:
            for f in sorted(Path(root).glob("*.jpg"))[:1]:
                sample = f
                break
            if sample:
                break
        if sample:
            url = rw.image_url(sample.name)
            img = QImage(str(sample))
            lines += [
                "",
                f"抽样文件：{sample.name}",
                f"解析地址：{url or '（空）'}",
                f"文件大小：{sample.stat().st_size // 1024} KB",
                f"解码结果：{'成功 ' + str(img.width()) + '×' + str(img.height()) if not img.isNull() else '失败'}",
            ]
        else:
            lines.append("\n没找到任何 jpg 图片")

        # 关键一步：模拟正文里 <img src="file://..."> 能否真的加载
        if sample:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QTextDocument
            doc = QTextDocument()
            doc.setHtml(f'<img src=""{rw.image_url(sample.name)}"">')
            res = doc.resource(QTextDocument.ResourceType.ImageResource, QUrl(rw.image_url(sample.name)))
            if res is not None and not res.isNull():
                lines.append(f"页面加载测试：成功 {res.width()}×{res.height()}")
            else:
                lines.append("页面加载测试：失败（正文拿不到这张图）")

        fmts = [bytes(x).decode() for x in QImageReader.supportedImageFormats()]
        lines += ["", "Qt 支持的图片格式：" + "、".join(sorted(fmts))]
        QMessageBox.information(self, "图片诊断", "\n".join(lines))

    def show_data_info(self):
        """摊开数据位置与条数，便于核对包装得对不对。"""
        def count_jpg(d: Path) -> int:
            if not d or not Path(d).is_dir():
                return 0
            return len(list(Path(d).glob("*.jpg"))) + len(list(Path(d).glob("*.png")))

        lines = [
            f"程序模式：{'打包版' if _is_frozen() else '源码运行'}",
            f"随包数据：{BUNDLE_DATA or '（无）'}",
            f"用户数据：{DATA_DIR}",
            f"词库文件：{WORDS_PATH}",
            f"词库条数：{len(self.entries)}",
            f"用户图片：{count_jpg(IMAGES_DIR)} 张",
            f"随包图片：{count_jpg(BUNDLE_DATA / 'images') if BUNDLE_DATA else 0} 张",
            "",
            "词库条数应为 4425。若明显偏少，说明读到的是旧数据：",
            "删掉「用户数据」里的 words.json 再重启，程序会重新从随包数据复制。",
        ]
        QMessageBox.information(self, "数据信息", "\n".join(lines))

    def open_data_dir(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR)))

    # ---------------------------------------------------------------- 杂项
    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _open_first(self):
        if self.listw.count():
            self.listw.setCurrentRow(0)

    # ---------------------------------------------------------------- 字号
    def bump_font(self, step: float):
        """在当前增量上加减，范围 -4 ~ +10pt。"""
        self.set_font_delta(dm_factor(rw.get_font_delta() + step))

    def set_font_delta(self, delta: float):
        """设置全局字号增量：所有位置的字号同步变化（原大小 + delta）。"""
        self._font_delta = dm_factor(delta)
        rw.set_font_delta(self._font_delta)
        self._apply_ui_font()
        self._save_font_delta()
        self._rerender() if self.current_id else self.show_welcome()
        self.statusBar().showMessage(
            f"字号 {self._font_delta:+.1f}pt　正文 {rw.fs('def')}　例句 {rw.fs('ex')}　列表 {rw.pt('list'):g}pt",
            4000,
        )

    def _apply_ui_font(self):
        """把增量应用到界面外壳：菜单、搜索框、列表、状态栏。"""
        self.setStyleSheet(build_qss())
        self.listw.setItemDelegate(WordDelegate(self.listw))   # 触发重新算行高
        self.listw.doItemsLayout()
        self.listw.viewport().update()

    def apply_image_menu(self, data):
        """右键菜单回调：数字是宽度，-1 走自定义输入。"""
        if data == -1:
            cur = self._image_width or 420
            val, ok_pressed = QInputDialog.getInt(
                self, "自定义图片大小", "宽度（像素，0 = 原始尺寸）：",
                cur, 0, 4000, 20)
            if not ok_pressed:
                return
            self.set_image_width(val)
        elif isinstance(data, int):
            self.set_image_width(data)

    def set_image_width(self, px: int):
        """设置图片在页面里的显示宽度（0 = 原图）。"""
        self._image_width = max(0, int(px))
        rw.set_image_width(self._image_width)
        self._save_setting("image_width", self._image_width)
        self._rerender() if self.current_id else self.show_welcome()
        self.statusBar().showMessage(
            f"图片宽度 {'原始' if self._image_width == 0 else str(self._image_width) + 'px'}", 3000)

    def reset_zoom(self):
        """回到默认字号。"""
        self.set_font_delta(0)

    def _settings_path(self) -> pathlib.Path:
        return WORDS_PATH.parent / "settings.json"

    def _load_settings_file(self) -> dict:
        try:
            return json.loads(self._settings_path().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _load_setting(self, key: str, default):
        val = self._load_settings_file().get(key, default)
        return val if isinstance(val, type(default)) or val == 0 else default

    def _save_setting(self, key: str, value):
        cfg = self._load_settings_file()
        cfg[key] = value
        try:
            self._settings_path().write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _save_font_delta(self):
        self._save_setting("font_delta", self._font_delta)

    def _load_font_delta(self) -> float:
        try:
            cfg = WORDS_PATH.parent / "settings.json"
            if cfg.exists():
                return dm_factor(json.loads(cfg.read_text(encoding="utf-8")).get("font_delta", 0))
        except (OSError, json.JSONDecodeError):
            pass
        return 0.0

    def about(self):
        QMessageBox.about(
            self, "词典",
            "<b>本地词典</b><br><br>"
            "词库：<code>data/words.json</code><br>"
            "快捷键：<b>/</b> 搜索　<b>Ctrl+N</b> 新建　<b>Ctrl+B</b> 批量加字　"
            "<b>Ctrl+E</b> 编辑　<b>Ctrl+=</b> 放大　<b>Esc</b> 清空搜索<br><br>"
            "联想：例句里带下划线的词可以直接点，未收录的英文词点一下就能建条。",
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith((".csv", ".json")):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".csv", ".json")):
                self.import_file(path)
                return
        super().dropEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.search.clear()
            return
        super().keyPressEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("词典")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(QSS)
    verify_images()               # 实测一次正文能否显示图片，不行就换目录
    win = DictWindow()
    win.show()
    return app.exec()


def print_data_info() -> int:
    """打包后排查用：不开窗口，只报告数据落在哪、读到多少条。"""
    entries = dm.load_entries(WORDS_PATH) if WORDS_PATH.exists() else []
    img_user = len(list(IMAGES_DIR.glob("*.jpg"))) if IMAGES_DIR.is_dir() else 0
    img_bundle = 0
    if BUNDLE_DATA and (BUNDLE_DATA / "images").is_dir():
        img_bundle = len(list((BUNDLE_DATA / "images").glob("*.jpg")))
    print("FROZEN", _is_frozen())
    print("BUNDLE", BUNDLE_DATA)
    print("DATA", DATA_DIR)
    print("WORDS", WORDS_PATH)
    print("COUNT", len(entries))
    print("IMG_USER", img_user)
    print("IMG_BUNDLE", img_bundle)
    print("IMG_OK", bool(rw.image_url("ppt-00002-1.jpg")))
    print("COPY_ERROR", COPY_ERROR or "none")
    for line in DIR_ATTEMPTS:
        print("DIR", line)
    for e in DIR_ERRORS:
        print("ERR", e)
    return 0


if __name__ == "__main__":
    _probe = os.environ.get("DICT_DATA_INFO")
    if _probe:
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_data_info()
        text = buf.getvalue()
        if _probe not in ("1", "true", "yes"):
            try:
                Path(_probe).write_text(text, encoding="utf-8")
            except Exception as exc:
                try:
                    Path(str(_probe) + ".err").write_text(repr(exc), encoding="utf-8")
                except Exception:
                    pass
        else:
            sys.stdout.write(text)
        sys.exit(0)
    sys.exit(main())

