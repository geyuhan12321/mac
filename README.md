# 词典 · 桌面版

本地汉字词典。数据来自 PPT 逐字导入，共 **4425 个单字**、**4064 张字源图**。

- 左边是字表，按导入页序排列
- 中间是字条：字形、字义、组词、字源图
- **正文里的每个字都能点**，点到哪个字就跳到哪个字条

## 启动

```powershell
python -m pip install PySide6-Essentials
python app.py
```

或双击 `launch.bat`（Windows）。

## 导入自己的数据

```powershell
# 从 PPT 导入（一个汉字一条，可选带图片）
python import_pptx.py "你的字典.pptx" --with-images
```

生成到 `data/words.json` 和 `data/images/`。这两个目录体积较大（约 106MB），**不进仓库**，需自行生成或拷贝。

## 功能

| 功能 | 说明 |
|---|---|
| 点字跳转 | 字条正文里出现的字，只要词库里有就变成可点链接 |
| 前进 / 后退 | 左上角 `‹` `›`，或 `Alt+←` / `Alt+→`，或鼠标侧键 |
| 字号 | `Ctrl+=` 放大、`Ctrl+-` 缩小、`Ctrl+0` 重置，正文与列表同步缩放 |
| 编辑 | 词条页「编辑」进入，版式与阅读页一致 |
| 插图 | 任意输入框里 `Ctrl+V` 直接粘图 |
| 导入导出 | CSV / JSON 互转 |
| 严格模式 | 只让词库里的字可点，未收录的字当普通文字 |

## 文件

```
app.py                 窗口、菜单、编辑、导入导出
dictionary_model.py    词条规范化、分词索引
dictionary_render.py   词条转富文本
import_pptx.py         PPT 批量导入
doctor.py              环境自检
data/                  词库与图片（不进仓库）
```

## 打包

- macOS（Apple Silicon）：GitHub Actions，见 [BUILD_MAC.md](BUILD_MAC.md)
- Windows：`pyinstaller -F -w --name 词典 app.py`
