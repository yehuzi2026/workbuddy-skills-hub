#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
offline_extract.py — 纯离线文档文本/图片抽取（不依赖任何第三方库安装）

用途：当沙箱/环境无法安装 pywin32、pymupdf、markitdown、OCR 库时，
      仅用标准库抽取 .doc / .docx / .pdf 的文本与内嵌图片，图片再用多模态 Read 识别。

用法：
  python offline_extract.py <输入文件或目录> -o <输出目录>

产出：
  <out>/text/<name>.txt          文本（.doc 为降级提取，可能含噪声）
  <out>/media/<name>_imgNN.(png|jpg)   内嵌/扫描图片

依赖：仅标准库（python-docx 可选；有则 .docx 文本更准，无则用 zipfile+xml 兜底）
"""
import os, re, sys, zlib, zipfile, argparse, struct, xml.etree.ElementTree as ET

# ---------- .doc (Word 97-2003 OLE) 降级文本提取 ----------
def doc_utf16_runs(b, min_len=4):
    """扫描字节流中的 UTF-16LE 可读串（CJK + 常用 ASCII）。降级方案，可能含噪声。"""
    runs, cur, i = [], [], 0
    n = len(b)
    while i + 1 < n:
        cp = b[i] | (b[i+1] << 8)
        if (0x20 <= cp <= 0x9fff) and cp not in (0x2028, 0x2029) and not (0xD800 <= cp <= 0xDFFF):
            cur.append(cp); i += 2
        else:
            if len(cur) >= min_len: runs.append(cur)
            cur = []; i += 2
    if len(cur) >= min_len: runs.append(cur)
    return runs

def extract_doc(path, out_txt):
    data = open(path, "rb").read()
    parts = ["".join(chr(c) for c in r) for r in doc_utf16_runs(data)]
    full = "\n".join(parts)
    lines = [ln for ln in full.split("\n")
             if re.search(r"[\u4e00-\u9fff]", ln) or len(re.sub(r"\s", "", ln)) >= 6]
    open(out_txt, "w", encoding="utf-8").write("\n".join(lines))
    return {"chars": sum(len(x) for x in lines), "note": "degraded(UTF-16LE scan)"}

# ---------- .docx ----------
def extract_docx(path, out_txt, media_dir, prefix):
    lines, stats = [], {}
    try:
        from docx import Document
        doc = Document(path)
        for p in doc.paragraphs:
            if p.text.strip(): lines.append(p.text.strip())
        for ti, tbl in enumerate(doc.tables):
            lines.append(f"\n[表格 {ti+1}]")
            for row in tbl.rows:
                lines.append(" | ".join(c.text.strip().replace("\n", "/") for c in row.cells))
        stats["engine"] = "python-docx"
    except Exception:
        # 兜底：直接读 document.xml 文本
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        lines = [re.sub(r"<[^>]+>", "", t) for t in xml.split("\n")]
        lines = [l.strip() for l in lines if l.strip()]
        stats["engine"] = "zipfile+xml(fallback)"
    open(out_txt, "w", encoding="utf-8").write("\n".join(lines))
    stats["chars"] = sum(len(l) for l in lines)
    # media
    n = 0
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.startswith("word/media/") and os.path.splitext(name)[1].lower() in (".png", ".jpg", ".jpeg"):
                fn = os.path.join(media_dir, f"{prefix}_img{n+1:02d}{os.path.splitext(name)[1].lower()}")
                open(fn, "wb").write(z.read(name)); n += 1
    stats["media"] = n
    return stats

# ---------- .pdf ----------
def extract_pdf(path, out_txt, media_dir, prefix):
    raw = open(path, "rb").read()
    # text
    txt = ""
    try:
        import pypdf
        r = pypdf.PdfReader(path)
        txt = "\n".join(f"\n===== PDF第{i+1}页 =====\n" + (pg.extract_text() or "")
                        for i, pg in enumerate(r.pages))
    except Exception as e:
        txt = f"[pypdf 不可用或失败: {e}]"
    open(out_txt, "w", encoding="utf-8").write(txt)
    # images (DCTDecode JPEG / FlateDecode raw)
    n = 0
    for m in re.finditer(rb"stream\r?\n", raw):
        s = m.end(); e = raw.find(b"endstream", s)
        if e < 0: continue
        head = raw[max(0, s-800):s]
        if b"/Subtype" in head and b"/Image" in head:
            body = raw[s:e].rstrip(b"\r\n ")
            if b"/DCTDecode" in head:
                fn = os.path.join(media_dir, f"{prefix}_page{n+1:02d}.jpg")
                open(fn, "wb").write(body); n += 1
            elif b"/FlateDecode" in head:
                try:
                    open(os.path.join(media_dir, f"{prefix}_page{n+1:02d}.raw"), "wb").write(zlib.decompress(body)); n += 1
                except Exception:
                    pass
    return {"chars": len(txt), "media": n, "note": "图片用多模态 Read 识别"}

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input"); ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    files = []
    if os.path.isdir(a.input):
        for f in sorted(os.listdir(a.input)):
            if os.path.splitext(f)[1].lower() in (".doc", ".docx", ".pdf"):
                files.append(os.path.join(a.input, f))
    else:
        files = [a.input]
    tdir = os.path.join(a.out, "text"); mdir = os.path.join(a.out, "media")
    os.makedirs(tdir, exist_ok=True); os.makedirs(mdir, exist_ok=True)
    for f in files:
        base = os.path.splitext(os.path.basename(f))[0]
        ext = os.path.splitext(f)[1].lower()
        ot = os.path.join(tdir, base + ".txt")
        try:
            if ext == ".doc":
                st = extract_doc(f, ot)
            elif ext == ".docx":
                st = extract_docx(f, ot, mdir, base)
            elif ext == ".pdf":
                st = extract_pdf(f, ot, mdir, base)
            else:
                continue
            print(f"[OK] {os.path.basename(f)} -> {st}")
        except Exception as e:
            print(f"[ERR] {os.path.basename(f)}: {e}")

if __name__ == "__main__":
    main()
