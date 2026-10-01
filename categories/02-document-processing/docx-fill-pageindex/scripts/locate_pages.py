#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
locate_pages.py — 在 PDF 里定位若干标题文本所在页码，输出页码范围。

用法:
    python locate_pages.py <pdf> <keywords.txt>
    # keywords.txt: 每行一个关键词；同一行可用 | 分隔别名（任一命中即算）
    # 行首 # 为注释

输出:
    每个关键词 -> 起始页, 以及自动推算的页码范围（到下一个关键词前一页为止，末项到总页数）

用途:
    给 docx 表格的「证明文件所在页码」列取值。配合 SKILL.md 的 Word COM 转 PDF 使用。
"""
import sys

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # 旧版


def load_keywords(path):
    kws = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            kws.append([a.strip() for a in line.split("|") if a.strip()])
    return kws


def norm(s):
    return s.replace(" ", "").replace("\n", "").replace("\u3000", "")


def main():
    pdf, kwfile = sys.argv[1], sys.argv[2]
    kws = load_keywords(kwfile)
    doc = fitz.open(pdf)
    n = doc.page_count
    pages = [norm(doc[i].get_text("text")) for i in range(n)]
    print("总页数: %d" % n)

    starts = []
    for alts in kws:
        hit = None
        for i, t in enumerate(pages):
            if any(a in t for a in alts):
                hit = i + 1
                break
        starts.append(hit)
        print("  %-30s 起始页=%s" % (alts[0][:28], hit))

    print("\n===== 页码范围（可直接填表）=====")
    for i, alts in enumerate(kws):
        s = starts[i]
        if s is None:
            print("  %-30s 未找到，需人工核" % alts[0][:28])
            continue
        e = (starts[i + 1] - 1) if (i + 1 < len(starts) and starts[i + 1]) else n
        print("  %-30s 第%d-%d页" % (alts[0][:28], s, e))


if __name__ == "__main__":
    main()
