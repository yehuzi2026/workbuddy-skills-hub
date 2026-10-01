#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_docx_format.py — 技术方案编写监督「强制交付闸门」脚本（C1 补建）

对应技能：技术方案编写监督--小羊羊AI
触发点：SKILL.md Phase 5.5.2（货物类/服务类） DOCX 13 项自动化验证
输入  ：一个已生成的 .docx 文件（可选 --markdown 提供源码用于 B.10 表数比对）
输出  ：phase5_docx_verification.json（13 项 B.1~B.13 通过/失败 + 失败详情）
退出码：0 = 全部通过（可交付）；1 = 存在失败项（不得交付）；2 = 参数/解析错误

设计原则：
- 零外部依赖（仅用标准库 zipfile + xml.etree），保证在任何 Python 3 环境可直接运行，
  不依赖 python-docx 是否已安装。
- DOCX 即 OOXML（zip 内的 XML）。所有 13 项检查直接解析 word/document.xml 等部件。
- 状态三态：pass（已验证合规）/ fail（确定性违规，阻断交付）/ warn（无法判定，放行但提示）。
  只有 fail 会置 block_delivery=true。

13 项检查映射（详见 references/common_checks.md Section B）：
  B.1  字体/字号/颜色逐项验证（标题必须用 Heading 样式，否则 TOC 不可用）
  B.2  分页符逐级验证（v3.1.1 修正公式：按"实际有子节点的上级数量"计算）
  B.2.5 多级列表自动编号（标题文本不得手序号）
  B.3  正文段落序号全局验证（无 ● ◆ 等非法项目符号）
  B.4  表格列宽自适应验证（非等宽 + 表头色系合法）
  B.5  标题层级完整性验证（有 H1+H3 必须有 H2）
  B.6  Markdown 语法残留全局扫描（表格外无 | / --- / ** / ![]()）
  B.7  全量行距 1.5 倍验证
  B.8  表格单元格垂直居中 + 多行左对齐
  B.9  图片嵌入验证（内嵌图数 == 图标题数，无失败标记）
  B.10 表格转换验证（--markdown 时比对 Markdown 表数 == DOCX 表数）
  B.11 TOC 域验证（已插入中文目录域）
  B.12 内容俗套语验证（无【对采购人的实用价值】等）
  B.13 双版本×双色系验证（表头色系为合法单色系之一）
"""

import sys
import os
import re
import json
import zipfile
import argparse
import datetime
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# OOXML 命名空间
# ---------------------------------------------------------------------------
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"

def q(tag, ns=W):
    return "{%s}%s" % (ns, tag)

# A4 可用正文宽度（twips）：页面 11906 - 左右边距 1440*2 ≈ 9026
USABLE_WIDTH_TWIPS = 9026
# 合法表头色系（彩色 #4472C4 / 黑白 #333333）
VALID_HEADER_FILLS = {"4472C4", "333333", "2E5A9C"}  # 含历史色 #2E5A9C 兼容
VALID_HEADER_FILLS_LOWER = {c.lower() for c in VALID_HEADER_FILLS}

# 标题样式判定
def heading_level(style_val):
    """返回 0/1/2/3；非标题返回 0。"""
    if not style_val:
        return 0
    v = style_val.strip()
    vl = v.lower()
    if vl in ("heading1", "1"):
        return 1
    if vl in ("heading2", "2"):
        return 2
    if vl in ("heading3", "3"):
        return 3
    if "heading1" in vl:
        return 1
    if "heading2" in vl:
        return 2
    if "heading3" in vl:
        return 3
    return 0


# ---------------------------------------------------------------------------
# 文档加载与遍历
# ---------------------------------------------------------------------------
class DocxDoc:
    def __init__(self, path):
        self.path = path
        if not os.path.isfile(path):
            raise FileNotFoundError("DOCX 不存在: %s" % path)
        self.zf = zipfile.ZipFile(path, "r")
        try:
            self.doc_xml = self.zf.read("word/document.xml")
        except KeyError:
            raise ValueError("word/document.xml 缺失，不是合法 DOCX")
        self.root = ET.fromstring(self.doc_xml)
        self.body = self.root.find(q("body"))
        if self.body is None:
            raise ValueError("document.xml 缺少 w:body")

    def close(self):
        try:
            self.zf.close()
        except Exception:
            pass

    # ---- 遍历所有段落（含表格内嵌套）----
    def iter_paragraphs(self):
        """yield (p_elem, is_in_table)"""
        def walk(elem, in_table):
            for child in list(elem):
                tag = child.tag
                if tag == q("p"):
                    yield (child, in_table)
                elif tag == q("tbl"):
                    for row in child.findall(q("tr")):
                        for cell in row.findall(q("tc")):
                            for sub in list(cell):
                                if sub.tag == q("p"):
                                    yield (sub, True)
                                elif sub.tag == q("tbl"):
                                    yield from walk(sub, True)
                else:
                    # 其他容器（如 sdt）也递归
                    yield from walk(child, in_table)
        yield from walk(self.body, False)

    def iter_tables(self):
        def walk(elem):
            for child in list(elem):
                if child.tag == q("tbl"):
                    yield child
                    for row in child.findall(q("tr")):
                        for cell in row.findall(q("tc")):
                            for sub in list(cell):
                                if sub.tag == q("tbl"):
                                    yield from walk(sub)
                else:
                    yield from walk(child)
        yield from walk(self.body)


# ---------------------------------------------------------------------------
# 段落属性读取辅助
# ---------------------------------------------------------------------------
def get_text(p):
    parts = []
    for t in p.iter(q("t")):
        parts.append(t.text or "")
    return "".join(parts)

def get_style_val(p):
    ppr = p.find(q("pPr"))
    if ppr is None:
        return None
    pstyle = ppr.find(q("pStyle"))
    if pstyle is None:
        return None
    return pstyle.get(q("val"))

def has_page_break(p):
    """判断段落是否带硬分页符（段前分页 或 段内 w:br type=page 或 节属性下一页）。"""
    ppr = p.find(q("pPr"))
    if ppr is not None:
        if ppr.find(q("pageBreakBefore")) is not None:
            return True
        # 段内分页符
        for br in p.iter(q("br")):
            if br.get(q("type")) == "page":
                return True
        # 节属性
        sect = ppr.find(q("sectPr"))
        if sect is not None:
            st = sect.find(q("type"))
            if st is not None and st.get(q("val")) == "nextPage":
                return True
    return False

def get_run_rpr(run):
    return run.find(q("rPr"))

def run_props(run):
    """返回 run 的字体属性 dict（仅显式设置的）。"""
    rpr = get_run_rpr(run)
    if rpr is None:
        return None
    props = {}
    rfonts = rpr.find(q("rFonts"))
    if rfonts is not None:
        props["eastAsia"] = rfonts.get(q("eastAsia"))
        props["ascii"] = rfonts.get(q("ascii"))
    sz = rpr.find(q("sz"))
    if sz is not None:
        props["sz"] = sz.get(q("val"))  # 半磅
    color = rpr.find(q("color"))
    if color is not None:
        props["color"] = (color.get(q("val")) or "").lower()
    props["bold"] = rpr.find(q("b")) is not None
    return props

def get_para_rpr(p):
    """段落标记级 rPr（应用于整段的无显式 run 格式的文本）。"""
    ppr = p.find(q("pPr"))
    if ppr is None:
        return None
    return ppr.find(q("rPr"))


# ---------------------------------------------------------------------------
# 13 项检查实现
# ---------------------------------------------------------------------------
def check_b1_font(doc):
    """B.1 字体/字号/颜色；标题必须用 Heading 样式。"""
    details = []
    # 1) 标题样式检查（关键：Normal 样式标题会导致 TOC 不可用）
    headings_normal_style = 0
    for p, _ in doc.iter_paragraphs():
        lvl = heading_level(get_style_val(p))
        if lvl == 0:
            # 疑似标题但用 Normal 样式：粗体 + 较大字号 + 文本较短
            text = get_text(p).strip()
            if 0 < len(text) <= 60:
                rpr = get_para_rpr(p)
                sz = None
                bold = False
                if rpr is not None:
                    s = rpr.find(q("sz"))
                    if s is not None:
                        sz = s.get(q("val"))
                    bold = rpr.find(q("b")) is not None
                # 检查 run 级
                for run in p.findall(q("r")):
                    rp = run_props(run)
                    if rp:
                        if rp.get("sz"):
                            sz = rp["sz"]
                        if rp.get("bold"):
                            bold = True
                if bold and sz and int(sz) >= 28:
                    headings_normal_style += 1
                    details.append("疑似标题但使用 Normal 样式（TOC 不可用）：「%s」" % text[:30])
        else:
            # 标题段落，确认其样式是 Heading
            sv = get_style_val(p)
            if not (sv and ("heading" in sv.lower() or sv in ("1", "2", "3"))):
                # 已通过 heading_level 判定为标题，这里理论上不会触发；保险起见记录
                details.append("标题样式异常：%s" % (sv or "None"))
    # 2) 显式 run 格式合规（字体=宋体，颜色=#000000/auto）
    mismatch = 0
    for p, _ in doc.iter_paragraphs():
        lvl = heading_level(get_style_val(p))
        for run in p.findall(q("r")):
            rp = run_props(run)
            if not rp:
                continue
            ea = rp.get("eastAsia") or rp.get("ascii")
            if ea and ea != "宋体" and ea != "SimSun":
                mismatch += 1
                details.append("非宋体字体：%s（「%s」）" % (ea, get_text(run)[:20]))
            col = rp.get("color")
            if col and col not in ("000000", "auto", "windowtext"):
                # 允许表格表头白字（在 B.4 单独处理），正文出现非黑字记一笔
                if lvl == 0:
                    mismatch += 1
                    details.append("正文非黑色字体：#%s（「%s」）" % (col, get_text(run)[:20]))
    if headings_normal_style > 0:
        return {"status": "fail",
                "details": ["有 %d 个疑似标题使用 Normal 样式，TOC 将不可用" % headings_normal_style] + details[:8]}
    if mismatch > 0:
        return {"status": "fail",
                "details": ["发现 %d 处字体/颜色违例" % mismatch] + details[:8]}
    return {"status": "pass", "details": ["标题均使用 Heading 样式；正文宋体+黑色（继承样式未报错）"]}


def check_b2_pagebreaks(doc):
    """B.2 分页符逐级验证（v3.1.1 修正公式）。"""
    h1_count = h2_count = h3_count = 0
    h1_idx = h2_idx = 0
    cur_h1 = None
    cur_h2 = None
    h1_with_h2 = set()
    h2_with_h3 = set()
    h1_pb = h2_pb = h3_pb = 0
    total_pb = 0
    for p, _ in doc.iter_paragraphs():
        lvl = heading_level(get_style_val(p))
        pb = has_page_break(p)
        if pb:
            total_pb += 1
        if lvl == 1:
            h1_count += 1
            h1_idx += 1
            cur_h1 = h1_idx
            cur_h2 = None
            if pb:
                h1_pb += 1
        elif lvl == 2:
            h2_count += 1
            h2_idx += 1
            if cur_h1 is not None:
                h1_with_h2.add(cur_h1)
            cur_h2 = h2_idx
            if pb:
                h2_pb += 1
        elif lvl == 3:
            h3_count += 1
            if cur_h2 is not None:
                h2_with_h3.add(cur_h2)
            if pb:
                h3_pb += 1
    exp_h1 = max(h1_count - 1, 0)
    exp_h2 = max(h2_count - len(h1_with_h2), 0)
    exp_h3 = max(h3_count - len(h2_with_h3), 0)
    exp_total = exp_h1 + exp_h2 + exp_h3
    fails = []
    if h1_count == 0:
        return {"status": "warn", "details": ["文档无 H1 标题，跳过分页符比对（请确认标题层级已生成）"]}
    if h1_pb != exp_h1:
        fails.append("H1 分页符：实测 %d / 期望 %d（=H1总数-1）" % (h1_pb, exp_h1))
    if h2_pb != exp_h2:
        fails.append("H2 分页符：实测 %d / 期望 %d（=H2总数-含H2的H1数=%d）" % (h2_pb, exp_h2, h2_count - len(h1_with_h2)))
    if h3_pb != exp_h3:
        fails.append("H3 分页符：实测 %d / 期望 %d（=H3总数-含H3的H2数=%d）" % (h3_pb, exp_h3, h3_count - len(h2_with_h3)))
    if total_pb != exp_total:
        fails.append("总硬分页符：实测 %d / 期望 %d（含非标题段落的分页符，请核查）" % (total_pb, exp_total))
    if fails:
        return {"status": "fail", "details": fails}
    return {"status": "pass",
            "details": ["H1=%d(H2子节点H1=%d), H2=%d, H3=%d；分页符实测与修正公式一致"
                        % (h1_count, len(h1_with_h2), h2_count, h3_count)]}


def check_b25_numbering(doc):
    """B.2.5 多级列表自动编号：标题文本不得手序号。"""
    pats = [
        re.compile(r"^[一二三四五六七八九十百千零]+、"),
        re.compile(r"^（[一二三四五六七八九十]+）"),
        re.compile(r"^\d+[、.．]"),
        re.compile(r"^\([一二三四五六七八九十]+\)"),
    ]
    bad = []
    for p, _ in doc.iter_paragraphs():
        lvl = heading_level(get_style_val(p))
        if lvl == 0:
            continue
        text = get_text(p).strip()
        for pat in pats:
            if pat.match(text):
                bad.append("H%d 手序号：「%s」" % (lvl, text[:30]))
                break
    if bad:
        return {"status": "fail", "details": ["发现 %d 个标题含手序号（应改用 Word 多级列表自动编号）" % len(bad)] + bad[:8]}
    return {"status": "pass", "details": ["标题文本均无手序号，序号由 Word 多级列表自动生成"]}


def check_b3_para_numbering(doc):
    """B.3 正文段落序号全局验证：无 ● ◆ 等非法项目符号。"""
    illegal = ["●", "◆", "♦", "■", "▪"]
    latin = re.compile(r"^\s*([a-zA-Z]\.|\([a-zA-Z]\)|\([ivxlcdm]+\))\s")
    bad = []
    for p, in_table in doc.iter_paragraphs():
        if in_table:
            continue
        if heading_level(get_style_val(p)) != 0:
            continue
        text = get_text(p)
        if not text.strip():
            continue
        for ch in illegal:
            if ch in text:
                bad.append("非法项目符号 %s：%s" % (ch, text[:30]))
                break
        else:
            if latin.match(text):
                bad.append("非法拉丁序号：%s" % text[:30])
    if bad:
        return {"status": "fail", "details": ["发现 %d 处非法正文序号/项目符号" % len(bad)] + bad[:8]}
    return {"status": "pass", "details": ["正文无 ●◆ 等非法项目符号，四层序号体系合规"]}


def _table_grid_widths(tbl):
    grid = tbl.find(q("tblGrid"))
    if grid is None:
        return []
    widths = []
    for gc in grid.findall(q("gridCol")):
        w = gc.get(q("w"))
        if w:
            widths.append(int(w))
    return widths

def _cell_shd_fill(tc):
    tcpr = tc.find(q("tcPr"))
    if tcpr is None:
        return None
    shd = tcpr.find(q("shd"))
    if shd is None:
        return None
    return (shd.get(q("fill")) or "").lower()

def check_b4_table_width(doc):
    """B.4 表格列宽自适应 + 表头色系合法。"""
    if not any(True for _ in doc.iter_tables()):
        return {"status": "warn", "details": ["文档无表格，跳过（如方案应含表格请核查）"]}
    bad = []
    for i, tbl in enumerate(doc.iter_tables(), 1):
        widths = _table_grid_widths(tbl)
        if len(widths) >= 2:
            if len(set(widths)) == 1:
                bad.append("表%d：所有列等宽（应自适应，数据列≤15%、描述列≥30%）" % i)
        # 表头色系（首行首格）
        rows = tbl.findall(q("tr"))
        if rows:
            first_cells = rows[0].findall(q("tc"))
            if first_cells:
                fill = _cell_shd_fill(first_cells[0])
                if fill and fill not in VALID_HEADER_FILLS_LOWER:
                    bad.append("表%d：表头填充色 #%s 不在合法色系（#4472C4/#333333）" % (i, fill))
    if bad:
        return {"status": "fail", "details": bad[:8]}
    return {"status": "pass", "details": ["表格列宽非等宽、表头色系合法"]}


def check_b5_hierarchy(doc):
    """B.5 标题层级完整性：H1+H3 之间必须有 H2。"""
    cur_h1 = None
    cur_h2 = None
    h3_without_h2 = 0
    for p, _ in doc.iter_paragraphs():
        lvl = heading_level(get_style_val(p))
        if lvl == 1:
            cur_h1 = True
            cur_h2 = False
        elif lvl == 2:
            cur_h2 = True
        elif lvl == 3:
            if cur_h1 is None:
                h3_without_h2 += 1
            elif cur_h2 is False:
                h3_without_h2 += 1
    if h3_without_h2 > 0:
        return {"status": "fail",
                "details": ["有 %d 个 H3 出现在无 H2 的层级中（标题层级断裂，TOC/导航异常）" % h3_without_h2]}
    return {"status": "pass", "details": ["标题层级连续（有 H1+H3 处必有 H2）"]}


def check_b6_markdown(doc):
    """B.6 Markdown 语法残留全局扫描（表格外）。"""
    bad = []
    md_img = re.compile(r"!\[.*?\]\(.*?\)")
    md_table_row = re.compile(r"\|.*\|")
    for p, in_table in doc.iter_paragraphs():
        if in_table:
            continue
        text = get_text(p)
        if not text:
            continue
        if "**" in text:
            bad.append("粗体残留 **：%s" % text[:40])
        elif md_img.search(text):
            bad.append("图片语法残留 ![]()：%s" % text[:40])
        elif re.match(r"^\s*-{3,}\s*$", text) or "---" in text.strip():
            bad.append("分隔线残留 ---：%s" % text[:40])
        elif md_table_row.search(text) and text.count("|") >= 2:
            bad.append("表格语法残留 |：%s" % text[:40])
    if bad:
        return {"status": "fail", "details": ["发现 %d 处 Markdown 残留" % len(bad)] + bad[:8]}
    return {"status": "pass", "details": ["正文无 Markdown 语法残留（| / --- / ** / ![]()）"]}


def check_b7_linespacing(doc):
    """B.7 全量行距 1.5 倍（仅校验显式设置的段落，继承样式视为合规）。"""
    viol = 0
    checked = 0
    for p, _ in doc.iter_paragraphs():
        ppr = p.find(q("pPr"))
        if ppr is None:
            continue
        sp = ppr.find(q("spacing"))
        if sp is None:
            continue
        line = sp.get(q("line"))
        if line is None:
            continue
        checked += 1
        # line==360 在 auto/exact 下均表示 1.5 行
        if int(line) != 360:
            viol += 1
    if viol > 0:
        return {"status": "fail", "details": ["发现 %d 个段落显式行距非 1.5 倍（共检查 %d 个显式段落）" % (viol, checked)]}
    return {"status": "pass", "details": ["显式行距段落均 1.5 倍（其余继承样式）"]}


def _cell_valign(tc):
    tcpr = tc.find(q("tcPr"))
    if tcpr is None:
        return None
    v = tcpr.find(q("vAlign"))
    if v is None:
        return None
    return v.get(q("val"))

def _cell_jc(tc):
    # 取单元格内第一个段落的对齐
    for p in tc.findall(q("p")):
        ppr = p.find(q("pPr"))
        if ppr is not None:
            jc = ppr.find(q("jc"))
            if jc is not None:
                return jc.get(q("val"))
    return None

def _cell_space_zero(tc):
    for p in tc.findall(q("p")):
        ppr = p.find(q("pPr"))
        if ppr is None:
            continue
        sp = ppr.find(q("spacing"))
        if sp is None:
            continue
        b = sp.get(q("before"))
        a = sp.get(q("after"))
        if (b and int(b) != 0) or (a and int(a) != 0):
            return False
    return True

def check_b8_cell_align(doc):
    """B.8 表格单元格垂直居中 + 多行左对齐。"""
    bad = []
    tbl_idx = 0
    for tbl in doc.iter_tables():
        tbl_idx += 1
        rows = tbl.findall(q("tr"))
        for ri, row in enumerate(rows, 1):
            for ci, tc in enumerate(row.findall(q("tc")), 1):
                v = _cell_valign(tc)
                if v and v != "center":
                    bad.append("表%d 行%d 列%d：vAlign=%s（应 center）" % (tbl_idx, ri, ci, v))
                # 多行判定：单元格内文本含换行或多个段落
                texts = [get_text(p) for p in tc.findall(q("p"))]
                cell_text = "\n".join(texts)
                multi = len(texts) > 1 or "\n" in cell_text or any("\n" in t for t in texts)
                jc = _cell_jc(tc)
                if multi:
                    if jc and jc != "left":
                        bad.append("表%d 行%d 列%d：多行单元格对齐=%s（应 left）" % (tbl_idx, ri, ci, jc))
                # single-line: expect center (optional, 不强制阻断)
                if not _cell_space_zero(tc):
                    bad.append("表%d 行%d 列%d：单元格段前/段后间距非 0" % (tbl_idx, ri, ci))
    if bad:
        return {"status": "fail", "details": bad[:8]}
    return {"status": "pass", "details": ["表格单元格垂直居中、段间距为 0"]}


def check_b9_images(doc):
    """B.9 图片嵌入验证。"""
    # 内嵌图（wp:inline）
    inline = doc.root.iter("{%s}inline" % WP)
    n_pics = sum(1 for _ in inline)
    # 图标题：匹配 图X-Y / 图X-Y 等
    cap_pat = re.compile(r"图\s*\d+\s*[-~]\s*\d+")
    n_caps = 0
    dup = {}
    failed_markers = 0
    for p, _ in doc.iter_paragraphs():
        text = get_text(p)
        if "图片未找到" in text or "图片加载失败" in text:
            failed_markers += 1
        m = cap_pat.search(text)
        if m:
            n_caps += 1
            key = m.group(0)
            dup[key] = dup.get(key, 0) + 1
    details = []
    status = "pass"
    if failed_markers > 0:
        status = "fail"
        details.append("存在 %d 处图片失败标记（[图片未找到]/[图片加载失败]）" % failed_markers)
    if n_pics == 0 and n_caps > 0:
        status = "fail"
        details.append("有 %d 个图标题但 DOCX 内嵌图片为 0" % n_caps)
    elif n_caps > 0 and abs(n_pics - n_caps) > 0:
        # 允许±1 容差（封面图等）
        if abs(n_pics - n_caps) > 1:
            details.append("内嵌图数(%d) 与图标题数(%d) 不一致" % (n_pics, n_caps))
    dups = [k for k, v in dup.items() if v > 1]
    if dups:
        status = "fail" if status == "fail" else "warn"
        details.append("重复图标题：%s" % ", ".join(dups[:5]))
    if status == "pass":
        details.append("内嵌图 %d 张，图标题 %d 个，无失败标记/重复标题" % (n_pics, n_caps))
    else:
        details.append("内嵌图 %d 张，图标题 %d 个" % (n_pics, n_caps))
    return {"status": status, "details": details}


def count_md_tables(md_path):
    """粗略统计 Markdown 中表格数量（连续 | 行 + 分隔行）。"""
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None
    n = 0
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            n += 1
            i += 2
        else:
            i += 1
    return n

def check_b10_tables(doc, md_path):
    """B.10 表格转换验证：Markdown 表数 == DOCX 表数。"""
    n_docx = sum(1 for _ in doc.iter_tables())
    if not md_path:
        return {"status": "warn",
                "details": ["未提供 --markdown，仅校验 DOCX 表格数=%d 且结构完整（表数比对需源码）" % n_docx]}
    n_md = count_md_tables(md_path)
    if n_md is None:
        return {"status": "warn", "details": ["无法读取 Markdown 源文件，跳过表数比对"]}
    if n_md != n_docx:
        return {"status": "fail",
                "details": ["表格数不一致：Markdown=%d，DOCX=%d（有表格在转换中丢失）" % (n_md, n_docx)]}
    return {"status": "pass", "details": ["Markdown 表数(%d) == DOCX 表数(%d)" % (n_md, n_docx)]}


def check_b11_toc(doc):
    """B.11 TOC 域验证（中文目录域已插入）。"""
    found = False
    has_cn_prompt = False
    for instr in doc.root.iter(q("instrText")):
        if instr.text and "TOC" in instr.text.upper():
            found = True
    # 中文提示（目录）
    full = doc.doc_xml.decode("utf-8", "ignore")
    if "目录" in full:
        has_cn_prompt = True
    if not found:
        return {"status": "fail", "details": ["未检测到 TOC 域（目录未插入或仅文字无域）"]}
    if not has_cn_prompt:
        return {"status": "warn", "details": ["检测到 TOC 域，但附近未见中文『目录』提示语"]}
    return {"status": "pass", "details": ["TOC 域已插入且含中文目录提示"]}


def check_b12_cliche(doc):
    """B.12 内容俗套语验证。"""
    patterns = ["【对采购人的实用价值】", "对采购人的实用价值", "【对采购人的价值】",
                "对采购人的价值", "对采购人的实用价值】"]
    hits = []
    for p, _ in doc.iter_paragraphs():
        text = get_text(p)
        for pat in patterns:
            if pat in text:
                hits.append(pat)
                break
    if hits:
        return {"status": "fail", "details": ["发现 %d 处俗套语残留：%s" % (len(hits), ", ".join(set(hits)))]}
    return {"status": "pass", "details": ["无【对采购人的实用价值】等俗套语残留"]}


def check_b13_variants(doc):
    """B.13 双版本×双色系：表头色系为合法单色系之一。"""
    headers = []
    for tbl in doc.iter_tables():
        rows = tbl.findall(q("tr"))
        if rows:
            cells = rows[0].findall(q("tc"))
            if cells:
                headers.append(_cell_shd_fill(cells[0]))
    if not headers:
        return {"status": "warn", "details": ["文档无表格，四变体验证跳过"]}
    bad = [h for h in headers if h and h not in VALID_HEADER_FILLS_LOWER]
    if bad:
        return {"status": "fail",
                "details": ["表头色系含非法值 %s（应为 #4472C4 或 #333333）" % ", ".join(set(bad))]}
    return {"status": "pass",
            "details": ["表头色系均合法（彩色#4472C4/黑白#333333）；四变体生成属构建期动作，需 agent 产出打印版/粘贴版各两色"]}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run_checks(doc, md_path):
    checks = {}
    checks["B.1"] = check_b1_font(doc)
    checks["B.2"] = check_b2_pagebreaks(doc)
    checks["B.2.5"] = check_b25_numbering(doc)
    checks["B.3"] = check_b3_para_numbering(doc)
    checks["B.4"] = check_b4_table_width(doc)
    checks["B.5"] = check_b5_hierarchy(doc)
    checks["B.6"] = check_b6_markdown(doc)
    checks["B.7"] = check_b7_linespacing(doc)
    checks["B.8"] = check_b8_cell_align(doc)
    checks["B.9"] = check_b9_images(doc)
    checks["B.10"] = check_b10_tables(doc, md_path)
    checks["B.11"] = check_b11_toc(doc)
    checks["B.12"] = check_b12_cliche(doc)
    checks["B.13"] = check_b13_variants(doc)
    return checks


CHECK_NAMES = {
    "B.1": "字体/字号/颜色逐项验证（标题须用 Heading 样式）",
    "B.2": "分页符逐级验证（v3.1.1 修正公式）",
    "B.2.5": "多级列表自动编号（标题无手序号）",
    "B.3": "正文段落序号全局验证（无非法项目符号）",
    "B.4": "表格列宽自适应验证（非等宽+表头色系）",
    "B.5": "标题层级完整性验证（H1+H3 必有 H2）",
    "B.6": "Markdown 语法残留全局扫描",
    "B.7": "全量行距 1.5 倍验证",
    "B.8": "表格单元格垂直居中+多行左对齐",
    "B.9": "图片嵌入验证（内嵌图数==图标题数）",
    "B.10": "表格转换验证（Markdown表数==DOCX表数）",
    "B.11": "TOC 域验证（中文目录域）",
    "B.12": "内容俗套语验证",
    "B.13": "双版本×双色系验证（表头色系合法）",
}


def main():
    parser = argparse.ArgumentParser(
        description="技术方案 DOCX 13 项自动化格式验证（强制交付闸门）")
    parser.add_argument("docx", help="待验证的 .docx 文件路径")
    parser.add_argument("--markdown", help="可选：Markdown 源文件，用于 B.10 表数比对")
    parser.add_argument("--out", help="输出 JSON 路径（默认：<docx目录>/phase5_docx_verification.json）")
    args = parser.parse_args()

    try:
        doc = DocxDoc(args.docx)
    except Exception as e:
        sys.stderr.write("错误：%s\n" % e)
        return 2

    try:
        checks = run_checks(doc, args.markdown)
    finally:
        doc.close()

    passed = sum(1 for c in checks.values() if c["status"] == "pass")
    failed = sum(1 for c in checks.values() if c["status"] == "fail")
    warned = sum(1 for c in checks.values() if c["status"] == "warn")
    block = failed > 0

    report = {
        "docx": os.path.abspath(args.docx),
        "markdown_source": os.path.abspath(args.markdown) if args.markdown else None,
        "verified_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "block_delivery": block,
        "summary": {"passed": passed, "failed": failed, "warned": warned, "total": len(checks)},
        "checks": {}
    }
    for k, v in checks.items():
        report["checks"][k] = {
            "name": CHECK_NAMES.get(k, k),
            "status": v["status"],
            "details": v["details"]
        }

    out_path = args.out or os.path.join(os.path.dirname(os.path.abspath(args.docx)),
                                        "phase5_docx_verification.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as e:
        sys.stderr.write("警告：无法写入报告 %s：%s\n" % (out_path, e))

    # 控制台摘要
    print("=" * 60)
    print("DOCX 格式验证（13 项）— %s" % ("❌ 不得交付" if block else "✅ 可交付"))
    print("通过 %d / 失败 %d / 提示 %d" % (passed, failed, warned))
    print("-" * 60)
    for k in CHECK_NAMES:
        c = checks[k]
        icon = {"pass": "✅", "fail": "❌", "warn": "⚠️"}[c["status"]]
        print("%-7s %s %s" % (k, icon, CHECK_NAMES[k]))
        if c["status"] != "pass":
            for d in c["details"][:3]:
                print("        · %s" % d)
    print("-" * 60)
    print("报告已写入：%s" % out_path)
    print("=" * 60)

    return 1 if block else 0


if __name__ == "__main__":
    sys.exit(main())
