#!/usr/bin/env python3
"""
Markdown to DOCX converter for bid technical plans.
Correct heading mapping:
  #  [title]       → Title page elements
  ## [chapter]     → Heading 2 (二级标题: 2.1, 2.2, ...)
  ### [section]    → Heading 3 (三级标题: 2.1.1, 2.1.2, ...)
  #### [sub]       → Body text (四级: not a heading)
  
Heading 1 (一级标题) is auto-inserted based on chapter groupings:
  Sections 2.X → "二、实施方案"
  Sections 3.X → "三、售后服务保障"
  Chapter names come from bidding_profile.json scoring items.

Table formatting:
  - All cells: vertical center + horizontal center
  - Header row: dark blue (#4472C4) background, white text, bold
  - Data rows: 宋体 10.5pt
  - Column widths: auto-fit by content (not equal width)
  - No first-line indent in table cells

Usage:
  python md2docx.py <input_md> <output_docx> [--chapter-names "二、实施方案,三、售后服务保障"]
"""
import re, os, sys, json, argparse
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT as WD_CVA
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml, OxmlElement


def set_cell_shading(cell, color):
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)


def add_heading(doc, text, level):
    """Add heading with 宋体 font, black color."""
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = '宋体'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        run.font.color.rgb = RGBColor(0, 0, 0)
    return h


def add_body_para(doc, text, first_line_indent=True, bold=False):
    """Add body paragraph with Normal style."""
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = para.paragraph_format
    pf.line_spacing = 1.5
    pf.space_after = Pt(0)
    pf.space_before = Pt(0)
    if first_line_indent:
        pf.first_line_indent = Cm(0.74)
    run = para.add_run(text)
    run.font.name = '宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.font.size = Pt(12)
    run.font.bold = bold
    return para


def clean_markdown(text):
    """Remove markdown formatting."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    return text


def setup_document():
    """Create and configure a Word document."""
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.18)
    section.right_margin = Cm(3.18)
    
    # Normal style
    style = doc.styles['Normal']
    font = style.font
    font.name = '宋体'
    font.size = Pt(12)
    style.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    style.paragraph_format.line_spacing = 1.5
    
    # Heading styles
    for i in range(1, 4):
        hstyle = doc.styles[f'Heading {i}']
        hfont = hstyle.font
        hfont.name = '宋体'
        hstyle.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        hfont.bold = True
        hfont.color.rgb = RGBColor(0, 0, 0)
        hfont.size = Pt(18 - i * 2)  # H1:16pt, H2:14pt, H3:12pt
    
    return doc


def add_toc(doc):
    """Add a TOC field that Word can generate on open."""
    toc_title = doc.add_paragraph()
    toc_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = toc_title.add_run('目  录')
    run.font.name = '宋体'; run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.font.size = Pt(16); run.font.bold = True
    
    toc_para = doc.add_paragraph()
    run1 = toc_para.add_run()
    fld_begin = OxmlElement('w:fldChar'); fld_begin.set(qn('w:fldCharType'), 'begin')
    run1._r.append(fld_begin)
    
    run2 = toc_para.add_run()
    instr = OxmlElement('w:instrText'); instr.set(qn('xml:space'), 'preserve')
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    run2._r.append(instr)
    
    run3 = toc_para.add_run()
    fld_sep = OxmlElement('w:fldChar'); fld_sep.set(qn('w:fldCharType'), 'separate')
    run3._r.append(fld_sep)
    
    run4 = toc_para.add_run('（右键此处，选择"更新域"以生成目录）')
    run4.font.size = Pt(10.5); run4.font.color.rgb = RGBColor(128, 128, 128)
    
    run5 = toc_para.add_run()
    fld_end = OxmlElement('w:fldChar'); fld_end.set(qn('w:fldCharType'), 'end')
    run5._r.append(fld_end)
    
    doc.add_page_break()


def add_page_numbers(doc):
    """Add centered page numbers in footer."""
    for sec in doc.sections:
        footer = sec.footer
        footer.is_linked_to_previous = False
        footer_para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        for tag, attrs in [('begin', {}), ('instr', {'xml:space': 'preserve'}), ('end', {})]:
            run = footer_para.add_run()
            el = OxmlElement('w:fldChar' if tag != 'instr' else 'w:instrText')
            if tag == 'begin':
                el.set(qn('w:fldCharType'), 'begin')
            elif tag == 'end':
                el.set(qn('w:fldCharType'), 'end')
            else:
                el.set(qn('xml:space'), 'preserve')
                el.text = ' PAGE '
            run._r.append(el)
            run.font.name = '宋体'
            run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
            run.font.size = Pt(9)


def add_table_to_doc(doc, data_rows):
    """Add a properly formatted table to the document."""
    if not data_rows:
        return
    
    num_cols = max(len(r) for r in data_rows)
    table = doc.add_table(rows=len(data_rows), cols=num_cols)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    
    # Set table width to 100%
    tbl = table._tbl
    tblPr = tbl.tblPr if tbl.tblPr is not None else OxmlElement('w:tblPr')
    tblW = OxmlElement('w:tblW')
    tblW.set(qn('w:w'), '5000')
    tblW.set(qn('w:type'), 'pct')
    tblPr.append(tblW)
    
    for row_idx, row_data in enumerate(data_rows):
        for col_idx in range(num_cols):
            if col_idx < len(row_data):
                cell = table.cell(row_idx, col_idx)
                cell_text = clean_markdown(row_data[col_idx])
                cell.text = ''
                
                cell_para = cell.paragraphs[0]
                cell_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                cell_para.paragraph_format.first_line_indent = Pt(0)
                cell_para.paragraph_format.space_before = Pt(2)
                cell_para.paragraph_format.space_after = Pt(2)
                
                cell_run = cell_para.add_run(cell_text)
                cell_run.font.name = '宋体'
                cell_run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
                cell_run.font.size = Pt(10.5)
                
                # Vertical centering
                cell.vertical_alignment = WD_CVA.CENTER
                
                # Header row
                if row_idx == 0:
                    cell_run.font.bold = True
                    cell_run.font.color.rgb = RGBColor(255, 255, 255)
                    set_cell_shading(cell, '4472C4')


def convert_md_to_docx(md_path, output_path, chapter_names=None):
    """
    Convert Markdown to properly formatted DOCX.
    
    chapter_names: list of Heading 1 names, e.g. ['二、实施方案', '三、售后服务保障']
    Chapter breaks are detected by the first digit of section numbers (2.X → 2, 3.X → 3).
    """
    if chapter_names is None:
        chapter_names = []
    
    # Build chapter map from section number
    chapter_map = {}
    for cn in chapter_names:
        # Extract digit from "二、实施方案" → unknown, so use positional
        pass
    # Default: use positional assignment
    # sections starting with 2 → first chapter_name, 3 → second, etc.
    
    doc = setup_document()
    
    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # ---- PHASE 1: Title page ----
    title_lines = []
    for line in lines:
        if line.startswith('# '):
            title_lines.append(line.lstrip('#').strip())
        elif line.strip() == '---':
            break
    
    for _ in range(5):
        doc.add_paragraph()
    
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title_lines[0] if title_lines else '')
    run.font.name = '宋体'; run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    run.font.size = Pt(22); run.font.bold = True
    
    doc.add_paragraph()
    for tl in title_lines[1:]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(tl)
        run.font.name = '宋体'; run._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        run.font.size = Pt(14)
    
    doc.add_page_break()
    
    # ---- PHASE 2: TOC ----
    add_toc(doc)
    
    # ---- PHASE 3: Body ----
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip() == '---':
            body_start = i + 1
            break
    
    last_chapter_num = None
    chapter_idx = -1
    in_table = False
    table_lines = []
    just_page_broken = True  # TOC already added a page break
    first_h3_after_h2 = False  # First H3 under each H2 shares H2's page
    i = body_start

    def is_table_line(text):
        """Robust check: line contains at least two | chars, with content between them."""
        t = text.strip()
        return t.startswith('|') and t.endswith('|') and t.count('|') >= 2

    def flush_table():
        """Render any pending table before switching to non-table content."""
        nonlocal in_table, table_lines
        if in_table and table_lines:
            in_table = False
            if len(table_lines) >= 2:
                rows = []
                for tl in table_lines:
                    # Split by |, drop outer empty strings from leading/trailing |
                    cells = [c.strip() for c in tl.strip().strip('|').split('|')]
                    rows.append(cells)
                # Filter out separator rows (all cells are just - : or spaces)
                data_rows = [r for r in rows if not all(re.match(r'^[-:\s]+$', c.strip()) for c in r)]
                if data_rows:
                    add_table_to_doc(doc, data_rows)
            table_lines = []

    while i < len(lines):
        line = lines[i].rstrip()

        # Empty line: if inside a table, treat as table terminator (flush)
        if not line.strip():
            if in_table:
                flush_table()
            i += 1
            continue

        if line.strip() == '---':
            if in_table:
                flush_table()
            i += 1
            continue

        # CRITICAL: Flush pending table before any non-table line processing
        if in_table and not is_table_line(line):
            flush_table()

        # ## Heading 2 (section level)
        if line.startswith('## ') and not line.startswith('### '):
            text = line.lstrip('#').strip()
            chapter_num = text.split('.')[0] if '.' in text else ''

            if chapter_num.isdigit() and chapter_num != last_chapter_num:
                doc.add_page_break()
                just_page_broken = True
                if chapter_names and chapter_idx + 1 < len(chapter_names):
                    chapter_idx += 1
                    add_heading(doc, chapter_names[chapter_idx], 1)
                last_chapter_num = chapter_num

            # Page break before every H2 section (unless just had one)
            if not just_page_broken:
                doc.add_page_break()
            just_page_broken = True
            first_h3_after_h2 = True  # Next H3 is the first under this H2

            add_heading(doc, text, 2)
            i += 1
            continue

        # ### Heading 3 (sub-section level)
        if line.startswith('### ') and not line.startswith('#### '):
            text = line.lstrip('#').strip()
            # Page break before each H3, EXCEPT the first H3 under a new H2
            if not just_page_broken and not first_h3_after_h2:
                doc.add_page_break()
            just_page_broken = True
            first_h3_after_h2 = False
            add_heading(doc, text, 3)
            i += 1
            continue

        # #### (sub-sub → body text with bold)
        if line.startswith('#### '):
            text = line.lstrip('#').strip()
            add_body_para(doc, text, first_line_indent=True, bold=True)
            just_page_broken = False
            i += 1
            continue

        # Code blocks (skip)
        if line.strip().startswith('```'):
            if in_table:
                flush_table()
            i += 1
            continue

        # Table (robust detection: | at both ends)
        if is_table_line(line):
            if not in_table:
                in_table = True
                table_lines = []
            table_lines.append(line)
            i += 1
            continue

        # Bold markers
        if line.strip().startswith('**') and line.strip().endswith('**'):
            text = line.strip().strip('*')
            add_body_para(doc, text, first_line_indent=True, bold=True)
            just_page_broken = False
            i += 1
            continue

        # Regular paragraph
        text = clean_markdown(line.strip())
        add_body_para(doc, text, first_line_indent=True)
        just_page_broken = False
        i += 1

    # END OF FILE: flush any trailing table
    if in_table:
        flush_table()

    # ---- PHASE 4: Page numbers ----
    add_page_numbers(doc)
    
    # ---- Save ----
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    doc.save(output_path)
    
    # Stats
    body_paras = [p for p in doc.paragraphs if p.style.name.startswith('Normal')]
    headings = [p for p in doc.paragraphs if p.style.name.startswith('Heading')]
    h1, h2, h3 = 0, 0, 0
    for p in headings:
        if p.style.name == 'Heading 1': h1 += 1
        elif p.style.name == 'Heading 2': h2 += 1
        elif p.style.name == 'Heading 3': h3 += 1
    
    print(f'✅ DOCX: {output_path}')
    print(f'   H1={h1} H2={h2} H3={h3} body={len(body_paras)} tables={len(doc.tables)}')
    
    return doc


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MD→DOCX converter for bid plans')
    parser.add_argument('input_md', help='Input Markdown file')
    parser.add_argument('output_docx', help='Output DOCX file')
    parser.add_argument('--chapters', default='二、实施方案,三、售后服务保障',
                        help='Comma-separated Heading 1 names')
    args = parser.parse_args()
    
    chapters = [c.strip() for c in args.chapters.split(',') if c.strip()]
    convert_md_to_docx(args.input_md, args.output_docx, chapters)
