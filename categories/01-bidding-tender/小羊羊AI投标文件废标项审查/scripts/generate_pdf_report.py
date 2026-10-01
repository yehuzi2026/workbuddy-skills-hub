#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
废标审查报告 PDF 生成器
=====================
将7步废标审查结果渲染为排版精美、简单易懂的 PDF 报告。

设计原则：
  - 封面 + 仪表盘总览 + 逐步详情 + 风险清单 + 终审确认
  - 红/黄/绿三色语义：❌废标(红) / ⚠️风险(黄) / ✅通过(绿)
  - 表格清晰，关键数据一目了然
  - 纯中文排版，专业商务风格

依赖：pip install reportlab
用法：
    python generate_pdf_report.py --data "审查报告.json" -o "输出报告.pdf"
    python generate_pdf_report.py --data "审查报告.json"                    # 默认输出同目录
    python generate_pdf_report.py --example                                 # 生成示例报告（测试用）
"""

import json
import os
import sys
import argparse
from datetime import datetime
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, Flowable, KeepTogether, ListFlowable, ListItem,
    CondPageBreak
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ============================================================
# 常量 & 配色方案
# ============================================================

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 22 * mm
RIGHT_MARGIN = 18 * mm
TOP_MARGIN = 25 * mm
BOTTOM_MARGIN = 20 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN

# 语义色系 — 红/黄/绿，对标中国用户习惯
COLOR_PASS_GREEN = colors.HexColor("#2E7D32")       # ✅ 通过 — 深绿
COLOR_RISK_YELLOW = colors.HexColor("#F57C00")      # ⚠️ 风险 — 深橙黄
COLOR_FAIL_RED = colors.HexColor("#C62828")          # ❌ 废标 — 深红
COLOR_HEADER_BG = colors.HexColor("#1A237E")         # 标题栏深蓝
COLOR_SUBHEADER_BG = colors.HexColor("#303F9F")      # 二级标题蓝
COLOR_LIGHT_BG = colors.HexColor("#E8EAF6")          # 浅蓝交替行
COLOR_TEXT_DARK = colors.HexColor("#212121")         # 正文深灰
COLOR_TEXT_SECONDARY = colors.HexColor("#616161")    # 辅助文字灰
COLOR_BORDER = colors.HexColor("#B0BEC5")            # 表格边框灰
COLOR_COVER_GRADIENT_TOP = colors.HexColor("#1A237E")
_COLOR_COVER_BOTTOM = colors.HexColor("#3949AB")
COLOR_WHITE = colors.white
COLOR_BLACK = colors.black

# 状态映射
STATUS_MAP = {
    "pass": ("✅ 通过", COLOR_PASS_GREEN),
    "risk": ("⚠️ 风险", COLOR_RISK_YELLOW),
    "fail": ("❌ 废标", COLOR_FAIL_RED),
}

# ============================================================
# 中文字体注册
# ============================================================

def register_fonts():
    """注册系统中文字体，按优先级尝试多个字体路径"""
    font_candidates = [
        # Windows 常见中文字体
        ("msyh", "C:/Windows/Fonts/msyh.ttc", 0),       # 微软雅黑
        ("msyhbd", "C:/Windows/Fonts/msyhbd.ttc", 0),   # 微软雅黑粗体
        ("simhei", "C:/Windows/Fonts/simhei.ttf"),       # 黑体
        ("simsun", "C:/Windows/Fonts/simsun.ttc", 0),   # 宋体
        # macOS / Linux fallback
        ("pingfang", "/System/Library/Fonts/PingFang.ttc", 1),
        ("noto", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ]

    registered_main = False
    registered_bold = False
    for name, path, *index in font_candidates:
        full_path = path
        idx = index[0] if index else 0
        if os.path.exists(full_path):
            try:
                pdfmetrics.registerFont(TTFont(name, full_path, subfontIndex=idx))
                if not registered_main:
                    FONT_MAIN = name
                    registered_main = True
                elif not registered_bold:
                    FONT_BOLD = name
                    registered_bold = True
                print(f"[字体注册] {name} <- {full_path}")
            except Exception as e:
                print(f"[字体跳过] {path}: {e}")

    if not registered_main:
        raise RuntimeError(
            "未找到任何中文字体！请确保系统安装了微软雅黑(msyh.ttc)或黑体(simhei.ttf)\n"
            "Windows: 字体位于 C:\\Windows\\Fonts\\\n"
            "安装后重试即可。"
        )

    return FONT_MAIN if registered_main else "Helvetica"

# 全局变量 — 字体名（模块加载时注册）
FONT_NAME = ""

def ensure_font():
    global FONT_NAME
    if not FONT_NAME:
        FONT_NAME = register_fonts()
    return FONT_NAME


# ============================================================
# 自定义绘制组件
# ============================================================

class CoverPage(Flowable):
    """封面页 — 居中大标题 + 项目信息卡片"""

    def __init__(self, project_name, audit_date, bidder_name="", ref_no=""):
        Flowable.__init__(self)
        self.project_name = project_name or "（待填写项目名称）"
        self.audit_date = audit_date or datetime.now().strftime("%Y年%m月%d日")
        self.bidder_name = bidder_name
        self.ref_no = ref_no

    def wrap(self, availWidth, availHeight):
        """返回封面需要的尺寸 — 填满整个可用页面区域"""
        self.width = availWidth
        self.height = availHeight
        return (self.width, self.height)

    def draw(self):
        canvas = self.canv
        aw, ah = self.width, self.height  # 实际可用宽高（严格不超此范围）

        font = ensure_font()

        # 背景填满可用区域
        canvas.setFillColor(COLOR_COVER_GRADIENT_TOP)
        canvas.rect(0, 0, aw, ah, fill=1, stroke=0)

        # 底部装饰条
        canvas.setFillColor(_COLOR_COVER_BOTTOM)
        canvas.rect(0, 0, min(ah * 0.12, 80), aw, fill=1, stroke=0)

        # 主标题区域
        canvas.setFillColor(COLOR_WHITE)
        canvas.setFont(font, 36)
        canvas.drawCentredString(aw / 2, ah - 140, "投标文件")
        canvas.drawCentredString(aw / 2, ah - 190, "废标项审查报告")

        # 分隔线
        canvas.setStrokeColor(colors.HexColor("#FFC107"))
        canvas.setLineWidth(3)
        canvas.line(aw / 2 - 100, ah - 215, aw / 2 + 100, ah - 215)

        # 项目信息卡片 — 宽度自适应页面，最大不超过可用宽度的72%
        # 卡片位置整体下移 198pt（约7cm = 原始85pt + 额外113pt/4cm），避免与标题区重叠
        card_w = min(int(aw * 0.72), 300)
        card_h = 220  # 增加高度以容纳新增的源技能作者行
        card_x = (aw - card_w) / 2  # 居中
        card_y = ah - 518  # 原值 ah-320，累计下移 198pt（约7cm）

        canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.95))
        canvas.roundRect(card_x, card_y, card_w, card_h, 10, fill=1, stroke=0)

        # 信息文字 — 根据卡片宽度动态调整字号和位置
        canvas.setFillColor(COLOR_TEXT_DARK)
        info_lines = [
            f"项目名称：{self.project_name}",
            f"审查日期：{self.audit_date}",
        ]
        if self.ref_no:
            info_lines.append(f"项目编号：{self.ref_no}")
        if self.bidder_name:
            info_lines.append(f"投标人：{self.bidder_name}")

        # 源技能作者标注（固定追加在最后一行）
        info_lines.append("源技能作者：小羊羊AI招投标")

        # 自动适配字号：如果最长的行超出卡片内边距则缩小字体
        max_text_w = card_w - 30  # 左右各留15px内边距
        base_font_size = 13
        for try_size in [13, 12, 11, 10]:
            canvas.setFont(font, try_size)
            max_line_w = max(canvas.stringWidth(line, font, try_size) for line in info_lines)
            if max_line_w <= max_text_w:
                base_font_size = try_size
                break

        canvas.setFont(font, base_font_size)
        text_start_x = card_x + 15  # 从卡片左内边距开始写
        for i, line in enumerate(info_lines):
            canvas.drawString(text_start_x, card_y + card_h - 40 - i * 32, line)

        # 底部提示文字
        canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.7))
        canvas.setFont(font, 10)
        canvas.drawCentredString(aw / 2, 35, "本报告由「废标项审查技能」自动生成 · 仅供封标前内部参考")


class DashboardCard(Flowable):
    """仪表盘统计卡 — 圆角色块 + 大数字"""

    def __init__(self, label, value, color, width=88, height=54):
        Flowable.__init__(self)
        self.label = label
        self.value = str(value)
        self.color = color
        self.card_width = width
        self.card_height = height

    def wrap(self, availWidth, availHeight):
        """报告自身占用的精确尺寸"""
        return (self.card_width, self.card_height)

    def draw(self):
        canvas = self.canv
        font = ensure_font()

        # 卡片背景圆角矩形 — 严格在声明的宽高范围内绘制
        canvas.setFillColor(self.color)
        canvas.roundRect(0, 0, self.card_width, self.card_height, 8, fill=1, stroke=0)

        # 数字
        canvas.setFillColor(COLOR_WHITE)
        canvas.setFont(font, 22)
        canvas.drawCentredString(self.card_width / 2, self.card_height - 28, self.value)

        # 标签
        canvas.setFont(font, 8.5)
        canvas.drawCentredString(self.card_width / 2, 10, self.label)


class StatusBadge(Flowable):
    """状态标签 — 小色块"""

    def __init__(self, status_text, color, width=65, height=20):
        Flowable.__init__(self)
        self.text = status_text
        self.color = color
        self.badge_width = width
        self.badge_height = height

    def draw(self):
        canvas = self.canv
        font = ensure_font()
        canvas.setFillColor(self.color)
        canvas.roundRect(0, 0, self.badge_width, self.badge_height, 4, fill=1, stroke=0)
        canvas.setFillColor(COLOR_WHITE)
        canvas.setFont(font, 9)
        canvas.drawCentredString(self.badge_width / 2, 4, self.text)


class ProgressBar(Flowable):
    """水平进度条 — 显示通过率"""

    def __init__(self, pass_count, total, width=None, height=14):
        Flowable.__init__(self)
        self.pass_count = pass_count
        self.total = total
        self._bar_width = width  # None 表示在 wrap 时自动适配

    def wrap(self, availWidth, availHeight):
        if self._bar_width is None or self._bar_width > availWidth:
            self._bar_width = availHeight  # 用满可用宽度
        return (self._bar_width, 28)  # 14px 进度条 + 14px 文字

    def draw(self):
        canvas = self.canv
        font = ensure_font()

        if self.total == 0:
            ratio = 0
        else:
            ratio = self.pass_count / self.total

        bw = self._bar_width

        # 背景（浅灰）— 绘制在上半部分 (y: 14~28)
        canvas.setFillColor(colors.HexColor("#E0E0E0"))
        canvas.roundRect(0, 14, bw, 14, 4, fill=1, stroke=0)

        # 通过部分（绿色）
        if ratio > 0:
            canvas.setFillColor(COLOR_PASS_GREEN)
            canvas.roundRect(0, 14, bw * ratio, 14, 4, fill=1, stroke=0)

        # 百分比文字 — 居中于底部 (y: 2)
        pct_str = f"{ratio * 100:.0f}%"
        canvas.setFillColor(COLOR_TEXT_DARK)
        canvas.setFont(font, 9)
        canvas.drawCentredString(bw / 2, 2, f"综合通过率：{pct_str} ({self.pass_count}/{self.total})")


class SectionDivider(Flowable):
    """章节分隔线 — 带序号标题"""

    def __init__(self, number, title, width=CONTENT_WIDTH):
        Flowable.__init__(self)
        self.number = number
        self.title = title
        self.div_width = width

    def wrap(self, availWidth, availHeight):
        """声明实际占用尺寸，确保 KeepTogether / 分页引擎正确计算空间"""
        # 固定高度 22pt（色带18pt + 底线间距4pt）
        return (self.div_width, 22)

    def draw(self):
        canvas = self.canv
        font = ensure_font()

        # 左侧色带（紧凑高度，避免向上遮挡）
        canvas.setFillColor(COLOR_HEADER_BG)
        canvas.rect(0, -2, 4, 18, fill=1, stroke=0)

        # 编号 + 标题
        canvas.setFillColor(COLOR_HEADER_BG)
        canvas.setFont(font, 12)
        canvas.drawString(12, 2, f"{self.number}. {self.title}")

        # 底线（紧贴文字下方）
        canvas.setStrokeColor(colors.HexColor("#E0E0E0"))
        canvas.setLineWidth(0.5)
        canvas.line(0, -6, self.div_width, -6)


# ============================================================
# 样式工厂
# ============================================================

def create_styles():
    """创建所有段落样式"""
    font = ensure_font()

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="ChineseTitle",
        fontName=font,
        fontSize=18,
        textColor=COLOR_HEADER_BG,
        spaceBefore=16,
        spaceAfter=10,
        leading=24,
        alignment=TA_LEFT,
    ))

    styles.add(ParagraphStyle(
        name="ChineseSubtitle",
        fontName=font,
        fontSize=13,
        textColor=COLOR_TEXT_SECONDARY,
        spaceBefore=6,
        spaceAfter=8,
        leading=18,
    ))

    styles.add(ParagraphStyle(
        name="ChineseBody",
        fontName=font,
        fontSize=10,
        textColor=COLOR_TEXT_DARK,
        spaceBefore=3,
        spaceAfter=3,
        leading=16,
        alignment=TA_LEFT,
    ))

    styles.add(ParagraphStyle(
        name="ChineseSmall",
        fontName=font,
        fontSize=8.5,
        textColor=COLOR_TEXT_SECONDARY,
        spaceBefore=2,
        spaceAfter=2,
        leading=13,
    ))

    styles.add(ParagraphStyle(
        name="ChineseCenter",
        fontName=font,
        fontSize=11,
        textColor=COLOR_TEXT_DARK,
        alignment=TA_CENTER,
        spaceBefore=4,
        spaceAfter=4,
        leading=15,
    ))

    styles.add(ParagraphStyle(
        name="TableHeader",
        fontName=font,
        fontSize=9,
        textColor=COLOR_WHITE,
        alignment=TA_CENTER,
        leading=13,
    ))

    styles.add(ParagraphStyle(
        name="TableCell",
        fontName=font,
        fontSize=8.5,
        textColor=COLOR_TEXT_DARK,
        leading=12,
        alignment=TA_LEFT,
    ))

    styles.add(ParagraphStyle(
        name="TableCellCenter",
        fontName=font,
        fontSize=8.5,
        textColor=COLOR_TEXT_DARK,
        leading=12,
        alignment=TA_CENTER,
    ))

    styles.add(ParagraphStyle(
        name="RiskItem",
        fontName=font,
        fontSize=9,
        textColor=COLOR_TEXT_DARK,
        spaceBefore=2,
        spaceAfter=2,
        leading=14,
        leftIndent=6,
    ))

    return styles


# ============================================================
# 表格构建工具
# ============================================================

def build_checklist_table(items, styles, col_widths=None):
    """
    构建核查结果表格
    items: [{"name": "...", "status": "pass|risk|fail", "desc": "..."}]
    """
    if col_widths is None:
        col_widths = [CONTENT_WIDTH * 0.42, CONTENT_WIDTH * 0.13, CONTENT_WIDTH * 0.45]

    header = [
        Paragraph("<b>核查项</b>", styles["TableHeader"]),
        Paragraph("<b>状态</b>", styles["TableHeader"]),
        Paragraph("<b>问题描述 / 备注</b>", styles["TableHeader"]),
    ]

    data = [header]
    for item in items:
        status_label, status_color = STATUS_MAP.get(item.get("status", "pass"), STATUS_MAP["pass"])
        row = [
            Paragraph(item.get("name", ""), styles["TableCell"]),
            Paragraph(f'<font color="{status_color.hexval()}" size="9"><b>{status_label}</b></font>', styles["TableCellCenter"]),
            Paragraph(item.get("desc", "—"), styles["TableCell"]),
        ]
        data.append(row)

    table = Table(data, colWidths=col_widths, repeatRows=1)

    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_WHITE),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, -1), ensure_font()),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]

    # 交替行底色 + 状态行高亮
    for i, item in enumerate(items, start=1):
        bg_color = COLOR_LIGHT_BG if i % 2 == 0 else COLOR_WHITE
        style_commands.append(("BACKGROUND", (0, i), (-1, i), bg_color))

        # 状态行整行淡色高亮
        if item.get("status") == "fail":
            style_commands.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FFEBEE")))
        elif item.get("status") == "risk":
            style_commands.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FFF3E0")))

    table.setStyle(TableStyle(style_commands))
    return table


def build_risk_table(risk_items, styles):
    """
    构建风险整改清单表格
    risk_items: [{"priority": "高|中|低", "code": "1.1", "desc": "...", "suggest": "...", "deadline": "..."}]
    """
    col_widths = [CONTENT_WIDTH * 0.08, CONTENT_WIDTH * 0.09, CONTENT_WIDTH * 0.28,
                   CONTENT_WIDTH * 0.30, CONTENT_WIDTH * 0.15]

    header = [
        Paragraph("<b>优先级</b>", styles["TableHeader"]),
        Paragraph("<b>废标点编号</b>", styles["TableHeader"]),
        Paragraph("<b>问题描述</b>", styles["TableHeader"]),
        Paragraph("<b>整改建议</b>", styles["TableHeader"]),
        Paragraph("<b>截止时间</b>", styles["TableHeader"]),
    ]

    PRIORITY_COLORS = {
        "高": COLOR_FAIL_RED,
        "中": COLOR_RISK_YELLOW,
        "低": colors.HexColor("#FFA000"),
    }

    data = [header]
    for item in risk_items:
        pri = item.get("priority", "中")
        pri_color = PRIORITY_COLORS.get(pri, COLOR_RISK_YELLOW)
        row = [
            Paragraph(f'<font color="{pri_color.hexval()}" size="10"><b>{pri}</b></font>', styles["TableCellCenter"]),
            Paragraph(item.get("code", ""), styles["TableCellCenter"]),
            Paragraph(item.get("desc", ""), styles["TableCell"]),
            Paragraph(item.get("suggest", ""), styles["TableCell"]),
            Paragraph(item.get("deadline", ""), styles["TableCellCenter"]),
        ]
        data.append(row)

    table = Table(data, colWidths=col_widths, repeatRows=1)

    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_WHITE),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (1, -1), "CENTER"),
        ("ALIGN", (4, 1), (4, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, -1), ensure_font()),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]

    for i in range(1, len(risk_items) + 1):
        bg_color = COLOR_LIGHT_BG if i % 2 == 0 else COLOR_WHITE
        style_commands.append(("BACKGROUND", (0, i), (-1, i), bg_color))

    table.setStyle(TableStyle(style_commands))
    return table


def build_summary_info_table(info_dict, styles):
    """构建项目基本信息表"""
    rows = [[Paragraph("<b>项目信息</b>", styles["TableHeader"]), Paragraph("<b>内容</b>", styles["TableHeader"])]]
    for label, value in info_dict.items():
        rows.append([
            Paragraph(label, styles["TableCell"]),
            Paragraph(value, styles["TableCell"]),
        ])

    col_widths = [CONTENT_WIDTH * 0.30, CONTENT_WIDTH * 0.70]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_WHITE),
        ("FONTNAME", (0, 0), (-1, -1), ensure_font()),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#F5F5F5")),
    ]))
    return table


# ============================================================
# 页眉页脚
# ============================================================

def add_page_number(canvas, doc):
    """页脚：页码 + 分隔线 + 标题"""
    canvas.saveState()

    # 顶部细线
    canvas.setStrokeColor(colors.HexColor("#E0E0E0"))
    canvas.setLineWidth(0.5)
    canvas.line(LEFT_MARGIN, PAGE_HEIGHT - 12, PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 12)

    # 底部页码
    font = ensure_font()
    page_num = canvas.getPageNumber()
    canvas.setFont(font, 8)
    canvas.setFillColor(COLOR_TEXT_SECONDARY)

    if page_num > 1:  # 封面不显示页脚
        canvas.drawCentredString(PAGE_WIDTH / 2, 12 * mm, f"— {page_num - 1} —")
        canvas.drawString(LEFT_MARGIN, 12 * mm, "废标项审查报告")
        canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 12 * mm, datetime.now().strftime("%Y-%m-%d"))

    canvas.restoreState()


# ============================================================
# 示例数据生成器
# ============================================================

def get_example_data():
    """生成完整的示例审查数据（用于测试和演示）"""
    return {
        "project_name": "XX市政务服务中心物业管理服务采购项目",
        "audit_date": datetime.now().strftime("%Y年%m月%d日"),
        "bidder_name": "XX物业管理有限公司",
        "ref_no": "ZB-2026-0XX",

        "summary": {
            "total_steps": 7,
            "total_items": 21,
            "pass_count": 17,
            "risk_count": 3,
            "fail_count": 1,
        },

        "steps": [
            {
                "step_num": 1,
                "step_title": "固定格式审查",
                "items": [
                    {"name": "表格模板逐页比对", "status": "pass", "desc": "与招标文件格式完全一致"},
                    {"name": "填完打印查溢出", "status": "pass", "desc": "无内容溢出、无覆盖边框"},
                    {"name": "字体字号锁定（暗标）", "status": "risk", "desc": "第45页发现一处字号偏大0.5pt，需确认是否影响评审"},
                    {"name": "盖章签字位置确认", "status": "pass", "desc": "公章、法人章、授权签字均已到位"},
                    {"name": "落款日期规则", "status": "pass", "desc": "日期为开标当天，有效期满足要求"},
                    {"name": "电子标日期水印", "status": "pass", "desc": "水印日期与落款日期一致"},
                ],
            },
            {
                "step_num": 2,
                "step_title": "投标文件组成/目录审查",
                "items": [
                    {"name": "文件名称确认", "status": "pass", "desc": "使用'投标文件'命名，符合要求"},
                    {"name": "分册方式核验", "status": "pass", "desc": "商务+技术+报价三册，无串册"},
                    {"name": "正副本数量核对", "status": "pass", "desc": "正本1份+副本4份+电子版U盘2个"},
                    {"name": "清单拣货法（第一轮）", "status": "pass", "desc": "目录涵盖全部要求的组成项"},
                    {"name": "目录与正文翻对", "status": "pass", "desc": "逐项翻查，标题与页码一致"},
                    {"name": "目录页码核对", "status": "pass", "desc": "目录标注页码与实际一致"},
                ],
            },
            {
                "step_num": 3,
                "step_title": "点对点审查（8轮）",
                "items": [
                    {"name": "第1轮：基础信息逐字校核", "status": "pass", "desc": "公司名/法人/项目名/编号全部正确"},
                    {"name": "第2轮：存在性核查（清单法）", "status": "pass", "desc": "所有'提供/出具/填写'要求均有对应材料"},
                    {"name": "第3轮：实质性条款雷达扫描", "status": "fail", "desc": "⚠️ 发现★号条款'须提供ISO9001证书'的证明材料放置在技术册而非资格册，可能被评委会判定为无效响应！需立即移至资格文件册。"},
                    {"name": "  └ 证明材料有效性核查", "status": "risk", "desc": "检测报告有效期至2026年3月，距投标日已超期，建议补充新报告或提供延期说明"},
                    {"name": "  └ 证明材料目录位置核查", "status": "pass", "desc": "其余材料均在正确位置"},
                    {"name": "  └ 灰色地带闭环", "status": "pass", "desc": "已就模糊条款向代理机构邮件确认并获回复"},
                    {"name": "第4轮：★/▲号条款响应核查", "status": "pass", "desc": "一对一证据钩稽表完整，每条均有页码索引"},
                    {"name": "第5轮：证明材料有效性核查", "status": "pass", "desc": "审计报告扫码验证通过，体系证书官网核实有效"},
                    {"name": "第6轮：资格条件逐条过", "status": "risk", "desc": "项目经理社保连续月份为11个月，招标要求12个月，差1个月，需补充说明"},
                    {"name": "第7轮：中小企业声明函专项核查", "status": "pass", "desc": "行业类型、从业人员、资产总额均与审计报告一致"},
                    {"name": "第8轮：模拟评标", "status": "pass", "desc": "两人交叉复核，除上述问题外其余均通过"},
                ],
            },
            {
                "step_num": 4,
                "step_title": "报价审查",
                "items": [
                    {"name": "限价红线确认", "status": "pass", "desc": "总价¥1,280,000在限价¥1,350,000以内"},
                    {"name": "三表总价一致", "status": "pass", "desc": "开标一览表=投标函=分项报价表合计"},
                    {"name": "手工计算器验证", "status": "pass", "desc": "手动加算无误"},
                    {"name": "大写金额终审", "status": "pass", "desc": "大写与小写完全对应"},
                    {"name": "报价格式与评分规则对照", "status": "pass", "desc": "税率、分类口径与评分规则一致"},
                    {"name": "小数点核查", "status": "pass", "desc": "保留两位小数，无异常"},
                    {"name": "中小企业声明函数据溯源", "status": "pass", "desc": "与财务审计报告核对一致"},
                ],
            },
            {
                "step_num": 5,
                "step_title": "页码审查",
                "items": [
                    {"name": "页码规则提取与比对", "status": "pass", "desc": "起始页、格式、位置均符合要求"},
                    {"name": "捻纸巡检法", "status": "pass", "desc": "页码连续无中断无重复"},
                    {"name": "缩略图巡检法", "status": "pass", "desc": "PDF缩略图无异常空白页"},
                    {"name": "大图/横表页码确认", "status": "pass", "desc": "横排页面页码可见未被覆盖"},
                ],
            },
            {
                "step_num": 6,
                "step_title": "索引/偏离/响应表页码审查",
                "items": [
                    {"name": "实地翻查页码引用", "status": "pass", "desc": "所有'见第X页'均已手指翻到确认"},
                    {"name": "页码更新同步", "status": "pass", "desc": "正文增删后已同步更新所有索引表"},
                    {"name": "商务偏离表承诺", "status": "pass", "desc": "'完全响应无任何偏离'+签字盖章齐全"},
                ],
            },
            {
                "step_num": 7,
                "step_title": "废标风险项整改清单",
                "items": [
                    {"name": "灰色地带逐项闭环", "status": "pass", "desc": "3项不确定条款均已获得代理机构书面确认"},
                    {"name": "确认方式留存", "status": "pass", "desc": "邮件凭证归档，电话录音备份"},
                    {"name": "遗留项清零检查", "status": "pass", "desc": "无'待确认'遗留项"},
                ],
            },
        ],

        "risk_list": [
            {
                "priority": "高",
                "code": "3.8",
                "desc": "实质性条款漏响应：★号条款要求的ISO9001证书放置位置错误",
                "suggest": "立即将该证书从技术册移至资格文件册，更新目录和页码",
                "deadline": "封标前",
            },
            {
                "priority": "中",
                "code": "3.9",
                "desc": "检测报告有效期超期（至2026年3月）",
                "suggest": "补充新的有效检测报告；或向代理机构提交延期说明申请",
                "deadline": "封标前",
            },
            {
                "priority": "中",
                "code": "3.3",
                "desc": "项目经理社保连续月份差1个月（要求12个月，实际11个月）",
                "suggest": "补缴当月社保并出具缴费凭证附入资格文件",
                "deadline": "封标前3天",
            },
        ],

        "final_checklist": [
            "所有❌废标项已整改完成",
            "所有⚠️风险项已确认处理方案",
            "第三步实质性条款雷达扫描所有项已闭环",
            "第七步风险整改清单所有项已闭环",
            "模拟评标已通过（两人交叉复核签字）",
        ],
    }


# ============================================================
# 核心：构建完整PDF文档
# ============================================================

def build_pdf_report(data, output_path):
    """
    根据审查数据构建完整PDF报告

    Args:
        data: 审查数据字典（结构见 get_example_data()）
        output_path: 输出PDF文件路径
    """
    font = ensure_font()
    styles = create_styles()

    # 创建文档
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=f"废标项审查报告 - {data.get('project_name', '未知项目')}",
        author="废标项审查技能",
        subject="投标文件废标风险排查报告",
    )

    story = []  # 文档元素列表

    # ==================== 封面 ====================
    story.append(CoverPage(
        project_name=data.get("project_name", ""),
        audit_date=data.get("audit_date", datetime.now().strftime("%Y年%m月%d日")),
        bidder_name=data.get("bidder_name", ""),
        ref_no=data.get("ref_no", ""),
    ))
    story.append(PageBreak())

    # ==================== 审查结果总览 ====================
    story.append(Paragraph("📋 投标文件废标项审查结果总览", styles["ChineseTitle"]))
    story.append(Spacer(1, 6))

    summary = data.get("summary", {})
    total_items = summary.get("total_items", 0)
    pass_count = summary.get("pass_count", 0)
    risk_count = summary.get("risk_count", 0)
    fail_count = summary.get("fail_count", 0)

    # 项目基本信息
    info_dict = {
        "项目名称": data.get("project_name", "—"),
        "审查日期": data.get("audit_date", "—"),
        "项目编号": data.get("ref_no", "—"),
        "投标人": data.get("bidder_name", "—"),
        "审查步骤": f"{summary.get('total_steps', 7)}步全覆盖",
    }
    story.append(build_summary_info_table(info_dict, styles))
    story.append(Spacer(1, 12))

    # 仪表盘卡片行 — 每张卡片自适应缩小，确保总宽 ≤ CONTENT_WIDTH
    card_w = min(88, (CONTENT_WIDTH - 30) // 4)  # 留出间距，4张均分
    card_h = 54
    dashboard_data = [
        [DashboardCard("核查总数", total_items, colors.HexColor("#1565C0"), card_w, card_h),
         DashboardCard("✅ 通过", pass_count, COLOR_PASS_GREEN, card_w, card_h),
         DashboardCard("⚠️ 风险", risk_count, COLOR_RISK_YELLOW, card_w, card_h),
         DashboardCard("❌ 废标", fail_count, COLOR_FAIL_RED, card_w, card_h)],
    ]
    dashboard_table = Table(dashboard_data, colWidths=[card_w + 4] * 4)  # 列宽略大于卡片
    dashboard_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(dashboard_table)
    story.append(Spacer(1, 10))

    # 进度条 — 自动适配页面宽度，不再手动指定
    story.append(ProgressBar(pass_count, total_items))
    story.append(Spacer(1, 16))

    # 快速结论
    if fail_count > 0:
        conclusion = f'<font color="{COLOR_FAIL_RED.hexval()}" size="11"><b>⛔ 结论：发现 {fail_count} 项废标问题，必须在封标前修复！</b></font>'
    elif risk_count > 0:
        conclusion = f'<font color="{COLOR_RISK_YELLOW.hexval()}" size="11"><b>⚠️ 结论：整体基本合格，但仍有 {risk_count} 项风险需关注处理。</b></font>'
    else:
        conclusion = '<font color="{COLOR_PASS_GREEN.hexval()}" size="11"><b>🎉 结论：全部核查项通过，可以进入封标流程。</b></font>'.format(
            COLOR_PASS_GREEN=COLOR_PASS_GREEN
        )
    story.append(Paragraph(conclusion, styles["ChineseCenter"]))
    story.append(Spacer(1, 20))

    # ==================== 逐步审查详情 ====================
    story.append(Paragraph("📋 逐步审查详情", styles["ChineseTitle"]))
    story.append(Spacer(1, 8))

    steps = data.get("steps", [])
    for idx, step in enumerate(steps):
        # 第一个步骤前不额外加间距（标题已有），后续步骤前多留空间
        if idx > 0:
            story.append(Spacer(1, 10))

        # ---- 防跨页断行：双保险策略 ----
        # 1) CondPageBreak：如果剩余空间 < 150pt（约5cm），强制先换页
        story.append(CondPageBreak(150))

        items = step.get("items", [])
        step_pass = sum(1 for i in items if i.get("status") == "pass")
        step_risk = sum(1 for i in items if i.get("status") == "risk")
        step_fail = sum(1 for i in items if i.get("status") == "fail")

        summary_line = f"<font size='8.5' color='{COLOR_TEXT_SECONDARY.hexval()}'>" \
                       f"本步骤共 {len(items)} 项 | " \
                       f"<font color='{COLOR_PASS_GREEN.hexval()}'>✅{step_pass}</font> &nbsp;&nbsp; " \
                       f"<font color='{COLOR_RISK_YELLOW.hexval()}'>⚠️{step_risk}</font> &nbsp;&nbsp; " \
                       f"<font color='{COLOR_FAIL_RED.hexval()}'>❌{step_fail}</font>" \
                       f"</font>"

        # 2) KeepTogether：把标题+摘要绑在一起，即使 CondPageBreak 的阈值没卡住也能兜底
        step_header_content = []
        step_header_content.append(SectionDivider(step["step_num"], step["step_title"]))
        step_header_content.append(Spacer(1, 12))
        step_header_content.append(Paragraph(summary_line, styles["ChineseSmall"]))
        step_header_content.append(Spacer(1, 4))
        story.append(KeepTogether(step_header_content))

        # 核查表格
        if items:
            tbl = build_checklist_table(items, styles)
            story.append(tbl)

        story.append(Spacer(1, 14))

    # ==================== 风险项整改清单 ====================
    story.append(PageBreak())
    story.append(Paragraph("🚨 风险项整改清单", styles["ChineseTitle"]))
    story.append(Spacer(1, 6))

    risk_list = data.get("risk_list", [])
    if risk_list:
        risk_tbl = build_risk_table(risk_list, styles)
        story.append(risk_tbl)
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            "<font size='8.5' color='#C62828'><b>⚠ 以上风险项必须在截止时间前完成整改并确认闭环，否则可能导致废标。</b></font>",
            styles["RiskItem"],
        ))
    else:
        story.append(Paragraph('<font color="#2E7D32">🎉 本次审查未发现需要整改的风险项。</font>', styles["ChineseBody"]))

    story.append(Spacer(1, 20))

    # ==================== 封标前终审确认 ====================
    story.append(Paragraph("✅ 封标前终审确认清单", styles["ChineseTitle"]))
    story.append(Spacer(1, 8))

    final_items = data.get("final_checklist", [])
    check_data = [[Paragraph("<b>终审确认项</b>", styles["TableHeader"]),
                   Paragraph("<b>确认状态</b>", styles["TableHeader"])]]
    for item in final_items:
        check_data.append([
            Paragraph(f"☐  {item}", styles["TableCell"]),
            Paragraph("<font color='#9E9E9E'>□ 未确认</font>", styles["TableCellCenter"]),
        ])

    check_table = Table(check_data, colWidths=[CONTENT_WIDTH * 0.78, CONTENT_WIDTH * 0.18])
    check_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_WHITE),
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
    ]))
    story.append(check_table)
    story.append(Spacer(1, 16))

    # 签字区提示
    story.append(Paragraph("— — — 签字确认区 — — —", styles["ChineseSubtitle"]))
    story.append(Spacer(1, 8))

    sign_rows = [["审查人签字：_________________", "日期：______年______月______日"],
                 ["复核人签字：_________________", "日期：______年______月______日"]]
    sign_table = Table(sign_rows, colWidths=[CONTENT_WIDTH * 0.55, CONTENT_WIDTH * 0.38])
    sign_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
    ]))
    story.append(sign_table)
    story.append(Spacer(1, 24))

    # 免责声明
    disclaimer = (
        "<font size='7.5' color='#9E9E9E'>"
        "<i>免责声明：本报告基于AI辅助审查工具生成，旨在帮助投标企业进行系统性废标风险排查。"
        "审查结论仅供参考，最终以人工审核和招标代理机构/评委会判定为准。"
        "如需定制化深度审查服务，可联系专业人员。</i>"
        "</font>"
    )
    story.append(Paragraph(disclaimer, styles["ChineseSmall"]))

    # ==================== 构建 ====================
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"\n✅ PDF报告已生成：{output_path}")
    print(f"   总计 {total_items} 项核查 | ✅{pass_count} 通过 | ⚠️{risk_count} 风险 | ❌{fail_count} 废标")
    return output_path


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="废标审查报告 PDF 生成器 — 将审查结果渲染为专业排版的PDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：

  # 用示例数据生成报告（测试用）
  python %(prog)s --example

  # 从JSON文件读取审查数据
  python %(prog)s --data 审查报告.json -o 输出报告.pdf

  # 从JSON读取，自动取名
  python %(prog)s --data 审查报告.json
        """,
    )
    parser.add_argument("--data", "-d", type=str, default=None,
                        help="审查数据的JSON文件路径（结构与get_example_data()一致）")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="输出PDF文件路径（默认与JSON同名）")
    parser.add_argument("--example", action="store_true",
                        help="使用内置示例数据生成一份演示报告")

    args = parser.parse_args()

    if args.example:
        data = get_example_data()
        output = args.output or os.path.join(os.getcwd(), "废标审查报告_示例.pdf")
    elif args.data:
        if not os.path.exists(args.data):
            print(f"❌ 数据文件不存在：{args.data}")
            sys.exit(1)
        with open(args.data, "r", encoding="utf-8") as f:
            data = json.load(f)
        base = os.path.splitext(os.path.basename(args.data))[0]
        output = args.output or os.path.join(os.getcwd(), f"{base}_审查报告.pdf")
    else:
        parser.print_help()
        print("\n⚠ 请指定 --data <json文件> 或 --example 使用示例数据")
        sys.exit(1)

    build_pdf_report(data, output)


if __name__ == "__main__":
    main()
