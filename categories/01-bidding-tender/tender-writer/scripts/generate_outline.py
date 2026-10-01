# -*- coding: utf-8 -*-
"""
generate_outline.py · 提纲生成脚本（阶段 3）

输入:
    output/scoring_matrix.csv

输出:
    output/outline.md

目标:
    1. 按“应答章节”聚合评分矩阵
    2. 为每一章标注总分
    3. 为每一节标注覆盖的矩阵行号
    4. 在文末输出覆盖度自检表
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import OrderedDict
from pathlib import Path


def load_matrix(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=1):
            row["_row_no"] = idx
            row["_score"] = float((row.get("分值") or "0").strip() or 0)
            rows.append(row)
    return rows


def chapter_sort_key(title: str, fallback_index: int) -> tuple[int, int]:
    match = re.search(r"第([一二三四五六七八九十百0-9]+)章", title)
    if not match:
        return (999, fallback_index)

    chinese = match.group(1)
    mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if chinese.isdigit():
        return (int(chinese), fallback_index)
    if chinese in mapping:
        return (mapping[chinese], fallback_index)
    if chinese.startswith("十") and len(chinese) == 2:
        return (10 + mapping.get(chinese[1], 0), fallback_index)
    return (999, fallback_index)


def build_outline(rows: list[dict]) -> str:
    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    for row in rows:
        chapter = (row.get("应答章节") or "").strip() or "【待用户指定章节】"
        grouped.setdefault(chapter, []).append(row)

    ordered_chapters = sorted(
        grouped.items(),
        key=lambda item: chapter_sort_key(item[0], list(grouped.keys()).index(item[0])),
    )

    lines: list[str] = []
    lines.append("# 标书提纲（outline）")
    lines.append("")
    lines.append("> 本提纲由 `generate_outline.py` 基于 `scoring_matrix.csv` 自动生成。")
    lines.append("> 每一章、每一节都应继续人工复核，确认章节命名、顺序和覆盖关系无误。")
    lines.append("")
    lines.append("---")
    lines.append("")

    for chapter_index, (chapter, chapter_rows) in enumerate(ordered_chapters, start=1):
        chapter_score = sum(row["_score"] for row in chapter_rows)
        lines.append(f"## {chapter}（对应 {chapter_score:g} 分）")
        lines.append("")

        for item_index, row in enumerate(chapter_rows, start=1):
            row_label = f"R{row['_row_no']:02d}"
            item_name = (row.get("评分项") or "").strip() or "【待补充评分项】"
            keywords = (row.get("关键词") or "").strip() or "【待补充】"
            evidence = (row.get("证据材料") or "").strip() or "【待补充】"
            risk = (row.get("风险提示") or "").strip() or "无"
            score = row["_score"]

            lines.append(f"### {chapter_index}.{item_index} {item_name}（对应 {row_label}，{score:g} 分）")
            lines.append(f"- 覆盖评分矩阵行：{row_label}")
            lines.append(f"- 建议关键词：{keywords}")
            lines.append(f"- 建议证据材料：{evidence}")
            lines.append(f"- 风险提示：{risk}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 覆盖度自检")
    lines.append("")
    lines.append("| 矩阵行号 | 评分项 | 分值 | 覆盖章节 | 风险提示 |")
    lines.append("|---|---|---:|---|---|")
    for row in rows:
        row_label = f"R{row['_row_no']:02d}"
        item_name = (row.get("评分项") or "").strip()
        chapter = (row.get("应答章节") or "").strip()
        risk = (row.get("风险提示") or "").strip()
        lines.append(f"| {row_label} | {item_name} | {row['_score']:g} | {chapter} | {risk} |")

    total_score = sum(row["_score"] for row in rows)
    lines.append("")
    lines.append(f"合计覆盖分值：{total_score:g} 分")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="提纲生成（阶段 3）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("matrix_csv", help="评分矩阵 CSV 路径")
    parser.add_argument("--out", default="output", help="输出目录，默认 output/")
    args = parser.parse_args()

    matrix_csv = Path(args.matrix_csv)
    if not matrix_csv.exists():
        print(f"[错误] 找不到评分矩阵: {matrix_csv}", file=sys.stderr)
        sys.exit(1)

    rows = load_matrix(matrix_csv)
    if not rows:
        print("[错误] 评分矩阵为空，无法生成提纲。", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    outline_path = out_dir / "outline.md"
    outline_path.write_text(build_outline(rows), encoding="utf-8")

    print(f"[完成] 提纲已写入: {outline_path}")
    print()
    print("=" * 60)
    print("阶段 3 完成。下一步:")
    print("  1. 用户复核 outline.md 的章节命名和顺序")
    print("  2. 确认无遗漏后，进入阶段 4 分章节撰写")
    print("=" * 60)


if __name__ == "__main__":
    main()
