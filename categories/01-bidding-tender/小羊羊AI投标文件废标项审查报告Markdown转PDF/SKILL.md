---
name: 小羊羊AI投标文件废标项审查报告Markdown转PDF
description: 小羊羊AI投标文件废标项审查报告 Markdown 转 PDF 技能。当用户需要对投标审查报告生成 PDF 文档时使用此技能。该技能将 Markdown 格式的审查报告通过 Python 脚本转换为排版专业的 PDF 文件，支持中文、表格、分级标签、结论框等复杂排版。触发场景：用户完成废标项审查后要求输出 PDF 报告、或要求将审查报告转换为正式文档时。
agent_created: true
Author: administrator
Date: 2026-05-19
BusinessSupportVersion: 1.0.0
---

# 📄 小羊羊AI 投标废标审查报告 Markdown → PDF 技能

## 概述

本技能提供将投标文件废标项审查报告（Markdown 格式）转换为专业 PDF 报告的能力。
核心思路是使用 `fpdf2` 纯 Python 库直接构建 PDF，不依赖任何外部浏览器或系统组件，
在 Windows 环境下稳定可靠。

## 适用时机

- 用户完成投标审查并要求生成交付物时
- 用户说"生成 PDF""导出报告""打印""出正式文档"时
- 审查报告 Markdown 已就绪，需要转换为正式版 PDF 时

## 工作流程

### 步骤 1：准备运行环境

使用脚本前，确保已安装 `fpdf2`：

```bash
# 在已存在的 venv 中安装，或用脚本自检安装
pip install fpdf2
```

如果 `generate_bid_pdf.py` 找不到 `fpdf2`，会自动提示安装。

### 步骤 2：使用脚本生成 PDF

脚本支持两种调用方式：

**方式 A — 命令行模式（推荐用于简单场景）：**

```bash
python scripts/generate_bid_pdf.py input.md output.pdf
```

**方式 B — 编程模式（用于复杂定制场景）：**

```python
from scripts.generate_bid_pdf import BidReportPDF, find_chinese_font

pdf = BidReportPDF(font_path=find_chinese_font())

pdf.render_cover_page(
    project_name="项目全称",
    project_no="项目编号",
    package_no="包号",
    bidder="投标人名称",
    reviewer="审查人",
    review_date="审查日期",
    verdict_text="审查结论文字（如：存在严重废标项，不建议通过）",
    table_headers=["#", "废标项", "级别", "判定", "关键依据"],
    table_rows=[
        ("1", "废标项描述", "P0", "废标", "依据条款"),
        ("2", "...", "P1", "极可能废标", "..."),
    ],
)

pdf.add_page()
pdf.render_section_title("一、P0级废标项（直接导致废标）")
pdf.render_danger_item_header("废标项1：问题描述")
pdf.render_clause_label("依据条款：")
pdf.render_clause_item("招标文件某条款：...")
pdf.render_clause_label("投标文件实际情况：")
pdf.render_body_text("描述文字...")
pdf.render_verdict_box("判定：废标（P0）")

# ... 继续添加更多内容 ...

pdf.output("输出路径.pdf")
```

### 步骤 3：可用排版方法一览

| 方法 | 用途 | 效果 |
|:----|:----|:----|
| `render_cover_page(...)` | 封面页 | 深蓝色标题 + 项目信息 + 红色结论框 + 速览表 |
| `render_section_title(text, color)` | 章节大标题 | 13pt 加粗 |
| `render_danger_item_header(text)` | P0 废标项标题栏 | 红色底色 + 白色文字 |
| `render_warning_item_header(text)` | P1 问题标题栏 | 橙色底色 + 白色文字 |
| `render_clause_label(text)` | 条款标签 | 红色加粗 |
| `render_clause_item(text)` | 条款项 | 缩进+项目符号 |
| `render_body_text(text)` | 正文段落 | 9pt 灰色正文 |
| `render_verdict_box(text)` | 判定框 | 红色居中框 |
| `render_recommendation(text)` | 建议项 | 缩进正文 |
| `render_bottom_line()` | 底部分隔线 | 灰色虚线 |
| `render_footer_text(lines)` | 底部文字 | 灰色小字 |

## 注意事项

1. **字体**：脚本会自动检测 Windows 下的微软雅黑（msyh.ttc）、宋体（simsun.ttc）等中文字体；
   macOS 下会找苹方/黑体；Linux 下会找文泉驿/Noto。如果找不到，会回退到 Helvetica（中文会乱码）。
2. **中文 Unicode**：`fpdf2` 需要注册包含中文的字体文件（.ttc/.ttf），不要用标准 PDF 内置字体。
3. **分页**：设置 `auto_page_break=True`，内容超出时会自动分页。需要强制分页时调用 `pdf.add_page()`。
4. **性能**：生成 4-5 页 PDF 约需 3-5 秒，无需担心。
5. **Python 版本**：需要 Python 3.8+，推荐用 3.11+。
