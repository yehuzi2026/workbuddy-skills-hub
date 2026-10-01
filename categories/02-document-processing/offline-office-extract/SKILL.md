---
name: offline-office-extract
description: "纯离线文档抽取（零依赖安装）。当沙箱/环境无法安装 pywin32、pymupdf、markitdown、RapidOCR 等第三方库（pip 经代理下载超时、无 LibreOffice/WPS）时，仅用 Python 标准库抽取 .doc(Word97-2003)、.docx、.pdf 的文本与内嵌/扫描图片，再用多模态 Read 直接识别图片内容（代替 OCR）。适用于读取招标文件/标书/扫描件、抽取 docx 内嵌截图、抽取 PDF 扫描页、旧版 .doc 降级提取。触发词：读不了doc、打不开docx、PDF是扫描件、pip装不上、没有LibreOffice、离线提取、抽取文档图片、文档转文本。"
agent_created: true
---

# offline-office-extract — 纯离线文档/图片抽取

> 沉淀自 2026-09-30 实战（人保财险整车招标文件整理）。核心场景：**沙箱 pip 装不了包，但仍要读 .doc / .docx / 扫描 PDF。**

## 何时用（识别信号）

- `pip install pywin32 / pymupdf / markitdown / rapidocr ...` 卡住或超时（常见现象：`Connection timed out while downloading`、进度停在几百 KB）。
- 本机无 LibreOffice / WPS / MS Word COM，无法转换 `.doc`。
- 拿到的 `.docx` 只有几十字正文但体积几 MB（正文是**图片**）；PDF 是**扫描件**（`pypdf.extract_text()` 只出几十字）。
- 需要把文档里的图片抽出来看内容，但没有 OCR 库。

## 核心思路（三步）

1. **文本**：`.doc` → 标准库按 **UTF-16LE 扫描** WordDocument 流（降级，可能含噪声）；`.docx` → python-docx（有则用，无则 zipfile 读 `word/document.xml`）；`.pdf` → pypdf（文字型直接出，扫描型出不了就以图片为准）。
2. **图片**：`.docx` 用 `zipfile` 直接取 `word/media/*`；`.pdf` 解析流对象取 `DCTDecode`(JPEG)/`FlateDecode` 图像（扫描件通常每页 1 张大图）。
3. **识别**：**用多模态 Read 工具直接 Read 抽出来的 png/jpg**——模型自带视觉，可替代 OCR，无需装任何库。这是本方法的关键：**不装 OCR，改让模型看图**。

## 一键脚本

```bash
"<受管python>/python.exe" "C:/Users/AHS/.workbuddy/skills/offline-office-extract/scripts/offline_extract.py" \
  "<输入文件或目录>" -o "<输出目录>"
```

产出：`<out>/text/*.txt`（文本）+ `<out>/media/*_imgNN.png|*_pageNN.jpg`（图片，随后用 Read 识别）。

## 实测要点 / 坑

- **`.doc` 是 OLE 复合文件**（magic `d0cf11e0a1b11ae1`），不是 zip。没有 olefile/pywin32 时，UTF-16LE 扫描能救回**正文段落**，但**表格（如标包清单）会乱**——此时改用文档自带的「附件/澄清通知」等**表格清晰的文件**作权威来源。
- **PDF 扫描件**：`pypdf` 抽不出文字是正常的（几十字），必须走「抽图 + Read 看图」。
- **图片很大**（如 3310×4680）。Read 能直接读，多张可并行 Read。
- 中文路径在 Git Bash 下 `ls` 可能列出为空 → 改用 Python `os.listdir`/`os.walk` 探查，避免误判"文件不存在"。
- 先验证工具可用性：`python -c "import docx,pypdf"`，再决定走哪条路。

## 与其它技能的关系

- 有 OCR 需求且本机装了 RapidOCR → 优先用 `hybrid-image-ocr`（本地 OCR 更准）。
- 中标书场景 → 本技能产出文本/图片后，衔接 `招标文件关键信息提取--小羊羊AI` 做结构化。
- 若日后 pip 恢复可用，`.doc→.docx` 仍以 **Word COM / LibreOffice** 为首选（保真度最高），本脚本只作离线兜底。
