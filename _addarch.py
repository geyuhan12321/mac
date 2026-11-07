"""确认 arm64 机器上拿到的一定是原生包：给流水线补架构断言。"""
import pathlib
import yaml

p = pathlib.Path(r"C:\Users\ge\Downloads\collins-dict-desktop\.github\workflows\build-mac.yml")
s = p.read_text(encoding="utf-8")

anchor = """      - name: 修 Info.plist"""

insert = """      - name: 校验确实打出了 arm64 原生包
        env:
          APP_NAME: ${{ vars.MAC_APP_NAME || '词典' }}
        run: |
          BIN="dist/$APP_NAME.app/Contents/MacOS/$APP_NAME"
          echo "== 主程序架构 =="
          lipo -archs "$BIN"
          lipo -archs "$BIN" | grep -qw arm64 || { echo "错误：不是 arm64 原生包"; exit 1; }

          echo "== 内嵌 Python / Qt 架构抽样 =="
          FAIL=0
          while IFS= read -r f; do
            ARCHS="$(lipo -archs "$f" 2>/dev/null || echo unknown)"
            case "$ARCHS" in
              *arm64*) ;;
              *) echo "非 arm64: $ARCHS  $f"; FAIL=1 ;;
            esac
          done < <(find "dist/$APP_NAME.app" -type f \\( -name "*.dylib" -o -name "*.so" -o -perm +111 \\) | head -400)
          [[ $FAIL -eq 0 ]] && echo "全部二进制均为 arm64" || { echo "混入了非 arm64 二进制"; exit 1; }

"""

assert anchor in s
s = s.replace(anchor, insert + anchor, 1)
p.write_text(s, encoding="utf-8")

d = yaml.safe_load(s)
steps = [x.get("name") or x.get("uses") for x in d["jobs"]["build"]["steps"]]
print("YAML ok，步骤：")
for x in steps:
    print("  -", x)
