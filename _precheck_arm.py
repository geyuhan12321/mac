"""导入期校验：确保 arm64 流水线不会因为代码问题白跑一遍。"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
BASE = r"C:\Users\ge\Downloads\collins-dict-desktop"
sys.path.insert(0, BASE)

import ast
import pathlib

import yaml

fail = []


def ok(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg)
    if not cond:
        fail.append(msg)


base = pathlib.Path(BASE)

print("[1] Python 文件语法")
for f in ["app.py", "dictionary_model.py", "dictionary_render.py", "demo_data.py"]:
    try:
        ast.parse((base / f).read_text(encoding="utf-8"), f)
        ok(True, f)
    except SyntaxError as e:
        ok(False, f"{f} 语法错误：{e}")

print("[2] 流水线只跑 arm64 原生")
wf = yaml.safe_load((base / ".github/workflows/build-mac.yml").read_text(encoding="utf-8"))
matrix = wf["jobs"]["build"]["strategy"]["matrix"]["include"]
ok(len(matrix) == 1 and matrix[0]["os"] == "macos-14", f"单架构：{matrix[0]['name']}")
ok(matrix[0]["arch"] == "arm64", "目标架构 arm64")

print("[3] 步骤齐全")
names = [s.get("name") or s.get("uses") for s in wf["jobs"]["build"]["steps"]]
for need in ["自检", "PyInstaller 打包", "冒烟启动", "打包 zip"]:
    ok(any(need in (n or "") for n in names), f"含「{need}」")

print("[4] 应用能导入并渲染")
from PySide6.QtWidgets import QApplication

import app as gui
import dictionary_model as dm
import dictionary_render as rw
from demo_data import DEMO

qa = QApplication([])
entries = [dm.normalize_entry(x) for x in DEMO]
idx = dm.Index(entries)
html = rw.entry_html(entries[0], idx, [], [])
ok(len(html) > 500, f"HTML {len(html)} 字符")
win = gui.DictWindow()
win.show()
qa.processEvents()
ok(True, "主窗口可构建")
win.close()

print("[5] 数据目录逻辑")
ok("_pick_data_dir" in (base / "app.py").read_text(encoding="utf-8"), "有可写目录回退逻辑")

print("\n==== " + ("FAIL: %d" % len(fail) if fail else "ALL PASS") + " ====")
sys.exit(1 if fail else 0)
