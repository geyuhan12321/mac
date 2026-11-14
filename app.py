

from __future__ import annotations

import json
import re
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
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QStyledItemDelegate, QStyle, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
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


def dm_factor(delta: float) -> float:
    """把增量夹到 -4 ~ +10 之间，并按 0.5 对齐。"""
    d = max(-4.0, min(10.0, float(delta)))
    return round(d * 2) / 2


def _pick_data_dir() -> Path:
    """优先用脚本旁边的 data/（Windows 绿色版）。

    打成 macOS .app 后脚本在只读的 bundle 里，写不进去，
    这时退到 ~/Library/Application Support/词典/data。
    """
    beside = APP_DIR / "data"
    try:
        beside.mkdir(parents=True, exist_ok=True)
        probe = beside / ".writable"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return beside
    except OSError:
        fallback = Path.home() / "Library" / "Application Support" / "词典" / "data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


DATA_DIR = _pick_data_dir()
WORDS_PATH = DATA_DIR / "words.json"
IMAGES_DIR = DATA_DIR / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
rw.set_image_root(IMAGES_DIR)

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


class PasteLineEdit(QLineEdit):
    """普通输入框，但 Ctrl+V 粘贴的是图片时不当文本处理。"""

    imagePasted = Signal()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            if not QApplication.clipboard().image().isNull():
                self.imagePasted.emit()
                return
        super().keyPressEvent(event)


class PasteTextEdit(QPlainTextEdit):
    """多行输入框，同样支持粘贴图片。"""

    imagePasted = Signal()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            if not QApplication.clipboard().image().isNull():
                self.imagePasted.emit()
                return
        super().keyPressEvent(event)


class EntryEditor(QDialog):
    """与词条页同版式的编辑器：71/29 双栏、同样的字号层级与细线位置。

    左边是正文（词目、读音、词形、汉字信息、义项、短语、词源），
    右边是侧栏（词频、词形汇总、分类、图片）。每个字段都是输入框，
    样式做成「下划虚线 / 细框」，填了内容也能看出是什么。
    """

    def __init__(self, parent=None, entry: dict | None = None, prefill: str = ""):
        super().__init__(parent)
        self.entry = entry
        self._images: list[dict] = []      # 词条级图片（由字段粘贴收集）
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
        cols.addWidget(left, 71)

        right = QWidget()
        self.side = QVBoxLayout(right)
        self.side.setContentsMargins(0, 0, 0, 0)
        self.side.setSpacing(0)
        cols.addWidget(right, 29)

        senses_val = (entry or {}).get("senses") or [{}]
        pron = (entry or {}).get("pronunciation") or {}
        char = (entry or {}).get("character") or {}

        # ======================================================= 左栏：词目
        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        self.f_head = self._line("词条", entry["headword"] if entry else prefill, "Headline")
        self.f_head.textChanged.connect(self._sync_lang)
        self.lang_hint = QLabel("中文")
        self.lang_hint.setObjectName("EditorHint")
        self.lang_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        head_row.addWidget(self._wrap(self.f_head), 1)
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

        # 词形
        self.form.addWidget(self._cap("词形变化（可选，逗号分隔）"))
        self.f_forms = self._line("runs, running, ran",
                                  "，".join(f.get("value", "") for f in (entry or {}).get("wordForms") or []))
        self.form.addWidget(self._wrap(self.f_forms))

        # 汉字信息（三格，与词条页同样的浅框）
        self.char_row_widget = QWidget()
        self.char_row_widget.setObjectName("CharBar")
        char_row = QHBoxLayout(self.char_row_widget)
        char_row.setContentsMargins(0, 0, 0, 0)
        char_row.setSpacing(1)
        self.f_radical = self._line("足", char.get("radical", ""), "CharField")
        self.f_strokes = self._line("12", char.get("strokes", ""), "CharField")
        self.f_trad = self._line("跑", char.get("traditional", ""), "CharField")
        for cap, w in (("部首", self.f_radical), ("笔画", self.f_strokes), ("繁体", self.f_trad)):
            cell = QWidget()
            cell.setObjectName("CharCell")
            v = QVBoxLayout(cell)
            v.setContentsMargins(10, 6, 10, 6)
            v.setSpacing(0)
            v.addWidget(self._cap(cap))
            v.addWidget(w)
            char_row.addWidget(self._wrap(cell))
        self.form.addSpacing(10)
        self.form.addWidget(self.char_row_widget)

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
        self.f_etym = self._line("如：形声字，从足包声", (entry or {}).get("etymology", ""))
        self.form.addWidget(self._wrap(self.f_etym))
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

        self.side.addWidget(self._section("词形变化"))
        self.forms_hint = QLabel("（在左侧填写）")
        self.forms_hint.setObjectName("EditorHint")
        self.forms_hint.setWordWrap(True)
        self.side.addWidget(self.forms_hint)
        self.f_forms.textChanged.connect(self._sync_forms)

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

    def _area(self, placeholder: str, value: str = "", height: int = 60) -> QPlainTextEdit:
        w = PasteTextEdit(value or "")
        w.setPlaceholderText(placeholder)
        w.setObjectName("EditorArea")
        w.setFixedHeight(height)
        w._img_list = []
        w.imagePasted.connect(lambda w=w: self._paste_into(w))
        return w

    # ---------------------------------------------------------------- 粘贴图片
    def _paste_into(self, field):
        """输入框里粘贴图片：存盘，并在该框下方摆缩略图。"""
        img = QApplication.clipboard().image()
        if img.isNull():
            return
        name = self._save_pixmap(QPixmap.fromImage(img))
        if not name:
            QMessageBox.warning(self, "保存失败", "图片没能写入 data/images。")
            return
        field._img_list.append({"file": name, "caption": ""})
        self._refresh_field_thumbs(field)

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
            pix = QPixmap(str(IMAGES_DIR / im["file"]))
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

    # ---------------------------------------------------------------- 联动
    def _sync_lang(self):
        zh = dm.has_cjk(self.f_head.text())
        self.lang_hint.setText("中文" if zh else "ENGLISH")
        self.char_row_widget.setVisible(zh)

    def _sync_freq(self):
        level = self.f_freq.value()
        dots = "".join("■" if i < level else "□" for i in range(5))
        self.freq_dots.setText(dots)

    def _sync_forms(self):
        vals = [v.strip() for v in self.f_forms.text().replace("，", ",").split(",") if v.strip()]
        self.forms_hint.setText("\n".join(vals) if vals else "（在左侧填写）")

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
        f_def = self._area("柯林斯式整句释义最佳", data.get("definition", ""), 62)
        f_zh = self._line("可选", data.get("definitionZh", ""), "EditorField")
        ex = (data.get("examples") or [{}])[0]
        f_ex = self._area("可选；写进去以后句中的词也能点", ex.get("text", ""), 54)
        f_extr = self._line("可选", ex.get("translation", ""), "EditorField")
        f_meta = self._line("用 | 分隔",
                            "|".join((data.get("synonyms") or []) + (data.get("collocations") or [])))
        for cap, w in (("词性", f_pos), ("释义", f_def), ("译文", f_zh),
                       ("例句", f_ex), ("例句翻译", f_extr), ("近义 / 搭配 / 标注", f_meta)):
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
            "widget": row, "num": num, "pos": f_pos, "def": f_def, "zh": f_zh,
            "ex": f_ex, "extr": f_extr, "meta": f_meta,
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

        # 词条级图片：来自左栏/侧栏那些字段
        entry_fields = [self.f_head, self.f_pron, self.f_forms,
                        self.f_phrases, self.f_etym, self.f_tags,
                        self.f_radical, self.f_strokes, self.f_trad]
        entry_imgs = []
        for f in entry_fields:
            entry_imgs.extend(getattr(f, "_img_list", []) or [])
        entry_imgs.extend(self._images)

        senses = []
        for r in self._sense_rows:
            definition = r["def"].toPlainText().strip()
            if not definition:
                continue
            example = r["ex"].toPlainText().strip()
            senses.append({
                "pos": r["pos"].text().strip(),
                "definition": definition,
                "definitionZh": r["zh"].text().strip(),
                "images": (r.get("images") or []) + [
                    im for f in (r["pos"], r["def"], r["zh"], r["ex"], r["extr"], r["meta"])
                    for im in (getattr(f, "_img_list", []) or [])
                ],
                "examples": ([{"text": example, "translation": r["extr"].text().strip()}]
                             if example else []),
                "synonyms": [x.strip() for x in r["meta"].text().split("|") if x.strip()],
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
            "wordForms": [{"label": "词形", "value": v.strip()}
                          for v in self.f_forms.text().replace("，", ",").split(",") if v.strip()],
            "senses": senses,
            "phrases": phrases,
            "etymology": self.f_etym.text().strip(),
            "images": entry_imgs,
            "tags": [t.strip() for t in self.f_tags.text().replace(",", "、").split("、") if t.strip()],
        }
        if zh:
            raw["character"] = {
                "radical": self.f_radical.text().strip(),
                "strokes": self.f_strokes.text().strip(),
                "traditional": self.f_trad.text().strip(),
            }
        if self.entry:
            raw["id"] = self.entry["id"]
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

        m_tool = bar.addMenu("工具(&T)")
        # 批量加字已在「词条」菜单里（Ctrl+B），这里不重复注册，否则快捷键会冲突
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
    def _persist(self):
        dm.save_entries(WORDS_PATH, self.entries)
        self.index = dm.Index(self.entries, auto_new=dm.Index.default_auto_new)

    def _commit(self):
        """写盘 → 重建索引 → 刷新列表 → 重画当前词条：新词立刻在句子里可点。"""
        self._persist()
        self.refresh_list()
        self._rerender()

    def _rerender(self):
        entry = next((x for x in self.entries if x["id"] == self.current_id), None)
        if not entry:
            self.show_welcome()
            return
        pos = self.browser.verticalScrollBar().value()
        backs = [x for x in self.entries if x["id"] in (self.index.inbound.get(entry["id"]) or [])]
        self.browser.setHtml(rw.entry_html(entry, self.index, backs, self._occurrences(entry)))
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
                    " ".join(e.get("tags") or []),
                ] + [s.get("definition", "") + " " + s.get("definitionZh", "")
                     + " " + " ".join(x.get("text", "") for x in s.get("examples") or [])
                     for s in e.get("senses") or []]).lower()
                if q not in hay:
                    continue
            out.append(e)
        # 不排序：保持导入时的页序（PPT 本身按拼音排好了）
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
        self.browser.setHtml(rw.entry_html(entry, self.index, backs, self._occurrences(entry)))
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
        dlg = EntryEditor(self, prefill=prefill)
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
        dlg = EntryEditor(self, entry=entry)
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

    def reset_zoom(self):
        """回到默认字号。"""
        self.set_font_delta(0)

    def _save_font_delta(self):
        try:
            cfg = WORDS_PATH.parent / "settings.json"
            cfg.write_text(json.dumps({"font_delta": self._font_delta}), encoding="utf-8")
        except OSError:
            pass

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
    win = DictWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

