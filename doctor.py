"""自检工具：确认你运行的是哪份代码，以及字号系统是否正常。

用法：  python doctor.py
"""
import os
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))

print("=" * 56)
print("词典 · 自检")
print("=" * 56)

print("\n[1] 文件位置")
for f in ["app.py", "dictionary_render.py", "dictionary_model.py", "data/words.json"]:
    p = BASE / f
    if p.exists():
        st = p.stat()
        print(f"  ✓ {f:24} {st.st_size:>7} 字节  修改于 {__import__('time').strftime('%m-%d %H:%M:%S', __import__('time').localtime(st.st_mtime))}")
    else:
        print(f"  ✗ {f:24} 不存在")

print("\n[2] 代码版本特征")
app_src = (BASE / "app.py").read_text(encoding="utf-8")
ren_src = (BASE / "dictionary_render.py").read_text(encoding="utf-8")
checks = [
    ("字号系统 BASE_SIZES", "BASE_SIZES" in ren_src),
    ("fs() 字号函数", "def fs(" in ren_src),
    ("快捷键多套注册 setShortcuts", "setShortcuts" in app_src),
    ("已移除 zoomIn/zoomOut", "zoomIn" not in app_src and "zoomOut" not in app_src),
    ("步长 1pt", "bump_font(+1.0)" in app_src),
]
for name, good in checks:
    print(f"  {'✓' if good else '✗'} {name}")

left = re.findall(r"font-size:(\d+(?:\.\d+)?)pt", ren_src)
print(f"  {'✓' if not left else '✗'} 无硬编码字号" + (f"（残留 {left}）" if left else ""))

print("\n[3] 字号系统实测")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

import dictionary_render as rw

qa = QApplication([])
rw.set_font_delta(0)
print(f"  默认：词目 {rw.fs('hw')} / 释义 {rw.fs('def')} / 例句 {rw.fs('ex')} / 标签 {rw.fs('label')}")
rw.set_font_delta(3)
print(f"  +3pt：词目 {rw.fs('hw')} / 释义 {rw.fs('def')} / 例句 {rw.fs('ex')} / 标签 {rw.fs('label')}")
rw.set_font_delta(0)

print("\n[4] 正在运行的词典进程")
import subprocess

out = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | "
     "Select-Object ProcessId,CommandLine | Format-List"],
    capture_output=True, text=True, encoding="utf-8", errors="ignore",
).stdout.strip()
if not out:
    print("  没有正在运行的进程")
else:
    for line in out.splitlines():
        if line.strip():
            print("  " + line.strip())

print("\n[5] 设置文件")
cfg = BASE / "data" / "settings.json"
print("  " + (cfg.read_text(encoding="utf-8").strip() if cfg.exists() else "（无，默认 0）"))

print("\n" + "=" * 56)
print("如果 [2] 全是 ✓ 但仍看不到变化：")
print("  1) 关掉所有旧窗口（上面 [4] 列出的进程）")
print("  2) 重新启动 launch.bat 或 python app.py")
print("  3) 打开「视图」菜单，应看到『放大正文 / 缩小正文 / 重置字号』")
print("     如果看到的是『放大 / 缩小』，说明你开的是旧代码")
print("=" * 56)
