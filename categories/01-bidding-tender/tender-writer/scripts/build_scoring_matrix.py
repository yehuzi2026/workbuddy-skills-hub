# -*- coding: utf-8 -*-
"""
build_scoring_matrix.py · 评分矩阵构建脚本（阶段 2）

输入:
    tender_brief.md 或 tender_brief.json

输出:
    output/scoring_matrix.csv

目标:
    1. 尽量从评分办法原文中逐条提取评分项
    2. 对“项目理解、需求分析、技术路线（共15分）”这类复合项进行拆分
    3. 为后续提纲和正文撰写提供逐行可追踪的矩阵
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

CSV_HEADERS = ["评分项", "分值", "关键词", "应答章节", "证据材料", "风险提示"]

TOTAL_ITEM_NAMES = {
    "合计",
    "总分",
    "总计",
    "技术分",
    "商务分",
    "价格分",
    "报价分",
}

KEYWORD_TO_CHAPTER = {
    "项目理解": "第二章 项目理解与需求分析",
    "需求分析": "第二章 项目理解与需求分析",
    "需求理解": "第二章 项目理解与需求分析",
    "项目背景": "第二章 项目理解与需求分析",
    "现状分析": "第二章 项目理解与需求分析",
    "难点": "第二章 项目理解与需求分析",
    "技术方案": "第三章 技术方案",
    "技术架构": "第三章 技术方案",
    "技术路线": "第三章 技术方案",
    "功能模块": "第三章 技术方案",
    "数据架构": "第三章 技术方案",
    "数据治理": "第三章 技术方案",
    "接口": "第三章 技术方案",
    "集成": "第三章 技术方案",
    "安全": "第三章 技术方案",
    "部署": "第三章 技术方案",
    "创新": "第三章 技术方案",
    "项目组织": "第四章 质量保证与进度控制",
    "实施计划": "第四章 质量保证与进度控制",
    "进度": "第四章 质量保证与进度控制",
    "质量": "第四章 质量保证与进度控制",
    "测试": "第四章 质量保证与进度控制",
    "风险管理": "第四章 质量保证与进度控制",
    "项目管理": "第四章 质量保证与进度控制",
    "运维": "第五章 售后服务与培训",
    "售后": "第五章 售后服务与培训",
    "培训": "第五章 售后服务与培训",
    "服务承诺": "第五章 售后服务与培训",
    "故障响应": "第五章 售后服务与培训",
    "知识转移": "第五章 售后服务与培训",
    "文档": "第五章 售后服务与培训",
    "业绩": "第六章 公司业绩与资质",
    "资质": "第六章 公司业绩与资质",
    "证书": "第六章 公司业绩与资质",
    "奖项": "第六章 公司业绩与资质",
}

KEYWORD_TO_EVIDENCE = {
    "业绩": "类似项目合同复印件、用户证明、中标公告截图",
    "项目经理": "项目经理身份证、社保、相关证书",
    "团队": "团队成员清单、社保、关键岗位证书",
    "资质": "企业资质证书复印件",
    "证书": "相关证书复印件",
    "奖项": "获奖证书复印件",
    "演示": "演示材料、截图或视频",
    "测试": "第三方测试报告",
    "安全": "等保、密评、制度或方案证明材料",
}

HEADING_PATTERN = re.compile(r"^(#{1,6})\s*(.+?)\s*$")
INLINE_SCORE_PATTERN = re.compile(
    r"(?P<name>[^\n;；。]{2,80}?)[（(]?\s*(?P<score>\d+(?:\.\d+)?)\s*分(?:\)|）)?"
)
TOTAL_SCORE_PATTERN = re.compile(r"(?:共|合计|总计)?\s*(\d+(?:\.\d+)?)\s*分")


PRIMARY_ITEM_PATTERN = re.compile(
    r"^[\-*]?\s*(?P<name>[^:：()（）]{2,50}?)\s*[（(]\s*(?P<score>\d+(?:\.\d+)?)\s*分\s*[)）]"
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_item_name(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^[（(]?[一二三四五六七八九十0-9]+[）).、．\s]+", "", text)
    text = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]+\s*", "", text)
    text = re.sub(r"^[\-*]\s*", "", text)
    text = text.strip("：:；;，,。 ")
    text = re.sub(r"\s+", " ", text)
    return text


def looks_like_total_item(name: str, score: float) -> bool:
    return name in TOTAL_ITEM_NAMES and score >= 20


def split_compound_name(name: str) -> list[str]:
    parts = re.split(r"[、/]", name)
    cleaned = [normalize_item_name(part) for part in parts]
    cleaned = [part for part in cleaned if 2 <= len(part) <= 24]
    if len(cleaned) <= 1:
        return []
    return cleaned


def is_scoring_heading(title: str) -> bool:
    return any(keyword in title for keyword in ("评分", "评标办法", "评审办法", "评审标准", "评分标准"))


def extract_scoring_section_from_md(text: str) -> str:
    lines = text.splitlines()
    collecting = False
    heading_level = None
    collected: list[str] = []

    for line in lines:
        heading_match = HEADING_PATTERN.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2)
            if not collecting and is_scoring_heading(title):
                collecting = True
                heading_level = level
                continue
            if collecting and level <= (heading_level or 6):
                break
        if collecting:
            collected.append(line)

    return "\n".join(collected).strip()


def load_brief(brief_path: Path) -> tuple[str, dict]:
    text = read_text(brief_path)
    if brief_path.suffix.lower() == ".json":
        data = json.loads(text)
        section = data.get("sections", {}).get("scoring", {})
        scoring_text = section.get("content") or section.get("content_preview", "")
        return scoring_text, data
    return extract_scoring_section_from_md(text), {}


def expand_compound_item(name: str, score: float, source_line: str) -> list[dict]:
    split_names = split_compound_name(name)
    if len(split_names) <= 1:
        return [{"raw": name, "score": score, "source_line": source_line, "split_note": ""}]

    if not ("共" in source_line or "合计" in source_line or "总计" in source_line):
        return [{"raw": name, "score": score, "source_line": source_line, "split_note": ""}]

    distributed = round(score / len(split_names), 2)
    split_note = f"原文为复合评分项，按均分拆为 {len(split_names)} 项，需人工复核"
    return [
        {"raw": split_name, "score": distributed, "source_line": source_line, "split_note": split_note}
        for split_name in split_names
    ]


def parse_score_items(scoring_text: str) -> list[dict]:
    items: list[dict] = []
    seen: set[tuple[str, float]] = set()

    for raw_line in scoring_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        primary_match = PRIMARY_ITEM_PATTERN.match(line)
        if primary_match:
            name = normalize_item_name(primary_match.group("name"))
            score = float(primary_match.group("score"))
            if name and not looks_like_total_item(name, score):
                expanded = expand_compound_item(name, score, line)
                for item in expanded:
                    key = (item["raw"], item["score"])
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(item)
                continue

        matches = list(INLINE_SCORE_PATTERN.finditer(line))
        if not matches:
            continue

        for match in matches:
            name = normalize_item_name(match.group("name"))
            score = float(match.group("score"))

            if not name or len(name) < 2:
                continue
            if looks_like_total_item(name, score):
                continue

            expanded = expand_compound_item(name, score, line)
            for item in expanded:
                key = (item["raw"], item["score"])
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)

    return items


def guess_chapter(item_raw: str) -> str:
    for keyword, chapter in KEYWORD_TO_CHAPTER.items():
        if keyword in item_raw:
            return chapter
    return "【待用户指定章节】"


def guess_evidence(item_raw: str) -> str:
    hints = [value for keyword, value in KEYWORD_TO_EVIDENCE.items() if keyword in item_raw]
    if hints:
        return "；".join(dict.fromkeys(hints))
    return "【待补充】"


def build_keywords(item_raw: str) -> str:
    cleaned = re.sub(r"[（）()【】★▲]", "", item_raw)
    parts = re.split(r"[，,、/；;\s]+", cleaned)
    parts = [part.strip() for part in parts if 2 <= len(part.strip()) <= 12]
    return " / ".join(parts[:5]) if parts else item_raw[:20]


def guess_risk(item: dict) -> str:
    item_raw = item["raw"]
    score = item["score"]
    risks: list[str] = []

    if "★" in item_raw or "▲" in item_raw:
        risks.append("★/▲ 实质性响应条款，不允许偏离")
    if score >= 10:
        risks.append("高分值，重点撰写")
    if any(keyword in item_raw for keyword in ("案例", "业绩", "获奖", "证书", "测试报告")):
        risks.append("需附证明材料，提前准备")
    if any(keyword in item_raw for keyword in ("演示", "现场")):
        risks.append("可能涉及现场演示，提前彩排")
    if item.get("split_note"):
        risks.append(item["split_note"])

    return "；".join(risks)


def build_matrix_rows(items: list[dict]) -> list[list[str]]:
    if not items:
        return [[
            "【未自动识别到评分项，请按评分办法逐项补录】",
            "0",
            "",
            "",
            "",
            "请人工通读 tender_brief.md 中的评分办法原文并补录",
        ]]

    rows = []
    for item in items:
        rows.append([
            item["raw"],
            f"{item['score']:g}",
            build_keywords(item["raw"]),
            guess_chapter(item["raw"]),
            guess_evidence(item["raw"]),
            guess_risk(item),
        ])
    return rows


def write_csv_with_bom(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="评分矩阵构建（阶段 2）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("brief_path", help="tender_brief.md 或 tender_brief.json 路径")
    parser.add_argument("--out", default="output", help="输出目录，默认 output/")
    args = parser.parse_args()

    brief_path = Path(args.brief_path)
    if not brief_path.exists():
        print(f"[错误] 找不到 brief 文件: {brief_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[信息] 正在读取: {brief_path}")
    scoring_text, _brief_data = load_brief(brief_path)

    if not scoring_text:
        print("[警告] 未在 brief 中定位到评分章节，将生成待人工补录模板。")

    items = parse_score_items(scoring_text)
    rows = build_matrix_rows(items)
    csv_path = out_dir / "scoring_matrix.csv"
    write_csv_with_bom(csv_path, CSV_HEADERS, rows)

    total_score = sum(item["score"] for item in items)
    print(f"[完成] 评分矩阵已写入: {csv_path}")
    print(f"[信息] 自动识别评分项数量: {len(items)}")
    print(f"[信息] 自动识别评分项总分: {total_score:g} 分")
    print()
    print("=" * 60)
    print("阶段 2 完成。下一步:")
    print(f"  1. 用 Excel/WPS 打开 {csv_path}")
    print("  2. 逐行复核评分项、分值、应答章节、证据材料、风险提示")
    print("  3. 用户确认后进入阶段 3：生成提纲")
    print("     run_script.bat generate_outline.py output/scoring_matrix.csv")
    print("=" * 60)


if __name__ == "__main__":
    main()
