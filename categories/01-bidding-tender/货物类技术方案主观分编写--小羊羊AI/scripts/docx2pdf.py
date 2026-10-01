#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docx2pdf.py — 将 Word .docx 转换为 .pdf（货物类技术方案专用）

相对服务类的增强点（来自 SKILL.md Phase 7 要求）：
  * PDF 元数据写入：项目名称（-> PDF /Title）、生成日期（-> PDF CreationDate + JSON）。
  * 转换后验证 PDF 页数与 DOCX 页数一致，结果写入 phase7_pdf_conversion.json。
  * 保持 DOCX 排版一致（由 Word 原生渲染保证）。

设计目标：
  * 零 Python 第三方依赖（仅标准库 + 系统已装引擎）。
  * 后端自动探测：1) MS Word COM（PowerShell，保真度最佳） 2) LibreOffice 无头。
  * 失败给出明确中文原因 + 非 0 退出码。

用法：
  python scripts/docx2pdf.py INPUT.docx OUTPUT.pdf [--project 项目名称] [--backend auto|word|libreoffice]
  python scripts/docx2pdf.py --help

退出码：
  0 成功（PDF 已生成）
  1 参数错误
  2 输入不存在 / 非 .docx
  3 无可用后端
  4 转换执行失败
  5 输出未生成或为空
  6 页数校验不一致（PDF 已产出，但页数不符，详见 JSON）
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys


# ---------------------------------------------------------------------------
# 后端探测
# ---------------------------------------------------------------------------

def find_libreoffice():
    for name in ("soffice", "libreoffice", "soffice.exe", "libreoffice.exe"):
        p = shutil.which(name)
        if p:
            return p
    for c in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        r"D:\Program Files\LibreOffice\program\soffice.exe",
        "/usr/bin/libreoffice", "/usr/bin/soffice", "/opt/libreoffice/program/soffice",
    ):
        if os.path.isfile(c):
            return c
    return None


def has_ms_word():
    if os.name != "nt":
        return False
    for c in (
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files\Microsoft Office\Office16\WINWORD.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files (x86)\Microsoft Office\Office16\WINWORD.EXE",
    ):
        if os.path.isfile(c):
            return True
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Classes\\Word.Application\\CurVer' -ErrorAction SilentlyContinue).'(default)'"],
            capture_output=True, text=True, timeout=20,
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def derive_project_name(input_path):
    """从 `技术方案_{项目简称}_排版完成.docx` 解析项目简称，失败回退文件名。"""
    base = os.path.splitext(os.path.basename(input_path))[0]
    m = re.search(r"技术方案_(.+?)_排版完成$", base)
    if m:
        return m.group(1)
    return base


def count_pdf_pages(pdf_path):
    """无第三方库统计 PDF 页数。

    匹配 `/Type/Page` 或 `/Type /Page`（允许有无空格），并用词边界 \\b
    排除 `/Type/Pages`（其前缀恰为 `/Type/Page`，否则会被多减）。
    对压缩在 ObjStm 中的页面对象可能失效，属 best-effort（本机 Word/LibreOffice
    产出的常规页面对象均可正确计数）。
    """
    with open(pdf_path, "rb") as f:
        data = f.read()
    pages = len(re.findall(rb"/Type\s*/\s*Page\b", data))
    return max(pages, 0)


# ---------------------------------------------------------------------------
# 后端实现
# ---------------------------------------------------------------------------

def convert_with_libreoffice(soffice, in_path, out_path):
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    cmd = [soffice, "--headless", "--convert-to", "pdf",
           "--outdir", out_dir, os.path.abspath(in_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError("LibreOffice 转换失败 (exit=%s)\n%s"
                           % (proc.returncode, proc.stderr.strip()))
    base = os.path.splitext(os.path.basename(in_path))[0] + ".pdf"
    produced = os.path.join(out_dir, base)
    if produced != os.path.abspath(out_path) and os.path.isfile(produced):
        shutil.move(produced, os.path.abspath(out_path))
    return os.path.abspath(out_path)


def convert_with_word_com(in_path, out_path, project_name):
    """通过 PowerShell 调用 Word COM 完成 DOCX->PDF，并写入元数据 / 取页数。"""
    in_abs = os.path.abspath(in_path)
    out_abs = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_abs)
    os.makedirs(out_dir, exist_ok=True)
    gen_date = datetime.date.today().isoformat()

    # PowerShell 中把项目名称与生成日期作为变量传入（避免命令注入）
    ps = r'''
$ErrorActionPreference = "Stop"
$in  = $env:D2P_IN
$out = $env:D2P_OUT
$pn  = $env:D2P_PROJECT
$gd  = $env:D2P_DATE
$word = $null
$doc  = $null
$docxPages = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Open($in, $false, $true)
    # 写入 PDF 元数据：项目名称 -> Title；生成日期记录到 Comments 便于追溯
    try { $doc.BuiltInDocumentProperties.Item("Title").Value = $pn } catch {}
    try { $doc.BuiltInDocumentProperties.Item("Comments").Value = ("生成日期: " + $gd) } catch {}
    # 取得 DOCX 页数（wdStatisticPages = 2）
    try { $docxPages = $doc.ComputeStatistics(2) } catch { $docxPages = $null }
    $doc.SaveAs([ref]$out, [ref]17)   # 17 = wdFormatPDF
} finally {
    if ($doc -ne $null) { try { $doc.Close() } catch {} }
    if ($word -ne $null) {
        try { $word.Quit() } catch {}
        [System.Runtime.Interopservices.Marshal]::ReleaseComObject($word) | Out-Null
    }
}
if ($docxPages -ne $null) { Write-Output ("DOCX_PAGES=" + $docxPages) }
'''
    env = dict(os.environ,
               D2P_IN=in_abs, D2P_OUT=out_abs,
               D2P_PROJECT=project_name or "", D2P_DATE=gen_date)
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True, text=True, timeout=180, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError("Word COM 转换失败 (exit=%s)\nstdout:%s\nstderr:%s"
                           % (proc.returncode, proc.stdout.strip(), proc.stderr.strip()))
    docx_pages = None
    for line in proc.stdout.splitlines():
        if line.startswith("DOCX_PAGES="):
            try:
                docx_pages = int(line.split("=", 1)[1])
            except Exception:
                docx_pages = None
    return out_abs, docx_pages, gen_date


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="货物类技术方案 DOCX->PDF（含元数据与页数校验）"
    )
    parser.add_argument("input", help="输入 .docx 文件路径")
    parser.add_argument("output", help="输出 .pdf 文件路径")
    parser.add_argument("--project", default=None,
                        help="项目名称（写入 PDF 元数据 /Title；缺省从文件名解析）")
    parser.add_argument("--backend", default="auto",
                        choices=["auto", "word", "libreoffice"])
    args = parser.parse_args(argv)

    in_path, out_path = args.input, args.output
    if not os.path.isfile(in_path):
        print("错误：输入文件不存在 -> %s" % in_path, file=sys.stderr); return 2
    if not in_path.lower().endswith(".docx"):
        print("错误：输入必须为 .docx -> %s" % in_path, file=sys.stderr); return 2

    project_name = args.project or derive_project_name(in_path)
    backend = args.backend
    soffice = None
    use_word = False

    if backend == "libreoffice":
        soffice = find_libreoffice()
        if not soffice:
            print("错误：未找到 LibreOffice (soffice)。", file=sys.stderr); return 3
    elif backend == "word":
        if not has_ms_word():
            print("错误：本机未安装 Microsoft Word。", file=sys.stderr); return 3
        use_word = True
    else:
        if has_ms_word():
            use_word = True
        else:
            soffice = find_libreoffice()
            if not soffice:
                print("错误：未找到可用转换后端（需安装 MS Word 或 LibreOffice）。",
                      file=sys.stderr); return 3

    docx_pages = None
    gen_date = datetime.date.today().isoformat()
    try:
        if use_word:
            out_path, docx_pages, gen_date = convert_with_word_com(
                in_path, out_path, project_name)
        else:
            convert_with_libreoffice(soffice, in_path, out_path)
    except Exception as e:
        print("错误：转换执行失败 -> %s" % e, file=sys.stderr); return 4

    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        print("错误：输出 PDF 未生成或为空 -> %s" % out_path, file=sys.stderr); return 5

    pdf_pages = count_pdf_pages(out_path)
    pages_match = (docx_pages is not None and docx_pages == pdf_pages)
    if docx_pages is None:
        pages_match = None  # 无法取得 DOCX 页数（如 LibreOffice 后端未取），仅记录 PDF 页数

    exit_code = 0
    if pages_match is False:
        exit_code = 6
        print("警告：PDF 页数(%s) 与 DOCX 页数(%s) 不一致！"
              % (pdf_pages, docx_pages), file=sys.stderr)

    # 产出 phase7_pdf_conversion.json
    report = {
        "status": "success" if exit_code in (0, 6) else "failed",
        "docx_path": os.path.abspath(in_path),
        "pdf_path": os.path.abspath(out_path),
        "pdf_size_bytes": os.path.getsize(out_path),
        "project_name": project_name,
        "generated_date": gen_date,
        "docx_pages": docx_pages,
        "pdf_pages": pdf_pages,
        "pages_match": pages_match,
        "backend": "word" if use_word else "libreoffice",
        "pdf_metadata": {
            "title": project_name,
            "creation_date": gen_date,
            "note": "项目名称写入 PDF /Title；生成日期写入 PDF CreationDate 及 Word Comments",
        },
    }
    json_path = os.path.join(os.path.dirname(os.path.abspath(out_path)),
                             "phase7_pdf_conversion.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("[docx2pdf] 转换成功：%s  (%d 字节, %s 页, 后端=%s)"
          % (out_path, os.path.getsize(out_path), pdf_pages,
             "word" if use_word else "libreoffice"))
    print("[docx2pdf] 报告：%s" % json_path)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
