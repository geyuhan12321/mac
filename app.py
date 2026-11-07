

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QKeySequence, QShortcut, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
    QStyledItemDelegate, QStyle, QTextBrowser, QVBoxLayout, QWidget,
)

import dictionary_model as dm
import dictionary_render as rw
from demo_data import DEMO

APP_DIR = Path(__file__).resolve().parent


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

QSS = """
QWidget { background: #ffffff; color: #111111; font-size: 13px; }
#Header { background: #ffffff; border-bottom: 1px solid #e6e6e6; }
#Count { background: transparent; }
QLineEdit#Search {
    background: #ffffff; border: 1px solid #dcdcdc; border-radius: 4px;
    padding: 6px 10px; color: #111111;
    selection-background-color: #111111; selection-color: #ffffff;
}
QLineEdit#Search:focus { border-color: #111111; }
QPushButton#Top { background: transparent; border: none; color: #5f5f5f; padding: 6px 10px; }
QPushButton#Top:hover { color: #111111; background: #f4f4f4; border-radius: 4px; }
QListWidget#WordList { border: none; background: #ffffff; outline: none; }
QListWidget#WordList::item { border: none; }
QTextBrowser#EntryView { border: none; background: #ffffff; }
QSplitter::handle { background: #ffffff; }
QSplitter::handle:horizontal { width: 1px; background: #e6e6e6; }
QComboBox { border: none; background: #ffffff; color: #5f5f5f; padding: 3px 4px; }
QComboBox:hover { color: #111111; }
QComboBox::drop-down { border: none; width: 14px; }
QComboBox QAbstractItemView {
    border: 1px solid #e6e6e6; background: #ffffff;
    selection-background-color: #f2f2f2; selection-color: #111111;
}
QLabel#Count { color: #9a9a9a; font-size: 11px; }
QStatusBar { color: #9a9a9a; font-size: 11px; border-top: 1px solid #eeeeee; }
QMenuBar { background: #ffffff; border-bottom: 1px solid #eeeeee; }
QMenuBar::item { padding: 4px 10px; background: transparent; color: #333333; }
QMenuBar::item:selected { background: #f4f4f4; }
"""


class WordDelegate(QStyledItemDelegate):
    """列表项：半粗词目 + 灰色读音；选中/悬停只有浅灰底，不描边。"""

    def sizeHint(self, option, index):
        return QSize(180, 32)

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
        f1.setPointSizeF(10.5)
        f1.setWeight(QFont.Weight.DemiBold)
        painter.setFont(f1)
        painter.setPen(QColor("#111111"))
        painter.drawText(rect.adjusted(14, 0, -8, 0),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), head)

        if pron:
            width = QFontMetrics(f1).horizontalAdvance(head)
            f2 = QFont(option.font)
            f2.setPointSizeF(8.5)
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


class NewEntryDialog(QDialog):
    """新建 / 编辑词条。传 entry 即进入编辑模式（改首条义项，其余保留）。"""

    def __init__(self, parent=None, prefill: str = "", entry: dict | None = None):
        super().__init__(parent)
        self.entry = entry
        self.setWindowTitle("编辑词条" if entry else "新建词条")
        self.setMinimumWidth(520)
        senses = (entry or {}).get("senses") or [{}]
        first = senses[0] if senses else {}
        pron = (entry or {}).get("pronunciation") or {}
        ex = (first.get("examples") or [{}])[0] if first.get("examples") else {}

        self.word = QLineEdit(entry["headword"] if entry else prefill)
        self.pron = QLineEdit(pron.get("pinyin") or pron.get("uk") or pron.get("us") or "")
        self.pron.setPlaceholderText("pǎo    或    /rʌn/")
        self.pos = QLineEdit(first.get("pos") or "")
        self.pos.setPlaceholderText("动词 / VERB")
        self.freq = QSpinBox()
        self.freq.setRange(0, 5)
        self.freq.setValue((entry or {}).get("frequency") or 3)
        self.freq.setSpecialValueText("未设置")
        self.defn = QPlainTextEdit(first.get("definition") or "")
        self.defn.setFixedHeight(84)
        self.example = QPlainTextEdit(ex.get("text") or "")
        self.example.setFixedHeight(64)
        self.example.setPlaceholderText("可选。写进去以后，这句里的词也能继续点。")

        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("词条", self.word)
        form.addRow("拼音 / 音标", self.pron)
        form.addRow("词性", self.pos)
        form.addRow("词频", self.freq)
        form.addRow("释义", self.defn)
        form.addRow("例句", self.example)
        hint = QLabel("释义必填。保存后立刻参与联想：所有例句里出现这个词都会变成可点。")
        hint.setStyleSheet("color:#78828c;font-size:11px;background:transparent;")
        form.addRow(hint)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("保存" if entry else "保存并打开")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def accept(self):
        if not self.word.text().strip():
            QMessageBox.warning(self, "缺词条", "词条名不能为空。")
            return
        if not self.defn.toPlainText().strip():
            QMessageBox.warning(self, "缺释义", "至少写一句释义。")
            return
        super().accept()

    def build(self) -> dict | None:
        head = self.word.text().strip()
        zh = dm.has_cjk(head)
        pron = self.pron.text().strip()
        body = self.example.toPlainText().strip()
        sense = {
            "pos": self.pos.text().strip(),
            "definition": self.defn.toPlainText().strip(),
            "examples": [{"text": body}] if body else [],
        }
        if not self.entry:
            return dm.normalize_entry({
                "headword": head,
                "lang": "zh" if zh else "en",
                "frequency": self.freq.value() or None,
                "pronunciation": {"pinyin": pron} if zh else {"uk": pron},
                "senses": [sense],
            })
        # 编辑：保留其余义项、词形、部首、标签等，只改首条
        base_entry = dict(self.entry)
        senses = [dict(x) for x in (base_entry.get("senses") or [])]
        merged = dict(senses[0]) if senses else {}
        merged.update({k: v for k, v in sense.items() if v or k == "definition"})
        if not body:
            merged.pop("examples", None)
            if senses:
                merged["examples"] = senses[0].get("examples") or []
        if senses:
            senses[0] = merged
        else:
            senses = [merged]
        base_entry.update({
            "headword": head,
            "lang": "zh" if zh else "en",
            "frequency": self.freq.value() or None,
            "pronunciation": {"pinyin": pron} if zh else {"uk": pron},
            "senses": senses,
        })
        return dm.normalize_entry(base_entry)


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

        self._build_ui()
        self._build_menu()
        self.refresh_list()
        self.show_welcome()
        self.setAcceptDrops(True)
        self.listw.setFocus()

    # ---------------------------------------------------------------- UI
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
        btn_demo = QPushButton("示例")
        btn_demo.setObjectName("Top")
        btn_demo.clicked.connect(self.load_demo)

        self.search.setMaximumWidth(560)
        h.addWidget(self.search)
        h.addStretch(1)
        h.addWidget(btn_import)
        h.addWidget(btn_new)
        h.addWidget(btn_demo)

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

        self.status_label = QLabel("")
        self.statusBar().addPermanentWidget(self.status_label)

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
        self._action(m_entry, "载入示例词库", self.load_demo)

        m_view = bar.addMenu("视图(&V)")
        self._action(m_view, "放大", lambda: self.browser.zoomIn(1), "Ctrl+=")
        self._action(m_view, "缩小", lambda: self.browser.zoomOut(1), "Ctrl+-")
        self._action(m_view, "重置字号", self.reset_zoom, "Ctrl+0")
        m_view.addSeparator()
        self._action(m_view, "搜索框", self.focus_search, "Ctrl+F")
        m_view.addSeparator()
        self.strict_action = QAction("只让库里的字可点（严格模式）", self, checkable=True)
        self.strict_action.setChecked(not dm.Index.default_auto_new)
        self.strict_action.toggled.connect(self.toggle_strict)
        m_view.addAction(self.strict_action)

        m_tool = bar.addMenu("工具(&T)")
        self._action(m_tool, "批量加字…", self.bulk_add, "Ctrl+B")
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
        self._update_counts()

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

    def _update_counts(self):
        senses = sum(len(e.get("senses") or []) for e in self.entries)
        self.status_label.setText(
            f"{len(self.entries)} 条词条 · {senses} 义项 · {self.index.edges} 联想边　|　"
            f"{WORDS_PATH}"
        )

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
                hay = " ".join([
                    e["headword"],
                    (e.get("pronunciation") or {}).get("pinyin", ""),
                    (e.get("pronunciation") or {}).get("uk", ""),
                    " ".join(e.get("tags") or []),
                ] + [s.get("definition", "") + " " + s.get("definitionZh", "")
                     + " " + " ".join(x.get("text", "") for x in s.get("examples") or [])
                     for s in e.get("senses") or []]).lower()
                if q not in hay:
                    continue
            out.append(e)
        out.sort(key=lambda x: (x["headword"].lower(), x.get("homograph") or 0))
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
        self._update_counts()

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
        self.open_entry(current.data(Qt.ItemDataRole.UserRole))

    def open_entry(self, eid: str):
        entry = next((x for x in self.entries if x["id"] == eid), None)
        if not entry:
            return
        self.current_id = eid
        backs = [x for x in self.entries if x["id"] in (self.index.inbound.get(eid) or [])]
        self.browser.setHtml(rw.entry_html(entry, self.index, backs, self._occurrences(entry)))
        self.browser.verticalScrollBar().setValue(0)
        self._select_in_list(eid)
        self.statusBar().showMessage(
            f"{entry['headword']} · {len(entry.get('senses') or [])} 个义项", 3000
        )

    def show_welcome(self):
        senses = sum(len(e.get("senses") or []) for e in self.entries)
        self.browser.setHtml(rw.welcome_html(len(self.entries), senses, self.index.edges))
        self._update_counts()

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
        dlg = NewEntryDialog(self, prefill)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            entry = dlg.build()
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
        dlg = NewEntryDialog(self, entry=entry)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dlg.build()
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

    def load_demo(self):
        self.entries = dm.merge(self.entries, [dm.normalize_entry(x) for x in DEMO], "upsert")
        self._commit()
        if not self.current_id and self.entries:
            self.open_entry(self.entries[0]["id"])
        self.statusBar().showMessage("已载入 7 条示例词条（可随时删除）", 4000)

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

    def reset_zoom(self):
        self.browser.setFont(QFont("Microsoft YaHei UI", 10))
        self.browser.setHtml(self.browser.toHtml())

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

