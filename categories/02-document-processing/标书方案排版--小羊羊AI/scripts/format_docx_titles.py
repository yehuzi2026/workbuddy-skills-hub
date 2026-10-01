#!/usr/bin/env python3
"""
Word 文档标题排版与目录生成脚本
自动将正文样式的标题转换为标准 Heading 样式，创建多级编号，插入 TOC 目录。

用法：
    python format_docx_titles.py <input.docx> [output.docx]

示例：
    python format_docx_titles.py 原始文件.docx 排版后.docx
"""
import re, zipfile, xml.etree.ElementTree as ET, sys, os

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

def get_text(p):
    return ''.join(t.text or '' for t in p.findall('.//w:t', NS))

def set_text(p, new_text):
    runs = p.findall('w:r', NS)
    first_run = None
    for r in runs:
        t_elems = r.findall('w:t', NS)
        if t_elems:
            if first_run is None:
                first_run = r
                for t in t_elems[1:]:
                    r.remove(t)
                t_elems[0].text = new_text
            else:
                p.remove(r)

def detect(text):
    text = text.strip()
    if re.match(r'^第[一二三四五六七八九十百千万]+章', text): return 1
    if re.match(r'^\d+\.\d+\.\d+\s', text): return 3
    if re.match(r'^\d+\.\d+\s', text): return 2
    return 0

def remove(text, level):
    if level == 1: return re.sub(r'^第[一二三四五六七八九十百千万]+章\s*', '', text)
    if level == 2: return re.sub(r'^\d+\.\d+\s+', '', text)
    if level == 3: return re.sub(r'^\d+\.\d+\.\d+\s+', '', text)
    return text

for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

def format_docx(input_path, output_path=None):
    if output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = base + '_已排版' + ext
    
    print(f'Reading input file: {input_path}')
    with zipfile.ZipFile(input_path, 'r') as zin:
        files = {name: zin.read(name) for name in zin.namelist()}
    print(f'Read {len(files)} files')

    # 1. Create numbering.xml
    print('Creating numbering.xml...')
    num_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="0">
    <w:multiLevelType w:val="multilevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/>
      <w:numFmt w:val="chineseCounting"/>
      <w:lvlText w:val="第%1章"/>
      <w:lvlJc w:val="left"/>
      <w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr>
      <w:rPr>
        <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="黑体"/>
        <w:b/><w:bCs/>
        <w:sz w:val="32"/><w:szCs w:val="32"/>
      </w:rPr>
    </w:lvl>
    <w:lvl w:ilvl="1">
      <w:start w:val="1"/>
      <w:numFmt w:val="decimal"/>
      <w:lvlText w:val="%1.%2"/>
      <w:lvlJc w:val="left"/>
      <w:pPr><w:ind w:left="420" w:hanging="420"/></w:pPr>
      <w:rPr>
        <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="黑体"/>
        <w:b/><w:bCs/>
        <w:sz w:val="28"/><w:szCs w:val="28"/>
      </w:rPr>
    </w:lvl>
    <w:lvl w:ilvl="2">
      <w:start w:val="1"/>
      <w:numFmt w:val="decimal"/>
      <w:lvlText w:val="%1.%2.%3"/>
      <w:lvlJc w:val="left"/>
      <w:pPr><w:ind w:left="840" w:hanging="840"/></w:pPr>
      <w:rPr>
        <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="黑体"/>
        <w:b/><w:bCs/>
        <w:sz w:val="24"/><w:szCs w:val="24"/>
      </w:rPr>
    </w:lvl>
  </w:abstractNum>
  <w:num w:numId="1">
    <w:abstractNumId w:val="0"/>
  </w:num>
</w:numbering>'''
    files['word/numbering.xml'] = num_xml.encode('utf-8')
    print('numbering.xml created')

    # 2. Update rels
    print('Updating rels...')
    rels_xml = files['word/_rels/document.xml.rels'].decode('utf-8')
    rels_root = ET.fromstring(rels_xml)
    ns_rels = 'http://schemas.openxmlformats.org/package/2006/relationships'
    rel = ET.SubElement(rels_root, '{%s}Relationship' % ns_rels)
    rel.set('Id', 'rId999')
    rel.set('Type', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering')
    rel.set('Target', 'numbering.xml')
    files['word/_rels/document.xml.rels'] = ET.tostring(rels_root, encoding='utf-8', xml_declaration=True)
    print('rels updated')

    # 3. Update styles.xml
    print('Updating styles.xml...')
    styles_xml = files['word/styles.xml'].decode('utf-8')
    styles_root = ET.fromstring(styles_xml)

    for style_id, style_name, font_size, outline_lvl, num_ilvl in [
        ('Title', 'Title', '44', None, None),
        ('Heading1', 'heading 1', '32', '0', '0'),
        ('Heading2', 'heading 2', '28', '1', '1'),
        ('Heading3', 'heading 3', '24', '2', '2'),
        ('TOCHeading', 'TOC Heading', '32', None, None),
    ]:
        for s in styles_root.findall('w:style', NS):
            if s.get('{%s}styleId' % W) == style_id:
                styles_root.remove(s)
                break
        
        style = ET.SubElement(styles_root, '{%s}style' % W)
        style.set('{%s}type' % W, 'paragraph')
        style.set('{%s}styleId' % W, style_id)
        ET.SubElement(style, '{%s}name' % W).set('{%s}val' % W, style_name)
        ET.SubElement(style, '{%s}basedOn' % W).set('{%s}val' % W, 'Normal')
        ET.SubElement(style, '{%s}qFormat' % W)
        
        pPr = ET.SubElement(style, '{%s}pPr' % W)
        ET.SubElement(pPr, '{%s}keepNext' % W)
        ET.SubElement(pPr, '{%s}keepLines' % W)
        ET.SubElement(pPr, '{%s}spacing' % W).set('{%s}before' % W, str(int(font_size) * 10))
        
        if outline_lvl is not None:
            ET.SubElement(pPr, '{%s}outlineLvl' % W).set('{%s}val' % W, outline_lvl)
        if num_ilvl is not None:
            numPr = ET.SubElement(pPr, '{%s}numPr' % W)
            ET.SubElement(numPr, '{%s}numId' % W).set('{%s}val' % W, '1')
            ET.SubElement(numPr, '{%s}ilvl' % W).set('{%s}val' % W, num_ilvl)
        
        rPr = ET.SubElement(style, '{%s}rPr' % W)
        rFonts = ET.SubElement(rPr, '{%s}rFonts' % W)
        rFonts.set('{%s}ascii' % W, 'Times New Roman')
        rFonts.set('{%s}hAnsi' % W, 'Times New Roman')
        rFonts.set('{%s}eastAsia' % W, '黑体')
        ET.SubElement(rPr, '{%s}b' % W)
        ET.SubElement(rPr, '{%s}bCs' % W)
        ET.SubElement(rPr, '{%s}sz' % W).set('{%s}val' % W, font_size)
        ET.SubElement(rPr, '{%s}szCs' % W).set('{%s}val' % W, font_size)

    files['word/styles.xml'] = ET.tostring(styles_root, encoding='utf-8', xml_declaration=True)
    print('styles.xml updated')

    # 4. Update document.xml
    print('Updating document.xml...')
    doc_xml = files['word/document.xml'].decode('utf-8')
    doc_root = ET.fromstring(doc_xml)
    body = doc_root.find('w:body', NS)

    stats = {1: 0, 2: 0, 3: 0}
    removed = []

    for p in body.findall('w:p', NS):
        text = get_text(p).strip()
        level = detect(text)
        
        if level == 0 and text == '技术方案':
            pPr = p.find('w:pPr', NS)
            if pPr is None: pPr = ET.SubElement(p, '{%s}pPr' % W)
            old = pPr.find('w:pStyle', NS)
            if old: pPr.remove(old)
            ET.SubElement(pPr, '{%s}pStyle' % W).set('{%s}val' % W, 'Title')
            continue
        
        if level == 0: continue
        
        new_text = remove(text, level)
        if new_text != text:
            set_text(p, new_text)
            removed.append(f'[{level}] "{text[:40]}..." -> "{new_text[:40]}..."')
        
        stats[level] += 1
        
        pPr = p.find('w:pPr', NS)
        if pPr is None: pPr = ET.SubElement(p, '{%s}pPr' % W)
        old = pPr.find('w:pStyle', NS)
        if old: pPr.remove(old)
        ET.SubElement(pPr, '{%s}pStyle' % W).set('{%s}val' % W, f'Heading{level}')
        
        old_num = pPr.find('w:numPr', NS)
        if old_num: pPr.remove(old_num)

    # Insert TOC
    toc_title = ET.Element('{%s}p' % W)
    tpPr = ET.SubElement(toc_title, '{%s}pPr' % W)
    ET.SubElement(tpPr, '{%s}pStyle' % W).set('{%s}val' % W, 'TOCHeading')
    tr = ET.SubElement(toc_title, '{%s}r' % W)
    trPr = ET.SubElement(tr, '{%s}rPr' % W)
    ET.SubElement(trPr, '{%s}b' % W)
    ET.SubElement(trPr, '{%s}bCs' % W)
    ET.SubElement(trPr, '{%s}sz' % W).set('{%s}val' % W, '32')
    ET.SubElement(trPr, '{%s}szCs' % W).set('{%s}val' % W, '32')
    ET.SubElement(tr, '{%s}t' % W).text = '目录'

    toc_field = ET.Element('{%s}p' % W)
    fpPr = ET.SubElement(toc_field, '{%s}pPr' % W)
    ET.SubElement(fpPr, '{%s}pStyle' % W).set('{%s}val' % W, 'Normal')

    r1 = ET.SubElement(toc_field, '{%s}r' % W)
    ET.SubElement(r1, '{%s}fldChar' % W).set('{%s}fldCharType' % W, 'begin')

    r2 = ET.SubElement(toc_field, '{%s}r' % W)
    it = ET.SubElement(r2, '{%s}instrText' % W)
    it.set('xml:space', 'preserve')
    it.text = ' TOC \\o "1-3" \\h \\z \\u '

    r3 = ET.SubElement(toc_field, '{%s}r' % W)
    ET.SubElement(r3, '{%s}fldChar' % W).set('{%s}fldCharType' % W, 'separate')

    r4 = ET.SubElement(toc_field, '{%s}r' % W)
    ET.SubElement(r4, '{%s}t' % W).text = '（右键此处，选择"更新域"以生成目录）'

    r5 = ET.SubElement(toc_field, '{%s}r' % W)
    ET.SubElement(r5, '{%s}fldChar' % W).set('{%s}fldCharType' % W, 'end')

    first_p = body.find('w:p', NS)
    if first_p is not None:
        idx = list(body).index(first_p)
        body.insert(idx, toc_field)
        body.insert(idx, toc_title)

    files['word/document.xml'] = ET.tostring(doc_root, encoding='utf-8', xml_declaration=True)
    print('document.xml updated')

    # 5. Write output
    print('Writing output...')
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name, data in files.items():
            zout.writestr(name, data)
    print(f'Output written: {output_path}')

    print(f'\nStats: H1={stats[1]}, H2={stats[2]}, H3={stats[3]}')
    print(f'Titles modified: {len(removed)}')
    for line in removed[:10]:
        print(line)

    print('\n=== DONE ===')
    return output_path

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python format_docx_titles.py <input.docx> [output.docx]')
        sys.exit(1)
    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    format_docx(input_path, output_path)
