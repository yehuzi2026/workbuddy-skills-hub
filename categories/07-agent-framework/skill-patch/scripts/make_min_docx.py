#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_min_docx.py —— 零依赖最小合法 DOCX 生成器（skill-patch 测试脚手架）

用途：补建/验证技能脚本时，用标准库手工拼 OOXML 造测试样本，无需 python-docx。

用法：
  python make_min_docx.py <output.docx> [--pages N] [--broken] [--title T] [--body B]

  --pages N    : 插入 N-1 个分页符，造多页文档（默认 1 页，用于 docx2pdf 页数校验）
  --broken     : 注入违规特征，用于测试 verify_docx_format 类闸门：
                 · 标题用 Normal 样式（B.1 违规）
                 · 含 ● 项目符号（B.3 违规）
                 · 含 ** Markdown 残留（B.6 违规）
  --title T    : 标题文本（默认“测试标题”）
  --body B     : 正文文本（默认“测试正文内容。”）

退出码：0 成功；2 参数/IO 错误。
"""
import os
import sys
import argparse
import zipfile

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '</Types>'
)

RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '</Relationships>'
)

DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '</Relationships>'
)

STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="%s">'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
    '<w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
    '</w:styles>'
) % W_NS

# TOC 域段落（满足 verify_docx_format 的 B.11 校验：文档须含 TOC 域）
TOC_FIELD = (
    '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    '<w:r><w:t xml:space="preserve">[请右键更新域生成目录]</w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
)


def esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def build_document(pages, broken, title, body):
    paras = []
    # 标题段
    if broken:
        # B.1 违规：标题用 Normal 样式（无 Heading pStyle），且加粗+18pt，
        # 触发 verify_docx_format 的「疑似标题但使用 Normal 样式」判定（需 bold+sz>=28）
        paras.append(
            '<w:p><w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr>'
            '<w:t xml:space="preserve">%s</w:t></w:r></w:p>' % esc(title)
        )
    else:
        paras.append(
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            '<w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % esc(title)
        )
    paras.append(TOC_FIELD)  # 统一插入 TOC 域（满足 B.11 校验）
    # 正文段
    paras.append(
        '<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % esc(body)
    )
    if broken:
        # B.3 违规：● 项目符号（文本字符）
        paras.append(
            '<w:p><w:r><w:t xml:space="preserve">● 违规项目符号</w:t></w:r></w:p>'
        )
        # B.6 违规：** Markdown 残留
        paras.append(
            '<w:p><w:r><w:t xml:space="preserve">这是 **加粗残留** 测试行</w:t></w:r></w:p>'
        )
    # 多页：插入分页符
    for _ in range(max(0, pages - 1)):
        paras.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        paras.append(
            '<w:p><w:r><w:t xml:space="preserve">第 %d 页正文</w:t></w:r></w:p>'
            % (len(paras) // 2 + 1)
        )

    body_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="%s"><w:body>%s'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        '</w:body></w:document>'
    ) % (W_NS, "".join(paras))
    return body_xml


def main():
    ap = argparse.ArgumentParser(description="零依赖最小 DOCX 生成器（测试脚手架）")
    ap.add_argument("output", help="输出 .docx 路径")
    ap.add_argument("--pages", type=int, default=1, help="页数（默认 1）")
    ap.add_argument("--broken", action="store_true", help="注入违规特征（测闸门）")
    ap.add_argument("--title", default="测试标题", help="标题文本")
    ap.add_argument("--body", default="测试正文内容。", help="正文文本")
    args = ap.parse_args()

    if not args.output.lower().endswith(".docx"):
        sys.stderr.write("error: 输出必须是 .docx\n")
        return 2
    try:
        doc = build_document(args.pages, args.broken, args.title, args.body)
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", CONTENT_TYPES)
            z.writestr("_rels/.rels", RELS)
            z.writestr("word/document.xml", doc)
            z.writestr("word/_rels/document.xml.rels", DOC_RELS)
            z.writestr("word/styles.xml", STYLES)
        sys.stderr.write("ok: 已生成 %s (%d 页%s)\n"
                         % (args.output, args.pages, "，含违规特征" if args.broken else ""))
        return 0
    except Exception as e:
        sys.stderr.write("error: %s\n" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
