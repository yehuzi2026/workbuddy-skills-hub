---
name: hybrid-image-ocr
description: "图片识别 / OCR 提取 / 表格识别 / 证件印章识别 Skill，专为做标书设计。混合模式：本地离线优先（RapidOCR，隐私不出本机），遇到模糊/复杂图片自动回退云端视觉。当用户说\"图片识别\"、\"OCR\"、\"识别图片文字\"、\"图片转文字\"、\"表格识别\"、\"图片里的表格\"、\"证件识别\"、\"识别公章/营业执照/资质证书\"、\"标书图片\"、\"截图转文字\"、\"扫描件转文字\"时触发。支持本地文件、http(s) URL、批量目录。"
agent_created: true
---

# hybrid-image-ocr — 标书图片识别 Skill（混合模式）

专为投标/标书场景设计的图片识别能力：**文字 OCR 提取、表格识别、通用图像理解、证件印章字段抽取** 四合一。
默认**本地离线**识别（RapidOCR，图片不出本机，保护标书敏感信息）；当本地结果质量不足或任务需要认知理解时，自动回退到**云端视觉**（WorkBuddy 内置多模态能力）兜底。

## 环境就绪说明（本机已装好，无需重装）

- 本地引擎：`rapidocr-onnxruntime` + `pillow` + `numpy` + `opencv-python` + `shapely`，装在受管 venv
  `C:/Users/Administrator/.workbuddy/binaries/python/envs/default/`
- 命令 wrapper：`ocr-local`（已放 `~/bin`，在 Git Bash PATH 中），直接调用受管 venv 的 python 跑脚本
- 模型：RapidOCR 的 onnx 模型首次运行时自动下载并缓存（约几十 MB）

如需重装：`"受管venv/python.exe" -m pip install rapidocr-onnxruntime pillow numpy==2.1.3 opencv-python==4.10.0.84`
（Python 3.13 必须用 numpy 2.x，opencv 用 4.x，勿用 5.x）

## 四种模式

| 模式 | 用途 | 本地做？ | 云端兜底 |
|------|------|----------|----------|
| `ocr` | 图片全部文字→可编辑文本（扫描件/截图转文字） | ✅ 默认本地 | 本地失败时才上云 |
| `table` | 图片表格→Markdown 表格 | ✅ 坐标聚类；质量差时输出 `[[FALLBACK_CLOUD]]` | 看到回退标记即上云 |
| `doc` | 证件/印章/资质图→抽取字段（公司名、编号、有效期） | 先本地OCR取文字块 | 必须上云做认知结构化 |
| `describe` | 通用图像理解（图里有什么、布局、图表含义） | ❌ | 直接上云（本技能用 Read 工具读图理解） |

## 工作流（agent 按此执行）

### 1) ocr 模式（文字提取，最常用）
```
ocr-local --image "<图片路径或URL>" [--json]
# 或批量：
ocr-local --dir "<图片目录>"
```
- 输出纯文本（按阅读顺序）。`--json` 给带坐标的结构化结果。
- 标书用法：把招标文件截图/扫描件转成可编辑文字，直接粘进标书或做比对。

### 2) table 模式（表格识别）
```
ocr-local --image "<图片路径或URL>" --mode table
```
- 本地按文字坐标聚类还原 Markdown 表格。
- **关键**：若输出含 `[[FALLBACK_CLOUD]]`，说明本地聚类质量不足（无边框表/倾斜/低置信），**立即改用云端**——用 Read 工具读该图片，以视觉能力输出 Markdown 表格。

### 3) doc 模式（证件/印章字段抽取）
```
ocr-local --image "<营业执照/资质证书/公章图片>" --mode doc [--json]
```
- 本地先取出所有文字块（含坐标）。
- **必须上云做结构化**：把图片用 Read 工具交给云端视觉，结合本地 OCR 文字块，抽取字段（公司名称、统一社会信用代码、证书编号、有效期、发证机关等），输出键值对。标书里用于资质核查、信息录入。

### 4) describe 模式（通用理解）
- 直接用 Read 工具读取图片，由云端视觉描述内容（物体、布局、图表含义、配图说明）。
- 标书用法：整理素材图、写图片说明、判断配图是否合规。

## 输入形式
- 本地文件：绝对路径，如 `F:/投标/资质/营业执照.jpg`
- URL：`ocr-local --image "https://..."` 会自动下载
- 批量：`ocr-local --dir "<目录>"` 处理目录下所有图片

## 输出建议（贴进标书前）
- ocr 纯文本：直接粘入文档，注意核对数字/标点（OCR 偶有误识）
- table：Markdown 转成 Word 表格；低质量图务必走云端复核
- doc：云端抽取的字段做人工核对后再用（证件信息容错率低）

## 注意
- 本地 OCR 对清晰印刷体中文效果好；手写体、艺术字、强扭曲图优先走云端。
- 标书敏感图片默认走本地，不上云；仅当本地做不了（table/doc/describe）才经云端，且不应包含涉密原件。
- RapidOCR 返回的 score 为字符串形式浮点，脚本已转为 float 处理。
