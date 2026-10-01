---
name: skill-patch
description: >
  技能补建与契约对齐助手。当 self-evolve 审计（或 scan_refs / skill_audit.py）报出
  「缺失脚本 / 真实断链（broken）」且用户点名确认（如回复 C1 / 技能名）后，按
  「引用→契约→测试」流程补建技能内缺失的脚本或资源。
  触发词：补建技能脚本、对齐技能引用、修复技能断链、补脚本、skill patch、
  引用断链修复、引用→契约→测试、技能缺失文件、缺失脚本补建。
  非交互（自动化）模式下本技能不主动运行，只由审计上报「待确认建议」，等用户点名。
argument-hint: 技能名 或 断链编号(如 C1)
agent_created: true
---

本技能把「补建一个技能内缺失的脚本/资源」做成可复现的标准流程。来源：08-07 self-evolve
审计发现的 C1/C2/M1 三个缺失脚本，逐一补建并验证通过后沉淀而成。

> 前置：先跑 `~/.workbuddy/skills/self-evolve/scripts/skill_audit.py --json` 拿到 broken_refs
> 列表（真实断链）。本技能只处理被明确判定为 broken 的项；cross_skill / placeholder /
> runtime_* / suspect 一律不是补建对象，交给人工核实。

## 模式判定

- 用户点名某技能名 / 某断链编号（如 C1、C2、M1、或「补建 xxx 的 docx2pdf」）→ 进入补建流程。
- 自动化（非交互）检测到新增技能的真实断链 → **不调用本技能**，只在进化日志写
  「待确认建议：技能 X 缺 `scripts/foo.py`（broken），回复 X 或编号即可触发 skill-patch 补建」。

---

## 补建流程（7 步，缺一不可）

### 1. 定位缺失项
读目标技能 `SKILL.md`，grep 所有 `references/`、`scripts/`、`assets/`、`templates/` 引用，
列出：文件名、相对路径、调用处的文件与行号、调用方式（CLI / import / 文档说明）。
确认它确实是 broken（全局不存在、非跨技能、非占位符、非运行时/设计态）。

### 2. 提取契约（最关键，切忌臆造）
缺失脚本的「该做什么」必须由技能自身文本定义，不能自己编：
- **读 SKILL.md 中引用该脚本的上下文**：输入输出文件名、CLI 参数顺序、退出码语义、
  输出物（如 `phase5_docx_verification.json`）、是否要求校验某项。
- **读对应的 references/*.md 章节**：例如 `verify_docx_format.py` 的契约是
  `common_checks.md` 的 Section B（B.1~B.13 共 13 项检查）；`docx2pdf.py` 的契约在
  SKILL.md Phase 7（CLI `python scripts/docx2pdf.py <in.docx> <out.pdf>` + 元数据 + 页数校验）。
- **契约不明确 → 立即停下，向用户澄清需求**，绝不凭空写实现。这是红线。

### 3. 探测本机环境后端
补建前先确认「用什么引擎」，避免写出跑不起来的脚本。常用探测：
```bash
# DOCX → PDF 后端（按优先级）
ls "/c/Program Files/Microsoft Office/root/Office16/WINWORD.EXE" 2>/dev/null && echo "Word OK"
command -v soffice libreoffice 2>/dev/null || echo "无 LibreOffice"
# Python 第三方库是否可用
PY="$HOME/.workbuddy/binaries/python/versions/3.13.12/python.exe"
"$PY" -c "import docx" 2>/dev/null && echo "python-docx OK" || echo "无 python-docx"
"$PY" -c "import reportlab" 2>/dev/null && echo "reportlab OK" || echo "无 reportlab"
"$PY" -c "import win32com" 2>/dev/null && echo "pywin32 OK" || echo "无 pywin32"
```
- 本机现状：**有 MS Word，无 LibreOffice，managed Python 无 python-docx/reportlab/pywin32**。
- 因此 DOCX→PDF 优先用 **Word COM（经 PowerShell 调用）**，零 Python 依赖；
  OOXML 解析优先用 **stdlib（zipfile + xml.etree）**，不依赖 python-docx。
- 同级技能已有可复用实现时（如服务类/货物类的 `docx2pdf.py`），直接参考其已验证后端，
  不要重复造轮子。

### 4. 实现（零依赖优先）
- 能用标准库实现就**不引第三方包**：交付类脚本绝不能依赖一个可能缺失的 pip 包，
  否则闸门失效（python-docx 在本机 managed venv 未安装，是血的教训）。
- 多后端可切换：`--backend auto|word|libreoffice`，auto 时按探测优先级选。
- 退出码语义化：`0` 成功 / `2` 输入错 / `3` 无后端 / `4` 转换失败 / `5` 输出空 / `6` 校验不符。
  失败信息用中文且可操作（写明具体失败原因，符合用户「错误消息需含具体失败原因」偏好）。
- 资源释放：`finally` 中 Close + Quit + ReleaseComObject（Word COM），防 WINWORD 进程残留。
- 中文路径必须测：技能实际文件名常含中文（如 `技术方案_项目_排版完成.docx`）。

### 5. 双向测试（必做，闸门类尤其）
用 `scripts/make_min_docx.py` 造测试样本（零依赖）：
- **合规样本** → 期望 exit 0（如 `verify_docx_format.py` 13 项全过；`docx2pdf.py` 产出合法 PDF）。
- **违规样本** → 期望 exit 非 0 且**精准定位**问题项（闸门类必须能拦住，否则形同虚设）。
- 转换类额外验证：PDF 头部 `%PDF-`、尾部 `%%EOF` 完整、非空。
- 错误路径：输入不存在 / 非 .docx 输入 → 明确的退出码 + 原因。
- 多页校验（若契约含页数）：造多页样本，确认页数比对正确（注意 Word 把页面写成
  `/Type/Page` 无空格，且 `/Pages` 前缀会多减，用正则 `\b` 词边界排除）。

### 6. 验证闭环
- 跑 `skill_audit.py --json`，确认该脚本**不再命中 broken**（扫描闭环）。
- 用 Read 回读目标技能 SKILL.md，确认引用路径可解析、无新引入的失效引用。

### 7. 记录
写入当日 `<workspace>/.workbuddy/memory/YYYY-MM-DD.md`：补建了哪个文件、契约来源
（读了哪些章节）、后端选择、测试结论（合规/违规样本结果）、扫描闭环确认。

---

## 安全约束

- **只补建缺失文件，不删不改正常工作的技能**；一次补建 >50 行时，先写「建议」上报，不硬塞。
- **契约红线**：SKILL.md / references 没定义的，必须问用户，不臆造。
- **非交互禁用**：自动化模式下本技能不被触发，仅由审计产出「待确认建议」。

## 受管运行时（本机）

- Python：`C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe`
  （纯 stdlib 脚本直接用它跑；无需 venv）
- Node：`C:/Users/Administrator/.workbuddy/binaries/node/versions/22.22.2/node.exe`
- 扫描器：`C:/Users/Administrator/.workbuddy/skills/self-evolve/scripts/skill_audit.py`
