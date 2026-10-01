#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务类技术方案 — 图片插入脚本
功能：根据 checkpoint.json 中的 image_folder_path，
     自动将图片占位符插入到各章节 Markdown 文件中。
路径已在 Step 2.6 收集，Phase 3 写作时调用此脚本。
"""

import os
import json
import re
import sys
from pathlib import Path


def load_checkpoint(workspace_dir):
    """加载 checkpoint.json"""
    cp_path = os.path.join(workspace_dir, "checkpoint.json")
    if not os.path.exists(cp_path):
        print("[SKIP] checkpoint.json 不存在，跳过图片插入")
        return None
    with open(cp_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_images_in_folder(folder_path):
    """
    读取图片文件夹，每章只返回一张图片。
    按文件夹名称分组，每个文件夹取第一张（字母序）。
    """
    images = {}
    if not os.path.isdir(folder_path):
        print(f"[WARN] 图片路径无效: {folder_path}")
        return images

    for root, dirs, files in os.walk(folder_path):
        # 只处理直接包含图片的文件夹
        image_files = [f for f in files if f.lower().endswith(
            ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp')
        )]
        if not image_files:
            continue

        # 每个文件夹取第一张（字母序）
        first_image = sorted(image_files)[0]
        folder_name = os.path.basename(root)
        images[folder_name] = {
            "path": os.path.join(root, first_image),
            "filename": first_image,
            "folder": folder_name,
        }

    return images


def match_image_to_chapter(image_info, chapter_md_path):
    """
    判断图片是否匹配某个章节。
    匹配规则：
    1. 文件夹名 == ## 标题名（精确匹配）
    2. 文件夹关键词 ∈ ### 子标题名（包含匹配）
    """
    if not os.path.exists(chapter_md_path):
        return False

    with open(chapter_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    folder_name = image_info["folder"]

    # 规则1：文件夹名精确匹配 H2 标题
    h2_pattern = rf'^##\s+.*{re.escape(folder_name)}.*$'
    if re.search(h2_pattern, content, re.MULTILINE):
        return True

    # 规则2：文件夹关键词在 H3 标题中出现
    h3_pattern = rf'^###\s+.*{re.escape(folder_name)}.*$'
    if re.search(h3_pattern, content, re.MULTILINE):
        return True

    return False


def insert_image_placeholder(chapter_md_path, image_info, chapter_num):
    """
    在章节 MD 中插入图片占位符 ![]()
    插入位置：第一个 H3 标题下的第一段正文之后
    """
    if not os.path.exists(chapter_md_path):
        print(f"[SKIP] 章节文件不存在: {chapter_md_path}")
        return

    with open(chapter_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 检查是否已有图片占位符
    if "![" in content:
        print(f"[SKIP] 章节已含图片占位符: {chapter_md_path}")
        return

    # 找到第一个 H3 标题后的正文段落
    lines = content.split("\n")
    insert_index = None
    found_h3 = False

    for i, line in enumerate(lines):
        if line.startswith("### "):
            found_h3 = True
            continue
        if found_h3 and line.strip() and not line.startswith("#"):
            # 找到第一段正文之后的位置
            insert_index = i + 1
            break

    if insert_index is None:
        # 回退：插入到第一个 H2 标题下方
        for i, line in enumerate(lines):
            if line.startswith("## "):
                insert_index = i + 2
                break

    if insert_index is None:
        print(f"[SKIP] 未找到合适的插入位置: {chapter_md_path}")
        return

    # 生成图片标题
    caption = f"图{chapter_num}-1  {image_info['folder']}"
    placeholder = f"\n![{caption}]({image_info['path']})\n"

    # 插入占位符
    lines.insert(insert_index, placeholder)

    with open(chapter_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[OK] 已插入图片占位符: {caption} → {chapter_md_path}")


def main(workspace_dir=None):
    """主函数：自动检测图片路径并插入占位符"""
    if workspace_dir is None:
        workspace_dir = os.getcwd()

    cp = load_checkpoint(workspace_dir)
    if cp is None:
        return

    image_folder = cp.get("image_folder_path", "")
    if not image_folder:
        print("[SKIP] image_folder_path 为空，跳过图片插入")
        return

    # 加载图片目录
    images = get_images_in_folder(image_folder)
    if not images:
        print("[SKIP] 图片文件夹中无有效图片")
        return

    print(f"[INFO] 发现 {len(images)} 个图片文件夹: {list(images.keys())}")

    # 扫描章节文件
    docx_build = os.path.join(workspace_dir, "docx_build")
    if not os.path.isdir(docx_build):
        print("[SKIP] docx_build 目录不存在")
        return

    chapter_files = sorted([
        f for f in os.listdir(docx_build) if f.startswith("章节") and f.endswith(".md")
    ])

    if not chapter_files:
        print("[SKIP] 未找到章节 MD 文件")
        return

    # 逐章匹配图片
    matched = {}
    for chapter_file in chapter_files:
        chapter_path = os.path.join(docx_build, chapter_file)
        # 提取章节编号
        match = re.search(r'章节(\d+)', chapter_file)
        chapter_num = int(match.group(1)) if match else 0

        for folder_name, img_info in images.items():
            if folder_name in matched:
                continue  # 该图片已被匹配

            if match_image_to_chapter(img_info, chapter_path):
                insert_image_placeholder(chapter_path, img_info, chapter_num)
                matched[folder_name] = chapter_file
                break  # 每章仅一张

    # 汇总
    print("\n=== 配图汇总 ===")
    if matched:
        for folder, chapter in matched.items():
            print(f"  {folder} → {chapter}")
    else:
        print("  无匹配图片")
    print(f"  总计: {len(matched)}/{len(images)} 张图片已匹配")


if __name__ == "__main__":
    ws = sys.argv[1] if len(sys.argv) > 1 else None
    main(ws)
