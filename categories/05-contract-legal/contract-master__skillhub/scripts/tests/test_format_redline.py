#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""格式红线冒烟测试：行距检测 + A4 页面兜底。

覆盖 v2.5.0 修复的"生成几百页"格式 bug：
  1. check_line_spacing 能识别 Pt(360) 固定行距（异常）并放过 1.5 倍行距（正常）
  2. beautify_docx.py 输出文档强制为 A4（21×29.7cm）而非 Letter

运行：python3 scripts/tests/test_format_redline.py
"""
import os
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from beautify_docx import check_line_spacing

from docx import Document
from docx.shared import Pt

HERE = os.path.dirname(os.path.abspath(__file__))
BEAUTIFY = os.path.join(HERE, "..", "beautify_docx.py")
PASS = 0
FAIL = 0


def ok(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")


def make_doc(spacing_mode, path):
    doc = Document()
    for i in range(5):
        p = doc.add_paragraph(f"测试段落 {i}")
        if spacing_mode == "ok":
            p.paragraph_format.line_spacing = 1.5
        elif spacing_mode == "bad":
            p.paragraph_format.line_spacing = Pt(360)  # 复现几百页 bug
    doc.save(path)


def main():
    tmp = tempfile.mkdtemp(prefix="hb_format_")
    ok_path = os.path.join(tmp, "ok.docx")
    bad_path = os.path.join(tmp, "bad.docx")
    make_doc("ok", ok_path)
    make_doc("bad", bad_path)

    print("[1] 行距红线检测")
    bad_n, _ = check_line_spacing(bad_path)
    ok_n, _ = check_line_spacing(ok_path)
    ok("Pt(360) 文档被识别为异常行距 (bad_n>0)", bad_n > 0)
    ok("1.5 倍行距文档不触发 (ok_n==0)", ok_n == 0)

    print("[2] beautify A4 页面兜底")
    r = subprocess.run(
        [sys.executable, BEAUTIFY, ok_path, "--mode", "draft"],
        capture_output=True, text=True, timeout=180,
    )
    ok("beautify 正常退出 (rc==0)", r.returncode == 0)
    with zipfile.ZipFile(ok_path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    # python-docx 以 twips 存页面：21cm=11906twips, 29.7cm=16838twips
    ok("页面宽为 A4 (w:w=11906)", 'w:w="11906"' in xml)
    ok("页面高为 A4 (w:h=16838)", 'w:h="16838"' in xml)

    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
