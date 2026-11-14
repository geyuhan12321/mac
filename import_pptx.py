"""把 PPT 按「单字」导入：一个汉字一条，图片缩压后随条走。

用法：
    python import_pptx.py "汉字字典（拼音顺序版）.pptx" [--with-images]
"""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
IMAGES = DATA / "images"
OUT = DATA / "words.json"

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PIC = "{http://schemas.openxmlformats.org/presentationml/2006/main}pic"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
CJK = re.compile(r"[\u3400-\u9fff]")
MAX_W = 560           # 图片最大宽度
MIN_W = 120           # 小于这个宽度多半是图标，跳过


def slide_lines(z, name):
    root = ET.fromstring(z.read(name))
    out = []
    for para in root.iter(A + "p"):
        t = "".join(x.text or "" for x in para.iter(A + "t")).strip()
        if t:
            out.append(t)
    return out


def slide_images(z, num):
    """返回这一页引用的图片在压缩包里的路径列表（去重、保序）。"""
    rels = f"ppt/slides/_rels/slide{num}.xml.rels"
    if rels not in z.namelist():
        return []
    mapping = {}
    for rel in ET.fromstring(z.read(rels)):
        target = rel.get("Target", "")
        if "media" in target:
            mapping[rel.get("Id")] = target.replace("../", "ppt/")
    root = ET.fromstring(z.read(f"ppt/slides/slide{num}.xml"))
    out = []
    for pic in root.iter(PIC):
        for blip in pic.iter(A + "blip"):
            path = mapping.get(blip.get(R + "embed"))
            if path and path not in out:
                out.append(path)
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = Path(sys.argv[1])
    with_images = "--with-images" in sys.argv
    if not src.exists():
        print("找不到文件:", src)
        return 1

    from PySide6.QtGui import QGuiApplication, QImage

    app = QGuiApplication.instance() or QGuiApplication([])   # noqa: F841

    z = zipfile.ZipFile(src)
    slides = sorted(
        [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
        key=lambda n: int("".join(c for c in n if c.isdigit())),
    )

    IMAGES.mkdir(parents=True, exist_ok=True)
    entries, seen = [], set()
    stats = {"total": len(slides), "single": 0, "skip_multi": 0, "dup": 0,
             "imgs": 0, "img_bytes": 0}

    for name in slides:
        num = int("".join(c for c in name if c.isdigit()))
        lines = slide_lines(z, name)
        if not lines:
            continue
        head = lines[0].strip()
        # 只要单个汉字
        if len(head) != 1 or not CJK.match(head):
            stats["skip_multi"] += 1
            continue
        if head in seen:
            stats["dup"] += 1
            continue
        seen.add(head)
        stats["single"] += 1

        images = []
        if with_images:
            for media in slide_images(z, num):
                try:
                    info = z.getinfo(media)
                    data = z.read(media)
                except KeyError:
                    continue
                img = QImage.fromData(data)
                if img.isNull() or img.width() < MIN_W:
                    continue
                if img.width() > MAX_W:
                    img = img.scaledToWidth(MAX_W)
                flat = QImage(img.size(), QImage.Format.Format_RGB32)
                flat.fill(0xFFFFFFFF)          # 透明底转白底
                from PySide6.QtGui import QPainter
                p = QPainter(flat)
                p.drawImage(0, 0, img)
                p.end()
                fname = f"ppt-{num:05d}-{len(images)+1}.jpg"
                target = IMAGES / fname
                if flat.save(str(target), "JPEG", 82):
                    images.append({"file": fname, "caption": ""})
                    stats["imgs"] += 1
                    stats["img_bytes"] += target.stat().st_size

        entries.append({
            "id": f"c-{head}",
            "headword": head,
            "lang": "zh",
            "frequency": None,
            "pronunciation": {"pinyin": "", "uk": "", "us": ""},
            "wordForms": [],
            "character": None,
            "senses": [{
                "pos": "",
                "definition": "\n".join(lines[1:]),   # 原样保留
                "definitionZh": "",
                "examples": [],
                "synonyms": [], "collocations": [], "labels": [], "note": "",
                "images": [],
            }],
            "phrases": [],
            "etymology": "",
            "images": images,
            "tags": [],
            "source": "",
        })

    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"总页 {stats['total']}｜单字词条 {stats['single']}｜跳过非单字 {stats['skip_multi']}｜重复 {stats['dup']}")
    if with_images:
        print(f"图片 {stats['imgs']} 张，{stats['img_bytes']/1024/1024:.0f} MB → {IMAGES}")
    print(f"词库 {len(entries)} 条 → {OUT}（{OUT.stat().st_size/1024/1024:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
