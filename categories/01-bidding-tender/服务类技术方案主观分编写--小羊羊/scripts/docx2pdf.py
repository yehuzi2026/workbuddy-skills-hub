#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docx2pdf.py — 将 Word .docx 文档转换为 .pdf

设计目标：
  * 零 Python 第三方依赖（仅用标准库 + 系统已装的转换引擎），
    避免在生产环境因 pip 缺失而中断交付。
  * 自动探测可用后端，按保真度优先级选择：
      1. Microsoft Word COM（通过 PowerShell 调用，Windows 原生，保真度最佳）
      2. LibreOffice 无头模式（soffice，跨平台）
  * 失败时给出明确、可操作的中文错误原因，并以非 0 退出码退出，
    便于上层技能判断"PDF 是否真的产出"。

用法：
  python scripts/docx2pdf.py INPUT.docx OUTPUT.pdf [--backend auto|word|libreoffice]
  python scripts/docx2pdf.py --help

退出码：
  0  成功（OUTPUT.pdf 已生成且非空）
  1  参数错误
  2  输入文件不存在 / 不是 .docx
  3  没有可用的转换后端
  4  转换执行失败（后端报错）
  5  输出文件未生成或为空
"""
import argparse
import os
import shutil
import subprocess
import sys
import xml.dom.minidom  # noqa: F401  (占位，后续扩展用)

# ---------------------------------------------------------------------------
# 后端探测
# ---------------------------------------------------------------------------

def find_libreoffice():
    """查找 soffice / libreoffice 可执行文件，找不到返回 None。"""
    # 1) PATH 中直接可找到
    for name in ("soffice", "libreoffice", "soffice.exe", "libreoffice.exe"):
        p = shutil.which(name)
        if p:
            return p
    # 2) 常见安装目录
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        r"D:\Program Files\LibreOffice\program\soffice.exe",
        "/usr/bin/libreoffice",
        "/usr/bin/soffice",
        "/opt/libreoffice/program/soffice",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def has_ms_word():
    """判断本机是否装有 Microsoft Word（Windows）。"""
    if os.name != "nt":
        return False
    candidates = [
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files\Microsoft Office\Office16\WINWORD.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files (x86)\Microsoft Office\Office16\WINWORD.EXE",
        r"C:\Program Files\Microsoft Office\Office15\WINWORD.EXE",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return True
    # 退一步：尝试让 PowerShell 探测 ProgId
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
# 后端实现
# ---------------------------------------------------------------------------

def convert_with_libreoffice(soffice, in_path, out_path):
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        soffice, "--headless", "--convert-to", "pdf",
        "--outdir", out_dir, os.path.abspath(in_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(
            "LibreOffice 转换失败 (exit=%s)\nstdout: %s\nstderr: %s"
            % (proc.returncode, proc.stdout.strip(), proc.stderr.strip())
        )
    # LibreOffice 输出文件名 = 输入基名.pdf，可能与用户指定名不同，改名
    base = os.path.splitext(os.path.basename(in_path))[0] + ".pdf"
    produced = os.path.join(out_dir, base)
    if produced != os.path.abspath(out_path) and os.path.isfile(produced):
        shutil.move(produced, os.path.abspath(out_path))
    return os.path.abspath(out_path)


def convert_with_word_com(in_path, out_path):
    """通过 PowerShell 调用 Word COM 完成 DOCX→PDF（wdFormatPDF=17）。"""
    in_abs = os.path.abspath(in_path)
    out_abs = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_abs)
    os.makedirs(out_dir, exist_ok=True)

    ps = r'''
$ErrorActionPreference = "Stop"
$in  = "%s"
$out = "%s"
$word = $null
$doc  = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0   # wdAlertsNone
    $doc = $word.Documents.Open($in, $false, $true)   # ReadOnly=$true
    # 17 = wdFormatPDF
    $doc.SaveAs([ref]$out, [ref]17)
} finally {
    if ($doc -ne $null) { try { $doc.Close() } catch {} }
    if ($word -ne $null) {
        try { $word.Quit() } catch {}
        # 释放 COM 对象，避免 WINWORD.EXE 残留
        [System.Runtime.Interopservices.Marshal]::ReleaseComObject($word) | Out-Null
    }
}
''' % (in_abs.replace("\\", "\\\\"), out_abs.replace("\\", "\\\\"))

    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Word COM 转换失败 (exit=%s)\nstdout: %s\nstderr: %s"
            % (proc.returncode, proc.stdout.strip(), proc.stderr.strip())
        )
    return out_abs


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="将 Word .docx 转换为 .pdf（自动选择可用后端）"
    )
    parser.add_argument("input", help="输入 .docx 文件路径")
    parser.add_argument("output", help="输出 .pdf 文件路径")
    parser.add_argument(
        "--backend", default="auto",
        choices=["auto", "word", "libreoffice"],
        help="强制指定后端（默认 auto 自动探测）",
    )
    args = parser.parse_args(argv)

    in_path, out_path = args.input, args.output

    # 参数校验
    if not os.path.isfile(in_path):
        print("错误：输入文件不存在 -> %s" % in_path, file=sys.stderr)
        return 2
    if not in_path.lower().endswith(".docx"):
        print("错误：输入文件必须为 .docx（不支持 .doc，需先转 docx）-> %s"
              % in_path, file=sys.stderr)
        return 2

    backend = args.backend
    soffice = None
    use_word = False

    if backend == "libreoffice":
        soffice = find_libreoffice()
        if not soffice:
            print("错误：未找到 LibreOffice (soffice)，无法使用 libreoffice 后端。",
                  file=sys.stderr)
            return 3
    elif backend == "word":
        if not has_ms_word():
            print("错误：本机未安装 Microsoft Word，无法使用 word 后端。",
                  file=sys.stderr)
            return 3
        use_word = True
    else:  # auto
        # 优先级：Word COM（保真度最佳）> LibreOffice
        if has_ms_word():
            use_word = True
        else:
            soffice = find_libreoffice()
            if not soffice:
                print(
                    "错误：未找到可用的转换后端。\n"
                    "  请安装 Microsoft Word 或 LibreOffice 后重试。\n"
                    "  备选方案：在 Python 环境安装 docx2pdf / 用 Word 手动另存为 PDF。",
                    file=sys.stderr,
                )
                return 3

    try:
        if use_word:
            convert_with_word_com(in_path, out_path)
        else:
            convert_with_libreoffice(soffice, in_path, out_path)
    except Exception as e:
        print("错误：转换执行失败 -> %s" % e, file=sys.stderr)
        return 4

    # 产出校验
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        print("错误：输出 PDF 未生成或为空 -> %s" % out_path, file=sys.stderr)
        return 5

    print("[docx2pdf] 转换成功：%s  (%d 字节)"
          % (out_path, os.path.getsize(out_path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
