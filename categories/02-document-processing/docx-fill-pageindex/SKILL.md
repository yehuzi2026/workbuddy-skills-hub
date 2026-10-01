---
name: docx-fill-pageindex
description: "给 .docx 里的表格填数据，并自动回填「证明文件所在页码」这类需要真实排版页码的列。做法：python-docx 填格（保留原格式）→ 用 PowerShell 工具调本机 Word COM 把 docx 导出 PDF → pymupdf 搜标题文本定位页码 → 回填 → 重转 PDF 复核页码未漂移。适用于投标业绩表/索引表/目录页码、附录页码引用。触发词：填写业绩表、补页码、证明文件所在页码、docx填表、页码引用、投标文件页码、表格自动填。"
agent_created: true
---

# docx-fill-pageindex — docx 表格填写 + 真实页码回填

> 沉淀自 2026-10-01 实战（人保整车招标 · 湖北《同类业绩汇总》10 列业绩表填写）。
> 核心场景：**表格里有一列要求填"证明材料在第几页"，而页码只有排版后才能知道。**

## 何时用（识别信号）

- 用户给一张表格截图/空表 + 一份 docx，说"完善这个表 / 补全 / 填一下"。
- 表格列含「证明文件所在页码」「详见 X 页」「所在页码」「附录页码」。
- 需要 docx → PDF 用来数页/看排版效果。

## 工作流（5 步，别跳步）

### 1. 先摸清文档结构，别急着填
```python
# 按 body 顺序打印 段落/表格，看清表格在哪个标题下、有几张同类表
from docx import Document
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn
d = Document(path)
for child in d.element.body.iterchildren():
    if child.tag == qn('w:p'):
        p = Paragraph(child, d)
        has_img = bool(child.findall('.//'+qn('a:blip')))
        if p.text.strip() or has_img: print("P:", p.text.strip()[:60], "[图片]" if has_img else "")
    elif child.tag == qn('w:tbl'):
        print("T: 表格")
```
**重点**：同一文件里常有多张同主题表（本例：开头 1 张空模板 + 后面 1 张已填表），先确认"要填哪张"再动手。

### 2. 找数据源，避免手抄
优先从**已有且已被用户确认过的文件**里读现成数据行（本例源＝最终版商务文件的业绩表）。
若源表与目标表列数不同，做显式列映射（如源 9 列 → 目标 10 列：第 9 列留空、第 10 列放备注）。

### 3. 填格：必须保留单元格原格式
**不要用 `cell.text = "..."`**（会清掉字体/对齐）。用：
```python
def set_cell(cell, text, font='宋体', size_pt=9):
    from docx.shared import Pt
    from docx.oxml.ns import qn
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    p = cell.paragraphs[0]
    for r in list(p.runs): r._element.getparent().remove(r._element)   # 清旧 run
    if p.alignment is None: p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.font.name = font
    run._element.rPr.rFonts.set(qn('w:eastAsia'), font)   # 中文字体必须设 eastAsia
    run.font.size = Pt(size_pt)
```
脚本：`scripts/docx_table_tools.py`

### 4. docx → PDF（只能用 PowerShell 工具，见"三个坑"#1）
```powershell
$log = "$env:TEMP\wb_pdf.txt"          # PowerShell 工具 stdout 不回显，结果写文件
$src = 'C:\...\x.docx'
$dst = 'C:\...\x.pdf'
try {
  $w = New-Object -ComObject Word.Application
  $w.Visible = $false; $w.DisplayAlerts = 0
  $d = $w.Documents.Open($src, $false, $true)     # 只读打开
  $d.ExportAsFixedFormat($dst, 17)                # 17 = wdExportFormatPDF
  $pages = $d.ComputeStatistics(2)                # 2 = wdStatisticPages
  $d.Close(0); $w.Quit()
  "PAGES=$pages" | Set-Content -Path $log -Encoding UTF8
} catch { "ERROR: $($_.Exception.Message)" | Set-Content -Path $log -Encoding UTF8 }
```
然后用 Read 工具读 `$env:TEMP\wb_pdf.txt`。

### 5. 定位页码并回填 + **复核**
```python
import pymupdf
doc = pymupdf.open(pdf)
pages = [doc[i].get_text("text").replace(" ","").replace("\n","") for i in range(doc.page_count)]
# 每个证明材料标题在文档里都能搜到，取首次出现页 = 起始页
# 页码范围 = [start_i, start_{i+1} - 1]，最后一项到总页数
```
脚本：`scripts/locate_pages.py`

**必须复核**：回填页码后再导一次 PDF，重新定位，确认
① 总页数没变（表格在前部时，填字可能撑高行 → 后面全部页码平移）；
② 每个关键词的实际页码与已填值一致。
不一致就按新页码再改一轮（通常一次收敛）。

## 6. 搬表 / 去重（表格位置或标题对不上时）

同一 docx 里常出现"**同一张表被放错位置**"或"**10 列表 + 8 列表内容重复**"。处理：
```python
from docx_table_tools import move_table_after, remove_table, insert_empty_paragraph_after
# 例：把表格0 搬到「同类业绩汇总表」标题正下方，并删掉 8 列重复旧表
remove_table(doc, 11)                              # 先删重复表
move_table_after(doc, 0, "同类业绩汇总表")          # 再搬正表（用索引或 Table 对象均可）
```
- ⚠️ **两张表相邻时 Word 会自动合并**成一张（第二张的表头会变成数据行）→ 要么先去重，要么 `insert_empty_paragraph_after(doc, tbl._tbl)` 插空段落隔离。
- ⚠️ 删表是"改内容"不是"删文件"，但仍属数据变更：**先备份**（`shutil.copy2` 到 `xxx_备份_日期.docx`），并在回复里说明删了哪张、如何还原。
- 搬完务必重跑 `iter_body` 校验：表的先后、行数列数、内容是否落位。

## ⚠️ 三个坑（本机实测，必踩）

1. **不能从 Bash 调 `powershell.exe`** → 被安全策略拦：`Invoking PowerShell from Bash bypasses PowerShell security checks`。**转 PDF 必须用 PowerShell 工具**。
2. **PowerShell 工具 stdout 不回显**（命令 EXIT 0 但无输出）→ 把结果 `Set-Content` 到 `$env:TEMP\xxx.txt`，再用 Read 读。
3. **本机 safe-delete 会拦 `Remove-Item`** → `[safe-delete][SAFE_DELETE_FAIL_CLOSED] ... trash-failed`。**覆盖输出时改新文件名（v2/已填表等），不要删旧文件。**
4. **Word→PDF 导出本身有时也被 safe-delete 拦死**（`ExportAsFixedFormat` 抛 safe-delete，PowerShell 进程直接 exit 1）。本机无 LibreOffice 兜底。**对策**：换全新路径+带时间戳的新文件名重试；仍失败就别死磕 —— 用 `iter_body` 纯 XML 校验结构即已足够（页码回填场景才必须要 PDF，普通填表/搬表不需要）。

## 合规提醒（投标场景）

- 填「合同金额」这类列前，先回招标文件原文核对：**是禁"投标报价"还是禁"任何金额"**。
  本例招标文件明文禁的是"商务/技术文件不得有任何明示、暗示**投标报价**的内容"，而其第六章**官方业绩表模板自带「合同金额（万元）」列** → 历史合同金额可填。
  **不要一看到"金额"就删列**（过度保守会偏离招标人给定格式）。
- 填完主动提示：业绩是否匹配招标口径（如"损余机动车整车拍卖"业绩 vs 物资设备拍卖业绩）。

## 本机环境

- Word：`C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE`（可被 COM 调用）
- 无 LibreOffice / WPS
- Python：`C:/Users/AHS/.workbuddy/binaries/python/versions/3.13.12/python.exe`（已装 python-docx、pymupdf、PIL）
