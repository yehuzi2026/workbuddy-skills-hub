#!/usr/bin/env python3
"""
对提取的图片执行OCR识别，将结果保存为结构化JSON。
支持RapidOCR(优先)和PaddleOCR(备选)两种引擎。

用法:
    python ocr_images.py <images_dir> <output_file> [--engine rapidocr|paddleocr] [--min-confidence 0.5]

参数:
    images_dir   : 包含图片的目录(extract_images.py的输出images/子目录)
    output_file  : OCR结果输出JSON文件路径
    --engine     : OCR引擎 rapidocr(默认)或paddleocr
    --min-confidence : 最低置信度阈值(默认0.5)

输出:
    JSON文件，包含每张图片的OCR识别结果:
    [
        {
            "image_file": "img_0001.png",
            "text_blocks": [
                {"text": "...", "confidence": 0.95, "bbox": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]}
            ],
            "full_text": "拼接的完整文本",
            "total_blocks": 10,
            "avg_confidence": 0.92
        },
        ...
    ]
"""

import os
import sys
import json
import argparse
from pathlib import Path


def init_rapidocr():
    """初始化RapidOCR引擎"""
    try:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        print("RapidOCR engine initialized successfully")
        return engine, 'rapidocr'
    except ImportError:
        print("RapidOCR not available, trying fallback...")
        return None, None


def init_paddleocr():
    """初始化PaddleOCR引擎(备选)"""
    try:
        from paddleocr import PaddleOCR
        engine = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
        print("PaddleOCR engine initialized successfully")
        return engine, 'paddleocr'
    except ImportError:
        print("PaddleOCR not available")
        return None, None


def ocr_with_rapidocr(engine, image_path):
    """使用RapidOCR识别单张图片"""
    result, elapse = engine(image_path)

    text_blocks = []
    if result:
        for item in result:
            bbox, text, confidence = item
            text_blocks.append({
                "text": text,
                "confidence": round(float(confidence), 4),
                "bbox": bbox
            })

    full_text = "\n".join([b["text"] for b in text_blocks])
    avg_conf = (sum(b["confidence"] for b in text_blocks) / len(text_blocks)
                if text_blocks else 0)

    return {
        "text_blocks": text_blocks,
        "full_text": full_text,
        "total_blocks": len(text_blocks),
        "avg_confidence": round(avg_conf, 4)
    }


def ocr_with_paddleocr(engine, image_path):
    """使用PaddleOCR识别单张图片"""
    result = engine.ocr(image_path, cls=True)

    text_blocks = []
    if result and result[0]:
        for line in result[0]:
            bbox = line[0]
            text = line[1][0]
            confidence = line[1][1]
            text_blocks.append({
                "text": text,
                "confidence": round(float(confidence), 4),
                "bbox": bbox
            })

    full_text = "\n".join([b["text"] for b in text_blocks])
    avg_conf = (sum(b["confidence"] for b in text_blocks) / len(text_blocks)
                if text_blocks else 0)

    return {
        "text_blocks": text_blocks,
        "full_text": full_text,
        "total_blocks": len(text_blocks),
        "avg_confidence": round(avg_conf, 4)
    }


def ocr_images(images_dir, output_file, engine_name='rapidocr', min_confidence=0.5):
    """批量OCR识别图片"""
    images_dir = Path(images_dir)

    if not images_dir.exists():
        print(f"ERROR: Directory not found: {images_dir}")
        sys.exit(1)

    # 加载manifest(如果存在)
    manifest_path = images_dir.parent / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)
            for item in manifest_data:
                manifest[item.get('saved_name', '')] = item

    # 初始化OCR引擎
    engine = None
    actual_engine = None

    if engine_name == 'rapidocr':
        engine, actual_engine = init_rapidocr()
        if engine is None:
            engine, actual_engine = init_paddleocr()
    else:
        engine, actual_engine = init_paddleocr()
        if engine is None:
            engine, actual_engine = init_rapidocr()

    if engine is None:
        print("ERROR: No OCR engine available!")
        print("Please install one of:")
        print("  pip install rapidocr-onnxruntime  (recommended, lightweight)")
        print("  pip install paddleocr              (more accurate, heavier)")
        sys.exit(1)

    print(f"Using OCR engine: {actual_engine}")

    # 获取图片文件列表
    supported_ext = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'}
    image_files = sorted([
        f for f in images_dir.iterdir()
        if f.suffix.lower() in supported_ext and f.is_file()
    ])

    if not image_files:
        print(f"No supported image files found in {images_dir}")
        sys.exit(0)

    print(f"Found {len(image_files)} images to process")

    # OCR函数映射
    ocr_func = ocr_with_rapidocr if actual_engine == 'rapidocr' else ocr_with_paddleocr

    results = []
    for i, img_path in enumerate(image_files, 1):
        print(f"  [{i}/{len(image_files)}] Processing: {img_path.name}...", end=" ")

        try:
            ocr_result = ocr_func(engine, str(img_path))

            # 过滤低置信度文本
            filtered_blocks = [
                b for b in ocr_result["text_blocks"]
                if b["confidence"] >= min_confidence
            ]

            entry = {
                "image_file": img_path.name,
                "text_blocks": filtered_blocks,
                "full_text": "\n".join([b["text"] for b in filtered_blocks]),
                "total_blocks": len(filtered_blocks),
                "avg_confidence": (sum(b["confidence"] for b in filtered_blocks) / len(filtered_blocks)
                                   if filtered_blocks else 0),
                "original_name": manifest.get(img_path.name, {}).get('original_name', ''),
                "size_bytes": manifest.get(img_path.name, {}).get('size_bytes', 0),
            }

            print(f"{entry['total_blocks']} blocks, avg_conf={entry['avg_confidence']:.2f}")
            results.append(entry)

        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                "image_file": img_path.name,
                "text_blocks": [],
                "full_text": "",
                "total_blocks": 0,
                "avg_confidence": 0,
                "error": str(e)
            })

    # 保存结果
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 统计
    total_images = len(results)
    images_with_text = sum(1 for r in results if r['total_blocks'] > 0)
    total_blocks = sum(r['total_blocks'] for r in results)

    print(f"\n=== OCR Complete ===")
    print(f"Images processed: {total_images}")
    print(f"Images with text: {images_with_text}")
    print(f"Total text blocks: {total_blocks}")
    print(f"Results saved: {output_path}")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='OCR images from bid documents')
    parser.add_argument('images_dir', help='Directory containing images')
    parser.add_argument('output_file', help='Output JSON file path')
    parser.add_argument('--engine', choices=['rapidocr', 'paddleocr'], default='rapidocr',
                        help='OCR engine to use (default: rapidocr)')
    parser.add_argument('--min-confidence', type=float, default=0.5,
                        help='Minimum confidence threshold (default: 0.5)')

    args = parser.parse_args()
    ocr_images(args.images_dir, args.output_file, args.engine, args.min_confidence)
