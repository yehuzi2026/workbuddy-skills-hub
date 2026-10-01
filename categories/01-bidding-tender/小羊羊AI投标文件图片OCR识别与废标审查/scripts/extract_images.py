#!/usr/bin/env python3
"""
从docx文件中提取所有内嵌图片，保存到指定目录。
支持超大docx文件（使用zipfile直接读取，不依赖python-docx）。

用法:
    python extract_images.py <docx_path> <output_dir> [--min-size 5000] [--format png|jpg|all]

参数:
    docx_path  : docx文件路径
    output_dir : 图片输出目录
    --min-size : 最小文件大小(字节)，低于此值的图片跳过(默认5000，过滤装饰性小图)
    --format   : 输出格式 png/jpg/all(默认all，保持原始格式)

输出:
    在output_dir下生成:
    - images/ 目录：所有提取的图片文件
    - manifest.json：图片清单(文件名、大小、尺寸、格式、在文档中的位置)
"""

import os
import sys
import json
import zipfile
import argparse
from pathlib import Path
from PIL import Image
import io
import re


def extract_images_from_docx(docx_path, output_dir, min_size=5000, fmt='all'):
    """从docx中提取图片"""
    docx_path = Path(docx_path)
    output_dir = Path(output_dir)

    if not docx_path.exists():
        print(f"ERROR: File not found: {docx_path}")
        sys.exit(1)

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    manifest = []

    # 使用zipfile直接读取docx(兼容超大文件)
    with zipfile.ZipFile(docx_path, 'r') as zf:
        # 获取所有媒体文件
        media_files = [f for f in zf.namelist()
                       if f.startswith('word/media/')]

        # 尝试读取document.xml获取图片位置信息
        doc_xml = None
        if 'word/document.xml' in zf.namelist():
            try:
                doc_xml = zf.read('word/document.xml').decode('utf-8', errors='ignore')
            except Exception:
                doc_xml = None

        # 提取图片的关系映射
        rels_xml = None
        if 'word/_rels/document.xml.rels' in zf.namelist():
            try:
                rels_xml = zf.read('word/_rels/document.xml.rels').decode('utf-8', errors='ignore')
            except Exception:
                rels_xml = None

        # 构建rId -> 图片文件名映射
        rid_map = {}
        if rels_xml:
            for match in re.finditer(
                r'Target="media/([^"]+)"\s+Id="([^"]+)"',
                rels_xml
            ):
                filename, rid = match.group(1), match.group(2)
                rid_map[rid] = filename
            # 也匹配Id在前的情况
            for match in re.finditer(
                r'Id="([^"]+)"[^>]*Target="media/([^"]+)"',
                rels_xml
            ):
                rid, filename = match.group(1), match.group(2)
                rid_map[rid] = filename

        print(f"Found {len(media_files)} media files in docx")
        print(f"Found {len(rid_map)} relationship mappings")

        total = len(media_files)
        saved = 0
        skipped = 0

        for i, media_path in enumerate(media_files, 1):
            filename = Path(media_path).name
            data = zf.read(media_path)
            file_size = len(data)

            # 过滤小图片(装饰性元素)
            if file_size < min_size:
                skipped += 1
                continue

            # 确定文件扩展名
            ext = Path(filename).suffix.lower()
            if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.emf', '.wmf'):
                ext = '.png'  # 默认

            # EMF/WMF格式转换
            if ext in ('.emf', '.wmf'):
                # 这些格式Pillow无法直接读取，先保存原文件，后面标记
                save_name = f"img_{i:04d}{ext}"
                save_path = images_dir / save_name
                with open(save_path, 'wb') as f:
                    f.write(data)

                entry = {
                    "index": i,
                    "original_name": filename,
                    "saved_name": save_name,
                    "size_bytes": file_size,
                    "width": None,
                    "height": None,
                    "format": ext[1:].upper(),
                    "ocr_ready": False,
                    "note": "EMF/WMF format, needs conversion for OCR"
                }
                manifest.append(entry)
                saved += 1
                continue

            # 尝试用Pillow读取获取尺寸
            try:
                img = Image.open(io.BytesIO(data))
                width, height = img.size
                img_format = img.format or ext[1:].upper()
            except Exception as e:
                width, height = None, None
                img_format = ext[1:].upper()

            # 保存图片
            save_name = f"img_{i:04d}{ext}"
            save_path = images_dir / save_name

            # 如果需要格式转换
            if fmt != 'all' and fmt != ext[1:].lower():
                if fmt == 'jpg' and ext == '.png':
                    # PNG -> JPG转换(去除透明通道)
                    try:
                        img = Image.open(io.BytesIO(data))
                        if img.mode == 'RGBA':
                            bg = Image.new('RGB', img.size, (255, 255, 255))
                            bg.paste(img, mask=img.split()[3])
                            img = bg
                        save_name = f"img_{i:04d}.jpg"
                        save_path = images_dir / save_name
                        img.save(save_path, 'JPEG', quality=95)
                    except Exception:
                        with open(save_path, 'wb') as f:
                            f.write(data)
                else:
                    with open(save_path, 'wb') as f:
                        f.write(data)
            else:
                with open(save_path, 'wb') as f:
                    f.write(data)

            entry = {
                "index": i,
                "original_name": filename,
                "saved_name": save_name,
                "size_bytes": file_size,
                "width": width,
                "height": height,
                "format": img_format,
                "ocr_ready": ext not in ('.emf', '.wmf'),
                "note": ""
            }
            manifest.append(entry)
            saved += 1

            if saved % 50 == 0:
                print(f"  Progress: {i}/{total} processed, {saved} saved, {skipped} skipped")

    # 保存清单
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 输出统计
    total_manifest = len(manifest)
    ocr_ready = sum(1 for m in manifest if m.get('ocr_ready'))
    print(f"\n=== Extraction Complete ===")
    print(f"Total media files: {total}")
    print(f"Saved images: {saved}")
    print(f"Skipped (too small): {skipped}")
    print(f"OCR-ready images: {ocr_ready}")
    print(f"Output directory: {images_dir}")
    print(f"Manifest saved: {manifest_path}")

    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Extract images from docx file')
    parser.add_argument('docx_path', help='Path to the docx file')
    parser.add_argument('output_dir', help='Output directory for images')
    parser.add_argument('--min-size', type=int, default=5000,
                        help='Minimum file size in bytes (default: 5000)')
    parser.add_argument('--format', choices=['png', 'jpg', 'all'], default='all',
                        help='Output format (default: all)')

    args = parser.parse_args()
    extract_images_from_docx(args.docx_path, args.output_dir, args.min_size, args.format)
