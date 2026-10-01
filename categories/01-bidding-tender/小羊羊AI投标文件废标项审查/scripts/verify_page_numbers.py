#!/usr/bin/env python3
"""
投标文件目录页码与正文一致性验证工具

功能：
1. 读取docx文件，提取目录中的章节标题和页码
2. 将docx转为PDF，提取每页的实际文字内容
3. 交叉比对：目录说第X页是某章节，验证PDF第X页确实包含该内容
4. 同时检查评分索引表、偏离表中的页码引用
5. 输出比对结果报告

用法：
    python verify_page_numbers.py <docx_path> [--output report.md] [--pdf-path output.pdf] [--tolerance 1]

依赖：
    pip install python-docx pdfplumber pywin32
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    import docx
    from docx.document import Document
    from docx.oxml.ns import qn
except ImportError:
    print("错误：未安装python-docx，请运行 pip install python-docx")
    sys.exit(1)

try:
    import pdfplumber
except ImportError:
    print("错误：未安装pdfplumber，请运行 pip install pdfplumber")
    sys.exit(1)


# ============================================================
# Part 1: 从docx提取目录信息
# ============================================================

def extract_toc_entries(doc):
    """
    从docx中提取目录条目。
    优先读取Word自动生成的TOC字段，fallback到按段落样式识别。
    返回: [{"title": "投标函", "page": 5, "level": 1}, ...]
    """
    toc_entries = []
    
    # 方法1: 尝试读取Word的TOC字段 (域代码)
    for para in doc.paragraphs:
        # 检查是否包含TOC字段
        for run in para.runs:
            fld_codes = run._element.findall(qn('w:fldChar'))
            # Word TOC通常存储为域代码，但python-docx可能无法直接读取
        
        # 方法2: 通过段落样式识别目录行
        style_name = para.style.name if para.style else ""
        text = para.text.strip()
        if not text:
            continue
        
        # 匹配目录样式
        is_toc_style = any([
            "TOC" in style_name.upper(),
            "toc" in style_name,
            style_name.startswith("TOC"),
            "目录" in style_name,
        ])
        
        if is_toc_style:
            entry = parse_toc_line(text, style_name)
            if entry:
                toc_entries.append(entry)
    
    # 方法3: 如果没有找到TOC样式段落，尝试通过文本模式识别目录
    if not toc_entries:
        toc_entries = extract_toc_by_pattern(doc)
    
    return toc_entries


def parse_toc_line(text, style_name=""):
    """
    解析单行目录文本，提取标题和页码。
    支持格式：
    - "投标函....................5"
    - "投标函  5"
    - "1. 投标函  5"
    - "投标函	5" (tab分隔)
    """
    # 提取页码：行末的数字
    page_match = re.search(r'[\.\s\t…·]+(\d{1,5})\s*$', text)
    if not page_match:
        # 尝试 tab+数字 格式
        page_match = re.search(r'\t(\d{1,5})\s*$', text)
    if not page_match:
        # 尝试空格+数字 格式
        page_match = re.search(r'\s{2,}(\d{1,5})\s*$', text)
    
    if not page_match:
        return None
    
    page = int(page_match.group(1))
    # 提取标题：去掉页码部分
    title = text[:page_match.start()].strip()
    # 去掉前导的点号/制表符
    title = re.sub(r'^[\.\s\t…·]+', '', title).strip()
    
    if not title:
        return None
    
    # 提取层级
    level = 1
    level_match = re.match(r'^(\d+(\.\d+)*)\s*', title)
    if level_match:
        num_parts = level_match.group(1).split('.')
        level = len(num_parts)
    
    return {"title": title, "page": page, "level": level, "raw": text}


def extract_toc_by_pattern(doc):
    """
    当没有TOC样式时，通过文本模式识别目录。
    寻找连续的"标题...页码"格式的段落。
    """
    toc_entries = []
    in_toc_section = False
    toc_end_markers = ["第一章", "第一部分", "一、", "1.", "1 "]
    
    for i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
        
        # 检测目录开始
        if not in_toc_section:
            if re.search(r'^目\s*录', text) or re.search(r'^Table\s+of\s+Contents', text, re.IGNORECASE):
                in_toc_section = True
                continue
        
        if in_toc_section:
            # 检测目录结束：遇到正文标题
            if any(text.startswith(marker) for marker in toc_end_markers):
                # 需要区分：如果是"1. 投标函  5"这种格式，仍是目录
                if not re.search(r'\d{1,5}\s*$', text) or len(text) > 50:
                    break
            
            entry = parse_toc_line(text)
            if entry:
                toc_entries.append(entry)
    
    return toc_entries


# ============================================================
# Part 2: 提取评分索引表/偏离表中的页码引用
# ============================================================

def extract_index_references(doc):
    """
    从docx表格中提取评分索引表、偏离表、响应表中的页码引用。
    返回: [{"table_name": "评分索引表", "row": 2, "content": "投标函", "page_ref": 5}, ...]
    """
    references = []
    
    for table_idx, table in enumerate(doc.tables):
        # 读取表头，判断表格类型
        headers = []
        if table.rows:
            for cell in table.rows[0].cells:
                header_text = cell.text.strip()
                headers.append(header_text)
        
        header_str = " ".join(headers)
        
        # 判断表格类型
        table_type = None
        if any(kw in header_str for kw in ["索引", "页码", "所在页"]):
            table_type = "评分索引表"
        elif any(kw in header_str for kw in ["偏离", "偏差"]):
            table_type = "偏离表"
        elif any(kw in header_str for kw in ["响应", "符合"]):
            table_type = "响应表"
        
        if not table_type:
            continue
        
        # 提取页码引用
        # 找到包含"页码"或"页"的列
        page_col = -1
        content_col = -1
        for col_idx, header in enumerate(headers):
            if re.search(r'页码|所在页|页数|位置|页$', header):
                page_col = col_idx
            if re.search(r'内容|项目|条款|评审|评分', header):
                content_col = col_idx
        
        if page_col == -1:
            # 遍历所有列，找包含纯数字的列
            for col_idx, header in enumerate(headers):
                if "页" in header:
                    page_col = col_idx
                    break
        
        if page_col == -1:
            continue
        
        # 提取每行的页码引用
        for row_idx, row in enumerate(table.rows):
            if row_idx == 0:
                continue  # 跳过表头
            
            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) <= page_col:
                continue
            
            page_text = cells[page_col]
            content_text = cells[content_col] if content_col >= 0 and content_col < len(cells) else ""
            
            # 提取页码数字
            page_nums = re.findall(r'\d{1,5}', page_text)
            for pn in page_nums:
                references.append({
                    "table_name": table_type,
                    "table_index": table_idx,
                    "row": row_idx + 1,
                    "content": content_text or "、".join(cells[:3]),
                    "page_ref": int(pn),
                    "raw_page_text": page_text
                })
    
    return references


# ============================================================
# Part 3: 将docx转为PDF
# ============================================================

def docx_to_pdf(docx_path, pdf_path=None):
    """
    使用Windows COM将docx转为PDF。
    返回PDF文件路径。
    """
    if pdf_path is None:
        pdf_path = str(Path(docx_path).with_suffix('.pdf'))
    
    if os.path.exists(pdf_path):
        print(f"  PDF已存在，直接使用: {pdf_path}")
        return pdf_path
    
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = False
        
        doc = word.Documents.Open(os.path.abspath(docx_path))
        doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)  # 17 = PDF
        doc.Close()
        word.Quit()
        
        print(f"  PDF已生成: {pdf_path}")
        return pdf_path
        
    except ImportError:
        print("  警告：未安装pywin32，尝试其他方式...")
        return docx_to_pdf_libreoffice(docx_path, pdf_path)
    except Exception as e:
        print(f"  Word COM转换失败: {e}")
        return docx_to_pdf_libreoffice(docx_path, pdf_path)


def docx_to_pdf_libreoffice(docx_path, pdf_path=None):
    """
    使用LibreOffice命令行将docx转为PDF（fallback方案）。
    """
    if pdf_path is None:
        pdf_path = str(Path(docx_path).with_suffix('.pdf'))
    
    if os.path.exists(pdf_path):
        return pdf_path
    
    # 尝试常见的LibreOffice路径
    lo_paths = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    
    lo_path = None
    for p in lo_paths:
        if os.path.exists(p):
            lo_path = p
            break
    
    if not lo_path:
        print("  错误：未找到Word或LibreOffice，无法转换PDF")
        return None
    
    import subprocess
    output_dir = str(Path(pdf_path).parent)
    cmd = [lo_path, "--headless", "--convert-to", "pdf", "--outdir", output_dir, docx_path]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        if os.path.exists(pdf_path):
            print(f"  PDF已生成(LibreOffice): {pdf_path}")
            return pdf_path
    except Exception as e:
        print(f"  LibreOffice转换失败: {e}")
    
    return None


# ============================================================
# Part 4: 从PDF提取每页内容
# ============================================================

def extract_pdf_pages(pdf_path):
    """
    从PDF中提取每页的文字内容。
    返回: [{"page": 1, "text": "...", "first_line": "...", "headings": [...]}, ...]
    """
    pages = []
    
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"  PDF共{total}页")
        
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            
            # 提取该页的标题/关键字行
            headings = []
            for line in lines[:5]:  # 只看前5行
                # 检测标题模式
                if re.match(r'^(\d+(\.\d+)*)\s+\S', line):
                    headings.append(line)
                elif re.match(r'^第[一二三四五六七八九十]+[章节部分]', line):
                    headings.append(line)
                elif re.match(r'^[一二三四五六七八九十]+[、．.]\s*\S', line):
                    headings.append(line)
            
            first_line = lines[0] if lines else ""
            
            pages.append({
                "page": i + 1,
                "text": text,
                "first_line": first_line,
                "headings": headings,
                "text_length": len(text)
            })
    
    return pages


# ============================================================
# Part 5: 交叉比对
# ============================================================

def compare_toc_with_pages(toc_entries, pdf_pages, tolerance=1):
    """
    比对目录页码与PDF实际内容。
    
    tolerance: 允许的页码偏差（默认1页，因为排版差异）
    """
    results = []
    
    for entry in toc_entries:
        expected_page = entry["page"]
        title = entry["title"]
        
        # 在预期页码附近搜索
        found = False
        match_detail = ""
        
        search_range = range(
            max(0, expected_page - 1 - tolerance),
            min(len(pdf_pages), expected_page + tolerance)
        )
        
        for pg_idx in search_range:
            if pg_idx >= len(pdf_pages):
                continue
            
            page = pdf_pages[pg_idx]
            page_num = page["page"]
            page_text = page["text"]
            
            # 提取标题关键词用于模糊匹配
            title_keywords = extract_title_keywords(title)
            
            if title_keywords and any(kw in page_text for kw in title_keywords):
                found = True
                actual_page = page_num
                page_offset = actual_page - expected_page
                
                if page_offset == 0:
                    status = "✅ 一致"
                elif abs(page_offset) <= tolerance:
                    status = "⚠️ 偏差"
                else:
                    status = "❌ 不一致"
                
                match_detail = f"在PDF第{actual_page}页找到（偏差{page_offset:+d}页）"
                break
        
        if not found:
            status = "❌ 未找到"
            actual_page = None
            match_detail = f"在PDF第{expected_page - tolerance}-{expected_page + tolerance}页均未找到对应内容"
        
        results.append({
            "toc_title": title,
            "toc_page": expected_page,
            "actual_page": actual_page,
            "status": status,
            "detail": match_detail,
            "level": entry.get("level", 1)
        })
    
    return results


def compare_index_with_pages(index_refs, pdf_pages, tolerance=1):
    """
    比对评分索引表/偏离表中的页码引用与PDF实际内容。
    """
    results = []
    
    for ref in index_refs:
        expected_page = ref["page_ref"]
        content = ref["content"]
        
        # 在预期页码附近搜索
        found = False
        match_detail = ""
        
        search_range = range(
            max(0, expected_page - 1 - tolerance),
            min(len(pdf_pages), expected_page + tolerance)
        )
        
        for pg_idx in search_range:
            if pg_idx >= len(pdf_pages):
                continue
            
            page = pdf_pages[pg_idx]
            page_num = page["page"]
            page_text = page["text"]
            
            # 提取内容关键词
            content_keywords = extract_title_keywords(content)
            
            if content_keywords and any(kw in page_text for kw in content_keywords):
                found = True
                actual_page = page_num
                page_offset = actual_page - expected_page
                
                if page_offset == 0:
                    status = "✅ 一致"
                elif abs(page_offset) <= tolerance:
                    status = "⚠️ 偏差"
                else:
                    status = "❌ 不一致"
                
                match_detail = f"在PDF第{actual_page}页找到（偏差{page_offset:+d}页）"
                break
        
        if not found:
            status = "⚠️ 待确认"
            actual_page = None
            match_detail = f"在PDF第{expected_page - tolerance}-{expected_page + tolerance}页未找到明确对应内容（可能需要人工确认）"
        
        results.append({
            "table_name": ref["table_name"],
            "row": ref["row"],
            "content": content,
            "ref_page": expected_page,
            "actual_page": actual_page,
            "status": status,
            "detail": match_detail
        })
    
    return results


def extract_title_keywords(title):
    """
    从标题中提取关键词用于模糊匹配。
    去掉序号、标点，保留核心词。
    """
    # 去掉前导序号
    cleaned = re.sub(r'^(\d+(\.\d+)*)\s*', '', title)
    cleaned = re.sub(r'^第[一二三四五六七八九十]+[章节部分]\s*', '', cleaned)
    cleaned = re.sub(r'^[一二三四五六七八九十]+[、．.]\s*', '', cleaned)
    
    # 去掉常见标点
    cleaned = re.sub(r'[：:，,、。.\s]+', '', cleaned)
    
    if len(cleaned) < 2:
        return []
    
    # 生成关键词（2-4字的滑动窗口）
    keywords = []
    if len(cleaned) <= 6:
        keywords.append(cleaned)
    else:
        # 取前4字+后4字+中间4字
        keywords.append(cleaned[:4])
        keywords.append(cleaned[-4:])
        if len(cleaned) > 8:
            mid = len(cleaned) // 2
            keywords.append(cleaned[mid-2:mid+2])
    
    return [kw for kw in keywords if len(kw) >= 2]


# ============================================================
# Part 6: 检查PDF页码连续性
# ============================================================

def check_page_continuity(pdf_pages):
    """
    检查PDF页面是否有连续性问题（空白页、内容异常少的页面）。
    """
    issues = []
    
    avg_length = sum(p["text_length"] for p in pdf_pages) / max(len(pdf_pages), 1)
    
    for i, page in enumerate(pdf_pages):
        # 检测空白页
        if page["text_length"] == 0:
            issues.append({
                "page": page["page"],
                "type": "空白页",
                "detail": f"第{page['page']}页无任何文字内容"
            })
        
        # 检测内容异常少的页面（可能是页码被图片覆盖）
        elif page["text_length"] < avg_length * 0.1 and avg_length > 100:
            issues.append({
                "page": page["page"],
                "type": "内容稀疏",
                "detail": f"第{page['page']}页内容极少({page['text_length']}字)，可能被大图覆盖"
            })
    
    return issues


# ============================================================
# Part 7: 生成报告
# ============================================================

def generate_report(toc_results, index_results, continuity_issues, docx_path, pdf_path, tolerance):
    """生成Markdown格式的比对报告"""
    
    lines = []
    lines.append("# 投标文件目录页码一致性验证报告\n")
    lines.append(f"## 基本信息\n")
    lines.append(f"- 投标文件：`{os.path.basename(docx_path)}`")
    lines.append(f"- PDF文件：`{os.path.basename(pdf_path)}`")
    lines.append(f"- 允许偏差：{tolerance}页")
    lines.append("")
    
    # 目录比对结果
    lines.append("## 一、目录页码验证\n")
    if not toc_results:
        lines.append("> 未检测到目录条目，跳过目录验证\n")
    else:
        pass_count = sum(1 for r in toc_results if "一致" in r["status"] and "不" not in r["status"])
        warn_count = sum(1 for r in toc_results if "偏差" in r["status"])
        fail_count = sum(1 for r in toc_results if "不一致" in r["status"] or "未找到" in r["status"])
        
        lines.append(f"**总条目：{len(toc_results)} | ✅ 一致：{pass_count} | ⚠️ 偏差：{warn_count} | ❌ 不一致/未找到：{fail_count}**\n")
        
        lines.append("| 目录标题 | 目录页码 | 实际页码 | 状态 | 说明 |")
        lines.append("|---------|---------|---------|------|------|")
        
        for r in toc_results:
            actual = str(r["actual_page"]) if r["actual_page"] else "-"
            lines.append(f"| {r['toc_title']} | {r['toc_page']} | {actual} | {r['status']} | {r['detail']} |")
    
    lines.append("")
    
    # 索引表比对结果
    lines.append("## 二、评分索引表/偏离表页码验证\n")
    if not index_results:
        lines.append("> 未检测到评分索引表/偏离表中的页码引用，跳过\n")
    else:
        pass_count = sum(1 for r in index_results if "一致" in r["status"] and "不" not in r["status"])
        warn_count = sum(1 for r in index_results if "偏差" in r["status"] or "待确认" in r["status"])
        fail_count = sum(1 for r in index_results if "不一致" in r["status"])
        
        lines.append(f"**总引用：{len(index_results)} | ✅ 一致：{pass_count} | ⚠️ 偏差/待确认：{warn_count} | ❌ 不一致：{fail_count}**\n")
        
        lines.append("| 表格名称 | 行号 | 引用内容 | 引用页码 | 实际页码 | 状态 | 说明 |")
        lines.append("|---------|------|---------|---------|---------|------|------|")
        
        for r in index_results:
            actual = str(r["actual_page"]) if r["actual_page"] else "-"
            lines.append(f"| {r['table_name']} | {r['row']} | {r['content'][:20]} | {r['ref_page']} | {actual} | {r['status']} | {r['detail']} |")
    
    lines.append("")
    
    # 页码连续性
    lines.append("## 三、页面连续性检查\n")
    if not continuity_issues:
        lines.append("✅ 未发现空白页或内容异常稀疏的页面\n")
    else:
        lines.append(f"**发现问题：{len(continuity_issues)}项**\n")
        lines.append("| 页码 | 问题类型 | 说明 |")
        lines.append("|------|---------|------|")
        for issue in continuity_issues:
            lines.append(f"| {issue['page']} | {issue['type']} | {issue['detail']} |")
    
    lines.append("")
    
    # 风险总结
    lines.append("## 四、废标风险提示\n")
    
    critical_issues = [r for r in toc_results if "不一致" in r["status"] or "未找到" in r["status"]]
    warning_issues = [r for r in toc_results if "偏差" in r["status"]]
    index_critical = [r for r in index_results if "不一致" in r["status"]]
    
    if critical_issues:
        lines.append("### ❌ 高风险（可能导致废标）\n")
        for r in critical_issues:
            lines.append(f"- 目录「{r['toc_title']}」标注第{r['toc_page']}页，{r['detail']}")
        lines.append("")
    
    if index_critical:
        lines.append("### ❌ 高风险 - 索引页码错误（虚假承诺风险）\n")
        for r in index_critical:
            lines.append(f"- {r['table_name']}第{r['row']}行「{r['content'][:20]}」引用第{r['ref_page']}页，{r['detail']}")
        lines.append("")
    
    if warning_issues:
        lines.append("### ⚠️ 中风险（需人工确认）\n")
        for r in warning_issues:
            lines.append(f"- 目录「{r['toc_title']}」标注第{r['toc_page']}页，{r['detail']}")
        lines.append("")
    
    if continuity_issues:
        lines.append("### ⚠️ 页面异常\n")
        for issue in continuity_issues:
            if issue["type"] == "空白页":
                lines.append(f"- 第{issue['page']}页为空白页，可能是排版错误或页码缺失")
            elif issue["type"] == "内容稀疏":
                lines.append(f"- 第{issue['page']}页内容极少，可能有页码被大图覆盖的风险")
        lines.append("")
    
    if not critical_issues and not warning_issues and not index_critical and not continuity_issues:
        lines.append("✅ **恭喜！未发现目录页码一致性问题，投标文件页码结构完整。**\n")
    
    lines.append("---")
    lines.append("*本报告由投标文件目录页码验证工具自动生成，仅提供参考，最终以人工翻查确认为准。*")
    
    return "\n".join(lines)


# ============================================================
# Main
# ============================================================

def extract_toc_from_pdf(pdf_pages, max_page=None):
    """
    从PDF页面中直接提取目录信息。
    在docx无法打开时使用（如超大文件）。
    扫描前N页，寻找"目录"关键字，然后提取目录行。
    max_page: 最大合法页码（超过此值的视为误报，通常为PDF总页数）
    """
    if max_page is None:
        max_page = len(pdf_pages)
    
    toc_entries = []
    in_toc = False
    toc_end_page = 5  # 目录通常在前5页内
    
    for page in pdf_pages[:20]:  # 只看前20页
        text = page["text"]
        if not text:
            continue
        
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        
        for line in lines:
            # 检测目录开始
            if not in_toc:
                if re.search(r'^目\s*录', line) or re.search(r'^Table\s+of\s+Contents', line, re.IGNORECASE):
                    in_toc = True
                    continue
            
            if in_toc:
                # 尝试解析目录行
                entry = parse_toc_line(line)
                if entry and entry["page"] <= max_page:
                    # 过滤明显不合理的页码（如报价表数字被误识别为页码）
                    toc_entries.append(entry)
                elif entry and entry["page"] > max_page:
                    # 超过PDF总页数的"页码"，是报价表等数据的误识别，跳过
                    pass
                # 简单判断目录结束：遇到明显的正文标题
                elif len(line) > 20 and not re.search(r'\d{1,5}\s*$', line):
                    # 可能是正文开始了
                    if re.match(r'^第[一二三四五六七八九十]+[章节]', line) or re.match(r'^\d+\.\d+\s+\S', line):
                        if toc_entries:  # 如果已经找到目录条目，说明目录结束了
                            in_toc = False
                            break
    
    return toc_entries


def extract_index_from_pdf(pdf_pages):
    """
    从PDF页面中提取评分索引表/偏离表中的页码引用。
    简化版：扫描所有页面，找到包含"索引""偏离"关键词的表格区域，
    提取"见第X页"等页码引用模式。
    """
    references = []
    
    for page in pdf_pages:
        text = page["text"]
        if not text:
            continue
        
        # 检测索引表/偏离表关键词
        table_name = None
        if "索引" in text and "页码" in text:
            table_name = "评分索引表"
        elif "偏离" in text and "页码" in text:
            table_name = "偏离表"
        elif "响应" in text and "页码" in text:
            table_name = "响应表"
        
        if not table_name:
            continue
        
        # 提取"见第X页"、"第X页"等页码引用
        page_refs = re.finditer(r'(?:见|在第?|于第?|P\.?|页)\s*(\d{1,5})\s*页?', text)
        for match in page_refs:
            page_num = int(match.group(1))
            # 获取上下文
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 10)
            context = text[start:end].strip().replace('\n', ' ')
            
            references.append({
                "table_name": table_name,
                "page": page["page"],
                "content": context,
                "page_ref": page_num,
                "raw_page_text": match.group(0)
            })
    
    return references


def main():
    parser = argparse.ArgumentParser(description="投标文件目录页码与正文一致性验证工具")
    parser.add_argument("input_path", help="投标文件路径（docx或PDF）")
    parser.add_argument("--output", "-o", help="输出报告路径（默认：同目录下生成_页码验证报告.md）")
    parser.add_argument("--pdf-path", help="指定PDF路径（当输入为docx且需要指定对应PDF时）")
    parser.add_argument("--tolerance", type=int, default=1, help="允许的页码偏差（默认1页）")
    parser.add_argument("--pdf-only", action="store_true", help="纯PDF模式，直接从PDF提取目录和索引")
    
    args = parser.parse_args()
    
    input_path = os.path.abspath(args.input_path)
    if not os.path.exists(input_path):
        print(f"错误：文件不存在 - {input_path}")
        sys.exit(1)
    
    # 判断输入类型
    is_pdf_input = input_path.lower().endswith('.pdf')
    is_docx_input = input_path.lower().endswith(('.docx', '.doc'))
    
    # 输出路径
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        output_path = os.path.join(os.path.dirname(input_path), "页码验证报告.md")
    
    print("=" * 60)
    print("投标文件目录页码一致性验证工具")
    print("=" * 60)
    
    toc_entries = []
    index_refs = []
    docx_path = input_path
    pdf_path = None
    
    # Step 1: 提取目录信息
    print("\n[1/5] 提取目录信息...")
    
    if is_pdf_input or args.pdf_only:
        # 纯PDF模式
        pdf_path = input_path
        print(f"  模式：纯PDF分析")
        print(f"  PDF文件：{pdf_path}")
        
    elif is_docx_input:
        # 尝试读取docx
        try:
            doc = docx.Document(input_path)
            toc_entries = extract_toc_entries(doc)
            index_refs = extract_index_references(doc)
            print(f"  从docx提取：{len(toc_entries)} 条目录条目，{len(index_refs)} 条索引引用")
        except Exception as e:
            print(f"  docx读取失败({type(e).__name__})，将使用PDF模式提取目录")
            docx_path = input_path
        
        # 确定PDF路径
        if args.pdf_path and os.path.exists(args.pdf_path):
            pdf_path = os.path.abspath(args.pdf_path)
        else:
            # 尝试同名PDF
            candidate = str(Path(input_path).with_suffix('.pdf'))
            if os.path.exists(candidate):
                pdf_path = candidate
                print(f"  找到同名PDF：{pdf_path}")
    
    # Step 2: 提取PDF内容
    print("\n[2/5] 提取PDF内容...")
    if not pdf_path or not os.path.exists(pdf_path):
        # 尝试自动转换
        print("  未找到PDF，尝试从docx转换...")
        if is_docx_input:
            pdf_path = docx_to_pdf(input_path)
        
        if not pdf_path:
            print("  ⚠️ 无法获取PDF文件")
            print("  请手动将docx导出为PDF后，使用以下命令：")
            print(f'    python verify_page_numbers.py "{input_path}" --pdf-path "导出的.pdf"')
            print(f'  或直接传入PDF文件：')
            print(f'    python verify_page_numbers.py "投标文件.pdf"')
            sys.exit(1)
    
    pdf_pages = extract_pdf_pages(pdf_path)
    
    # Step 3: 从PDF补充目录信息（如果docx提取失败）
    print("\n[3/5] 提取目录和索引信息...")
    if not toc_entries:
        toc_entries = extract_toc_from_pdf(pdf_pages, max_page=len(pdf_pages))
        print(f"  从PDF提取目录：{len(toc_entries)} 条")
    else:
        print(f"  使用docx目录：{len(toc_entries)} 条")
    
    if not index_refs:
        index_refs = extract_index_from_pdf(pdf_pages)
        print(f"  从PDF提取索引引用：{len(index_refs)} 条")
    else:
        print(f"  使用docx索引引用：{len(index_refs)} 条")
    
    # Step 4: 交叉比对
    print("\n[4/5] 执行交叉比对...")
    toc_results = compare_toc_with_pages(toc_entries, pdf_pages, args.tolerance)
    index_results = compare_index_with_pages(index_refs, pdf_pages, args.tolerance)
    continuity_issues = check_page_continuity(pdf_pages)
    
    # Step 5: 生成报告
    print("\n[5/5] 生成报告...")
    report = generate_report(toc_results, index_results, continuity_issues, docx_path or input_path, pdf_path, args.tolerance)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    
    # 输出摘要
    toc_pass = sum(1 for r in toc_results if "一致" in r["status"] and "不" not in r["status"])
    toc_warn = sum(1 for r in toc_results if "偏差" in r["status"])
    toc_fail = sum(1 for r in toc_results if "不一致" in r["status"] or "未找到" in r["status"])
    
    idx_pass = sum(1 for r in index_results if "一致" in r["status"] and "不" not in r["status"])
    idx_warn = sum(1 for r in index_results if "偏差" in r["status"] or "待确认" in r["status"])
    idx_fail = sum(1 for r in index_results if "不一致" in r["status"])
    
    print(f"\n{'='*60}")
    print("验证结果摘要")
    print(f"{'='*60}")
    print(f"  目录验证：✅{toc_pass}  ⚠️{toc_warn}  ❌{toc_fail}  (共{len(toc_results)}条)")
    print(f"  索引验证：✅{idx_pass}  ⚠️{idx_warn}  ❌{idx_fail}  (共{len(index_results)}条)")
    print(f"  页面连续性：发现{len(continuity_issues)}个异常")
    print(f"\n报告已保存至: {output_path}")
    
    # 如果有问题，返回非零退出码
    if toc_fail > 0 or idx_fail > 0:
        sys.exit(2)
    elif toc_warn > 0 or idx_warn > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
