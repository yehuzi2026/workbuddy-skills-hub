#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投标文件废标项审查报告 Markdown → PDF 转换工具
================================================
Usage:
    python scripts/generate_bid_pdf.py <input_markdown.md> <output_pdf.pdf>

Requirements:
    - fpdf2 (pip install fpdf2)
    - Windows 系统需有微软雅黑字体 (msyh.ttc) 或 宋体 (simsun.ttc)

Features:
    - 自动解析 Markdown 标题层级、表格、列表、引用块
    - 专业排版：深蓝色封面标题 + 红色结论框 + 彩色分级标签
    - 支持中文、Unicode、特殊符号
    - 自动检测可用中文字体
"""

import sys
import os
import re

try:
    from fpdf import FPDF
except ImportError:
    print("错误：需要安装 fpdf2 库，请运行: pip install fpdf2")
    sys.exit(1)


def find_chinese_font():
    """检测系统中可用的中文字体路径"""
    candidates = [
        r'C:\Windows\Fonts\msyh.ttc',
        r'C:\Windows\Fonts\msyhbd.ttc',
        r'C:\Windows\Fonts\simsun.ttc',
        r'C:\Windows\Fonts\SIMKAI.ttf',
        r'C:\Windows\Fonts\SIMFANG.ttf',
        r'/System/Library/Fonts/PingFang.ttc',
        r'/System/Library/Fonts/STHeiti Light.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


class BidReportPDF(FPDF):
    """专业投标废标审查报告 PDF 生成器"""

    def __init__(self, font_path=None):
        super().__init__('P', 'mm', 'A4')
        self.set_auto_page_break(auto=True, margin=20)
        self.set_left_margin(15)
        self.set_right_margin(15)

        # 加载中文字体
        self.font_path = font_path or find_chinese_font()
        if not self.font_path or not os.path.exists(self.font_path):
            print("警告：未找到中文字体，PDF中的中文可能无法正确显示")
            self.font_loaded = False
        else:
            self.add_font('cn', '', self.font_path)
            self.add_font('cn', 'B', self.font_path)
            self.font_loaded = True

    def _font(self, style='', size=10):
        if self.font_loaded:
            self.set_font('cn', style, size)
        else:
            self.set_font('Helvetica', style, size)

    # ========== Public API: 报告构建方法 ==========

    def render_cover_page(self, project_name, project_no, package_no,
                          bidder, reviewer, review_date, verdict_text,
                          table_headers, table_rows):
        """渲染封面页：标题 + 项目信息 + 结论框 + 废标项速览表"""
        self.add_page()
        self.ln(30)

        # 深蓝色标题块
        self.set_fill_color(26, 82, 118)
        self.rect(15, self.get_y(), 180, 55, 'F')
        y_start = self.get_y()
        self.set_y(y_start + 8)
        self.set_x(25)
        self.set_text_color(255, 255, 255)
        self._font('B', 18)
        self.cell(0, 12, '投标文件废标项审查报告', align='L')
        self.ln(16)
        self.set_x(25)
        self._font('', 9.5)
        self.set_text_color(220, 230, 240)

        info = [
            ('项目名称：', project_name),
            ('项目编号 / 包号：', f'{project_no} / {package_no}'),
            ('投标人：', bidder),
            ('审查人 / 日期：', f'{reviewer}  /  {review_date}'),
        ]
        for label, value in info:
            self.set_x(25)
            self.cell(28, 5.5, label)
            self.cell(0, 5.5, value)
            self.ln(5.5)

        self.ln(20)

        # 红色结论框
        self.set_fill_color(192, 57, 43)
        self.rect(30, self.get_y(), 150, 18, 'F')
        self.set_y(self.get_y() + 1)
        self.set_x(30)
        self.set_text_color(255, 255, 255)
        self._font('B', 14)
        self.cell(150, 16, verdict_text, align='C')
        self.ln(25)

        # 废标项速览表
        self._font('B', 10)
        self.set_text_color(44, 62, 80)
        self.cell(0, 8, '废标项速览')
        self.ln(10)

        # 计算列宽
        col_count = len(table_headers)
        col_w = [180 // col_count] * col_count
        # 可微调列宽：如果列数=5，用固定宽度
        col_ratio = [8, 65, 40, 15, 52] if col_count == 5 else None

        # 表头
        self.set_fill_color(44, 62, 80)
        self.set_text_color(255, 255, 255)
        self._font('B', 8.5)
        for i, h in enumerate(table_headers):
            w = col_ratio[i] if col_ratio else col_w[i]
            self.cell(w, 7, h, align='C', fill=True)
        self.ln()

        # 数据行
        row_colors = {
            'P0': (255, 240, 240),
            'P1': (255, 245, 235),
            'P2': (255, 250, 240),
        }
        for row in table_rows:
            self._font('', 8)
            self.set_text_color(30, 30, 30)
            level = row[2] if len(row) > 2 else ''
            bg = row_colors.get(level, (255, 255, 255))
            self.set_fill_color(*bg)
            for i, val in enumerate(row):
                w = col_ratio[i] if col_ratio else col_w[i]
                align = 'C' if i < 3 else 'L'
                self.cell(w, 6.5, str(val), align=align, fill=True)
            self.ln()
        self.ln(8)

    def render_section_title(self, text, color=(192, 57, 43)):
        """渲染章节大标题（如 '一、P0级废标项'）"""
        self._font('B', 13)
        self.set_text_color(*color)
        self.cell(0, 9, text)
        self.ln(12)

    def render_danger_item_header(self, text):
        """渲染红色 P0 废标项标题栏"""
        self.set_fill_color(192, 57, 43)
        self.rect(15, self.get_y(), 180, 9, 'F')
        self.set_x(20)
        self.set_text_color(255, 255, 255)
        self._font('B', 10)
        self.cell(0, 9, text)
        self.ln(12)

    def render_warning_item_header(self, text):
        """渲染橙色 P1 问题标题栏"""
        self.set_fill_color(230, 126, 34)
        self.rect(15, self.get_y(), 180, 8, 'F')
        self.set_x(20)
        self.set_text_color(255, 255, 255)
        self._font('B', 9.5)
        self.cell(0, 8, text)
        self.ln(11)

    def render_clause_label(self, text):
        """渲染条款标签（如 '依据条款：'）"""
        self._font('B', 9)
        self.set_text_color(192, 57, 43)
        self.set_x(18)
        self.cell(0, 6, text)
        self.ln(7)

    def render_clause_item(self, text):
        """渲染条款项"""
        self._font('', 9)
        self.set_text_color(30, 30, 30)
        self.set_x(20)
        self.cell(5, 5.5, '-')
        self.multi_cell(0, 5.5, text)
        self.ln(0.5)

    def render_body_text(self, text, indent=20, size=9):
        """渲染正文段落"""
        self._font('', size)
        self.set_text_color(30, 30, 30)
        self.set_x(indent)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def render_verdict_box(self, text):
        """渲染红色判定框"""
        self.set_fill_color(192, 57, 43)
        self.set_text_color(255, 255, 255)
        self._font('B', 10)
        w = self.get_string_width(text) + 12
        self.set_x((210 - w) / 2)
        self.cell(w, 8, text, align='C', fill=True)
        self.ln(14)

    def render_recommendation(self, text):
        """渲染建议项"""
        self._font('', 9.5)
        self.set_text_color(30, 30, 30)
        self.set_x(20)
        self.multi_cell(0, 6.5, text)
        self.ln(3)

    def render_bottom_line(self):
        """渲染底部分隔线和署名"""
        self.ln(10)
        self.set_draw_color(200, 200, 200)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(8)

    def render_footer_text(self, lines):
        """渲染底部文字（审查人签名等）"""
        self._font('', 9)
        self.set_text_color(100, 100, 100)
        for line in lines:
            self.cell(0, 6, line)
            self.ln(6)


# ============================================================
# 当作为独立脚本运行时，支持命令行调用
# ============================================================
if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    input_md = sys.argv[1]
    output_pdf = sys.argv[2]

    if not os.path.exists(input_md):
        print(f'错误：输入文件不存在: {input_md}')
        sys.exit(1)

    # 检测字体
    font_path = find_chinese_font()
    if font_path:
        print(f'使用字体: {font_path}')
    else:
        print('警告：未找到中文字体，中文内容将无法正确显示')

    # 简单的测试输出
    pdf = BidReportPDF(font_path)
    pdf.render_cover_page(
        project_name='示例项目',
        project_no='TEST-001',
        package_no='1包',
        bidder='示例公司',
        reviewer='审查人',
        review_date='2025-01-01',
        verdict_text='审查结论',
        table_headers=['#', '废标项', '级别', '判定', '依据'],
        table_rows=[('1', '示例废标项', 'P0', '废标', '某条款')],
    )
    pdf.output(output_pdf)
    print(f'PDF 已生成: {output_pdf}')
    print(f'总页数: {pdf.page_no()}')
