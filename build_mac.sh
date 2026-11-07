#!/usr/bin/env bash
# =============================================================
# 词典 · macOS 打包脚本
# 在 macOS 上运行（Windows / Linux 无法交叉编译出 .app）
#   用法：  ./build_mac.sh            打 .app（未签名，可本地双击）
#           ./build_mac.sh --dmg      额外产出 .dmg 安装包
#           ./build_mac.sh --sign "Developer ID Application: 你的名字 (TEAMID)"
# =============================================================
set -euo pipefail

APP_NAME="词典"
BUNDLE_ID="local.dict.desktop"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

DO_DMG=0
SIGN_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dmg)  DO_DMG=1; shift ;;
    --sign) SIGN_ID="${2:-}"; shift 2 ;;
    *) echo "未知参数：$1"; exit 1 ;;
  esac
done

echo "==> 1/6 检查环境"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "错误：必须在 macOS 上执行（当前 $(uname -s)）。Qt 应用无法交叉编译。"
  exit 1
fi
PY="$(command -v python3 || true)"
[[ -z "$PY" ]] && { echo "错误：找不到 python3。建议 brew install python@3.12"; exit 1; }
echo "    python: $($PY -V)  @ $PY"
echo "    架构: $(uname -m)"

echo "==> 2/6 建虚拟环境并装依赖"
[[ -d .venv-build ]] || "$PY" -m venv .venv-build
# shellcheck disable=SC1091
source .venv-build/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install "PySide6-Essentials>=6.6" pyinstaller
echo "    PySide6: $(python -c 'import PySide6;print(PySide6.__version__)')"
echo "    PyInstaller: $(python -m PyInstaller --version)"

echo "==> 3/6 清理旧的构建产物"
rm -rf build dist "$APP_NAME.spec"

echo "==> 4/6 PyInstaller 打包"
# --windowed：生成 .app（不弹终端）
# --osx-bundle-identifier：macOS 识别用
# --add-data：把示例与模板塞进包内（冒号分隔，mac 用冒号不是分号）
python -m PyInstaller \
  --noconfirm \
  --windowed \
  --clean \
  --name "$APP_NAME" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --exclude-module PySide6.QtWebEngineCore \
  --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.Qt3DCore \
  --exclude-module PySide6.QtMultimedia \
  --exclude-module tkinter \
  app.py

APP_PATH="dist/$APP_NAME.app"
[[ -d "$APP_PATH" ]] || { echo "错误：没有生成 $APP_PATH"; exit 1; }

echo "==> 5/6 修正 Info.plist 与首启目录"
PLIST="$APP_PATH/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName $APP_NAME" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 11.0" "$PLIST" 2>/dev/null || true
# 中文名在中文系统外显示会乱，补一个英文显示名
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string $APP_NAME" "$PLIST" 2>/dev/null || true

if [[ -n "$SIGN_ID" ]]; then
  echo "    签名：$SIGN_ID"
  codesign --force --deep --timestamp --options runtime \
    --sign "$SIGN_ID" "$APP_PATH"
  codesign --verify --deep --strict --verbose=2 "$APP_PATH"
else
  echo "    跳过签名（本地可用；分发给别人需要签名 + 公证）"
  codesign --force --deep --sign - "$APP_PATH" 2>/dev/null || true
fi

if [[ $DO_DMG -eq 1 ]]; then
  echo "==> 6/6 生成 DMG"
  rm -f "dist/$APP_NAME.dmg"
  hdiutil create -volname "$APP_NAME" -srcfolder "$APP_PATH" \
    -ov -format UDZO "dist/$APP_NAME.dmg"
  [[ -n "$SIGN_ID" ]] && codesign --force --sign "$SIGN_ID" "dist/$APP_NAME.dmg"
  echo "    产物：dist/$APP_NAME.dmg"
else
  echo "==> 6/6 跳过 DMG（加 --dmg 可生成）"
fi

SIZE=$(du -sh "$APP_PATH" | cut -f1)
echo
echo "完成：$APP_PATH（$SIZE）"
echo "双击即可运行；数据文件在 ~/Library/Application Support/词典/data/words.json"
echo "首次打开若被 Gatekeeper 拦下：右键 → 打开，或执行"
echo "  xattr -dr com.apple.quarantine \"$APP_PATH\""
