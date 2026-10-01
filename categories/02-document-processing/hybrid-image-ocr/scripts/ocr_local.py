#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hybrid-image-ocr 本地引擎封装（RapidOCR）

模式:
  ocr   提取图片全部文字(按阅读顺序)，输出纯文本；--json 输出结构化
  table 坐标聚类还原 Markdown 表格；质量不足时打印 [[FALLBACK_CLOUD]]
  doc   提取全部文字块(含坐标/置信)，供云端视觉二次结构化

输入: 本地文件路径、http(s) URL、或 --dir 批量目录(处理所有图片)
依赖: rapidocr-onnxruntime, pillow, numpy, opencv-python, shapely
"""
import argparse
import json
import os
import sys
import tempfile
import urllib.request

from rapidocr_onnxruntime import RapidOCR

ENGINE = None


def get_engine():
    global ENGINE
    if ENGINE is None:
        ENGINE = RapidOCR()
    return ENGINE


def download(url, dest_dir):
    fn = os.path.basename(url.split("?")[0]) or "download.png"
    dest = os.path.join(dest_dir, fn)
    urllib.request.urlretrieve(url, dest)
    return dest


def parse_items(result):
    items = []
    for box, text, score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append(
            {
                "text": text,
                "score": float(score),
                "cx": sum(xs) / 4.0,
                "cy": sum(ys) / 4.0,
                "w": max(xs) - min(xs),
                "h": max(ys) - min(ys),
            }
        )
    return items


def line_threshold(items):
    hs = [it["h"] for it in items if it["h"] > 0]
    if not hs:
        return 20
    hs.sort()
    med = hs[len(hs) // 2]
    return max(10, med * 0.7)


def read_order(items):
    items = sorted(items, key=lambda it: it["cy"])
    thresh = line_threshold(items)
    rows, cur, last_y = [], [], None
    for it in items:
        if last_y is None or abs(it["cy"] - last_y) <= thresh:
            cur.append(it)
        else:
            rows.append(cur)
            cur = [it]
        last_y = it["cy"]
    if cur:
        rows.append(cur)
    lines = []
    for r in rows:
        r.sort(key=lambda it: it["cx"])
        lines.append(" ".join(it["text"] for it in r))
    return lines


def cluster_table(items):
    items = sorted(items, key=lambda it: it["cy"])
    thresh = line_threshold(items)
    rows, cur, last_y = [], [], None
    for it in items:
        if last_y is None or abs(it["cy"] - last_y) <= thresh:
            cur.append(it)
        else:
            rows.append(cur)
            cur = [it]
        last_y = it["cy"]
    if cur:
        rows.append(cur)
    for r in rows:
        r.sort(key=lambda it: it["cx"])
    n_rows = len(rows)
    n_cols = max((len(r) for r in rows), default=0)
    avg_conf = sum(it["score"] for it in items) / len(items) if items else 0.0
    table = [[cell["text"] for cell in r] for r in rows]
    return table, n_rows, n_cols, avg_conf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="图片路径或 http(s) URL")
    ap.add_argument("--dir", help="批量目录(处理目录下所有图片)")
    ap.add_argument("--mode", default="ocr", choices=["ocr", "table", "doc"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    eng = get_engine()
    tmp = tempfile.mkdtemp()
    targets = []
    if args.dir:
        for f in sorted(os.listdir(args.dir)):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
                targets.append(os.path.join(args.dir, f))
    elif args.image:
        if args.image.startswith("http://") or args.image.startswith("https://"):
            targets.append(download(args.image, tmp))
        else:
            targets.append(args.image)
    else:
        print("ERROR: 需提供 --image 或 --dir", file=sys.stderr)
        sys.exit(2)

    for path in targets:
        result, _ = eng(path)
        items = parse_items(result or [])
        if args.mode == "ocr":
            if args.json:
                print(json.dumps({"source": path, "lines": read_order(items), "items": items}, ensure_ascii=False, indent=2))
            else:
                print("\n".join(read_order(items)))
        elif args.mode == "doc":
            out = [
                {"text": it["text"], "score": round(it["score"], 3), "pos": [round(it["cx"], 1), round(it["cy"], 1)]}
                for it in sorted(items, key=lambda x: (x["cy"], x["cx"]))
            ]
            if args.json:
                print(json.dumps({"source": path, "blocks": out}, ensure_ascii=False, indent=2))
            else:
                for b in out:
                    print(f"[{b['score']}] {b['text']}")
        elif args.mode == "table":
            table, raw_n_rows, raw_n_cols, avg_conf = cluster_table(items)
            # 过滤单列行（纯文本段落），只保留真正多列表格
            table = [r for r in table if len(r) >= 2]
            n_rows = len(table)
            n_cols = max((len(r) for r in table), default=0)
            if n_rows < 2 or n_cols < 2 or avg_conf < 0.6:
                # 本地质量不足 -> 交给云端视觉兜底
                if args.json:
                    print(json.dumps({"fallback": "cloud", "n_rows": n_rows, "n_cols": n_cols, "avg_conf": round(avg_conf, 3)}, ensure_ascii=False))
                else:
                    print("[[FALLBACK_CLOUD]]")
            else:
                md = "| " + " | ".join(table[0]) + " |\n"
                md += "| " + " | ".join(["---"] * len(table[0])) + " |\n"
                for row in table[1:]:
                    md += "| " + " | ".join(row) + " |\n"
                print(md.strip())


if __name__ == "__main__":
    main()
