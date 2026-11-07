# 苹果系统打包（GitHub Actions）

> **当前进度**：本地 git 仓库已初始化并提交，`.gitignore` 已排除私人词库，Windows 流水线也已就位。
> 剩下的只有 `git remote add origin … && git push -u origin main` 这一步——它需要你的 GitHub 账号。

Windows 机器打不出能双击的 macOS `.app`——PyInstaller 只能为目标平台编译原生解释器和 Qt 框架。所以用 GitHub 免费的 `macos-15` 机器（原生 Apple Silicon）构建，得到的是**真 arm64 原生包**，不是 Rosetta 转译。

工作流文件：[.github/workflows/build-mac.yml](.github/workflows/build-mac.yml)

---

## 一、准备（一次性，约 5 分钟）

### 1. 建仓库并推上去

```bash
cd collins-dict-desktop
git init
git add app.py dictionary_model.py dictionary_render.py demo_data.py requirements.txt
git add .github build_mac.sh README.md
git add data/.gitkeep        # 空词库占位，见下方说明
git commit -m "词典桌面版 + macOS 打包流水线"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

> `data/words.json` 是你的私人词库，**建议加进 `.gitignore` 不要上传**。仓库里放一个空的 `data/.gitkeep` 让目录存在即可，程序首次启动会自动建 `words.json`。

`.gitignore` 建议内容：

```
.venv-build/
build/
dist/
__pycache__/
*.spec
data/words.json
preview/
```

### 2. 触发一次

- **方式 A（推荐）**：仓库页面 → **Actions** → 左侧 `build-macos` → **Run workflow** → 勾上 `dmg` → Run。
- **方式 B**：打 tag 推送，自动出包并挂到 Release：

```bash
git tag v1.0.0
git push origin v1.0.0
```

### 3. 下载

跑完后在该次运行页面底部 **Artifacts** 里拿到两个包：

| 产物 | 适用机器 |
|---|---|
| `词典-arm64.zip` / `词典-arm64.dmg` | M 系列 Mac（M1/M2/M3/M4），原生运行 |

`.app` 约 60–80MB，整体跑一次约 4–5 分钟。

> 只出 arm64。老 Intel Mac 需要 x86_64 包时，把 `build-mac.yml` 里矩阵那段加回 `macos-13 / x86_64` 即可。

---

## 二、流水线做了什么

| 步骤 | 内容 |
|---|---|
| 装依赖 | Python 3.12 + `PySide6-Essentials` + PyInstaller（带 pip 缓存） |
| **自检** | 无界面模式跑一遍：加载示例词条、建索引、渲染 HTML，失败就不打包 |
| PyInstaller | `--windowed` 出 `.app`，排除 WebEngine/3D/Multimedia/tkinter 砍体积 |
| **架构断言** | `lipo -archs` 检查主程序与内嵌 dylib/so 全是 arm64，混进 x86 二进制就直接失败 |
| 修 Info.plist | 补 `CFBundleDisplayName`、`NSHighResolutionCapable`、最低系统 11.0 |
| 签名 | 有证书走真签名 + 公证；没有就 ad-hoc 签名 |
| **冒烟启动** | 启动 `.app` 等 6 秒，进程还活着才算通过 |
| 打包 | `ditto` 压 zip（保留符号链接与权限，关键）+ `hdiutil` 出 dmg |
| 发布 | 打 tag 时自动挂到 GitHub Release |

两个容易踩的点已经处理：

- **zip 必须用 `ditto` 不能 `zip`**，否则 `.app` 里的符号链接会被压平，解压后无法启动。
- **中文应用名**在英文系统下可能显示异常，所以额外写了 `CFBundleDisplayName`。

---

## 三、去掉「无法验证开发者」提示（可选）

未签名的包在别人 Mac 上会被 Gatekeeper 拦，第一次要右键 → 打开。想彻底消除，需要 Apple Developer 账号（$99/年）。

配好后在仓库 **Settings → Secrets and variables → Actions** 加这些 Secret：

| Secret 名 | 内容 |
|---|---|
| `MAC_SIGN_IDENTITY` | `Developer ID Application: 你的名字 (TEAMID)` |
| `MAC_CERT_P12_BASE64` | 开发者证书 `.p12` 的 base64：`base64 -i cert.p12 \| pbcopy` |
| `MAC_CERT_PASSWORD` | 导出 `.p12` 时设的密码 |
| `APPLE_ID` | Apple ID 邮箱 |
| `APPLE_TEAM_ID` | 10 位 Team ID |
| `APPLE_APP_PASSWORD` | appleid.apple.com 生成的 App 专用密码 |

六个都填了，流水线自动走「签名 → 公证 → stable」，别人双击即开。

还可以用 **Variables** 改应用名：`MAC_APP_NAME`（默认 `词典`）。

---

## 四、没有 Mac 也不会上 GitHub 的话

退路按可靠程度排序：

1. **借一台 Mac 跑 [`build_mac.sh`](build_mac.sh)**：`./build_mac.sh --dmg`，20 分钟出包，脚本里连环境检查都带了。
2. **Mac 上直接跑源码**：装 `python@3.12` + `pip install PySide6-Essentials`，`python3 app.py`。
3. **Mac 云主机**（MacStadium、AWS EC2 mac 实例）：按时租，跑完脚本就销毁。

---

## 五、数据放在哪

macOS 版启动后，数据文件在：

```
~/Library/Application Support/词典/data/words.json
```

`.app` 内部是只读的，所以程序不会往 bundle 里写。想换词库，直接编辑这个文件，或用界面里的「导入 / 导出」。

程序启动时会先试同目录的 `data/`（Windows 绿色版就是这个），写不进去才退到 Application Support。打成 `.app` 后 bundle 只读，所以自动走第二个路径。
