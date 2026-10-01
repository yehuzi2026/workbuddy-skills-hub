#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
法律风险计算器 (Legal Risk Calculator)
=====================================
全能型法律审核守护者的风险量化工具

基于万物互爱安好哲学体系，为法律风险评估提供精确的量化工具。
风险评分 = 发生概率(P) × 影响程度(I) × 不可逆性系数(U)

支持三种运行模式：
1. 交互模式：逐步引导用户输入风险参数
2. 命令行模式：通过命令行参数批量计算
3. JSON输入模式：从JSON文件批量读取风险数据

使用方式：
    # 交互模式
    python legal_risk_calculator.py

    # 命令行模式
    python legal_risk_calculator.py --probability 4 --impact 5 --irreversibility 1.5

    # JSON批量模式
    python legal_risk_calculator.py --input risks.json --format report

输出格式：
    report：人类可读的报告格式
    json：JSON格式（便于程序处理）
    summary：简短摘要格式
"""

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple


# ============================================================
# 风险等级定义
# ============================================================

RISK_LEVELS = [
    {"min_score": 40, "level": "极高风险", "color": "🔴", "response": "立即专项审核 + 高层报告 + 应急措施"},
    {"min_score": 25, "level": "高风险", "color": "🟠", "response": "优先审核 + 持续监控 + 整改计划"},
    {"min_score": 15, "level": "中等风险", "color": "🟡", "response": "纳入审核计划 + 定期监控"},
    {"min_score": 5, "level": "低风险", "color": "🟢", "response": "常规监控 + 改善建议"},
    {"min_score": 0, "level": "极低风险", "color": "⚪", "response": "记录备案"},
]

# 七维法律风险类别
RISK_CATEGORIES = {
    "contract": "合同法律风险",
    "governance": "公司治理法律风险",
    "labor": "劳动法律风险",
    "ip": "知识产权法律风险",
    "finance_tax": "财税法律风险",
    "data_compliance": "数据合规法律风险",
    "litigation": "争议解决与诉讼风险",
}


# ============================================================
# 风险评分计算
# ============================================================

def calculate_risk_score(probability: int, impact: int, irreversibility: float) -> float:
    """
    计算法律风险评分

    参数:
        probability: 发生概率 (1-5)
        impact: 影响程度 (1-5)
        irreversibility: 不可逆性系数 (1.0-2.0)

    返回:
        风险评分 (float)
    """
    # 参数校验
    if not (1 <= probability <= 5):
        raise ValueError(f"发生概率必须在1-5之间，当前值: {probability}")
    if not (1 <= impact <= 5):
        raise ValueError(f"影响程度必须在1-5之间，当前值: {impact}")
    if not (1.0 <= irreversibility <= 2.0):
        raise ValueError(f"不可逆性系数必须在1.0-2.0之间，当前值: {irreversibility}")

    score = probability * impact * irreversibility
    return round(score, 1)


def get_risk_level(score: float) -> Dict:
    """
    根据风险评分获取风险等级信息

    参数:
        score: 风险评分

    返回:
        包含风险等级信息的字典
    """
    for level in RISK_LEVELS:
        if score >= level["min_score"]:
            return level
    return RISK_LEVELS[-1]


def get_probability_description(p: int) -> str:
    """获取发生概率的描述"""
    descriptions = {
        1: "极低（<5%）- 有完善的防控措施，历史无类似风险发生",
        2: "较低（5%-20%）- 有较好的防控措施，历史极少发生",
        3: "中等（20%-50%）- 防控措施一般，历史偶有发生",
        4: "较高（50%-80%）- 防控措施薄弱，历史时有发生",
        5: "极高（>80%）- 无防控措施或防控失效，历史频繁发生",
    }
    return descriptions.get(p, "未知")


def get_impact_description(i: int) -> str:
    """获取影响程度的描述"""
    descriptions = {
        1: "微小 - 损失<10万元，无法律后果，无声誉影响",
        2: "较小 - 损失10-100万元，轻微违法无处罚，内部知晓",
        3: "中等 - 损失100-1000万元，行政处罚罚款较小，行业内知晓",
        4: "严重 - 损失1000万-1亿元，重大行政处罚或民事赔偿，媒体曝光",
        5: "灾难性 - 损失>1亿元，刑事责任或吊销资质，全国性声誉危机",
    }
    return descriptions.get(i, "未知")


def get_irreversibility_description(u: float) -> str:
    """获取不可逆性系数的描述"""
    descriptions = {
        1.0: "完全可逆 - 金钱损失可通过追偿恢复",
        1.2: "基本可逆 - 损失可通过努力大部分恢复",
        1.5: "部分不可逆 - 部分损失无法恢复（如声誉损害）",
        1.8: "大部分不可逆 - 重大损害难以恢复（如吊销资质）",
        2.0: "完全不可逆 - 无法恢复（如刑事责任、人员伤亡）",
    }
    # 找到最接近的描述
    closest = min(descriptions.keys(), key=lambda x: abs(x - u))
    return descriptions[closest]


# ============================================================
# 风险评估结果
# ============================================================

def assess_risk(
    probability: int,
    impact: int,
    irreversibility: float,
    category: str = "",
    description: str = "",
    risk_id: str = "",
) -> Dict:
    """
    完整的风险评估

    返回包含所有评估信息的字典
    """
    score = calculate_risk_score(probability, impact, irreversibility)
    level_info = get_risk_level(score)

    return {
        "risk_id": risk_id,
        "category": category,
        "category_name": RISK_CATEGORIES.get(category, category),
        "description": description,
        "probability": probability,
        "probability_description": get_probability_description(probability),
        "impact": impact,
        "impact_description": get_impact_description(impact),
        "irreversibility": irreversibility,
        "irreversibility_description": get_irreversibility_description(irreversibility),
        "risk_score": score,
        "risk_level": level_info["level"],
        "risk_color": level_info["color"],
        "response": level_info["response"],
    }


# ============================================================
# 输出格式化
# ============================================================

def format_report(result: Dict) -> str:
    """格式化为人类可读的报告"""
    lines = []
    lines.append("=" * 60)
    lines.append("           法律风险评估报告")
    lines.append("=" * 60)
    lines.append("")

    if result.get("risk_id"):
        lines.append(f"风险编号: {result['risk_id']}")
    if result.get("category_name"):
        lines.append(f"风险类别: {result['category_name']}")
    if result.get("description"):
        lines.append(f"风险描述: {result['description']}")
    lines.append("")

    lines.append("-" * 60)
    lines.append("一、风险参数")
    lines.append("-" * 60)
    lines.append(f"  发生概率 (P):     {result['probability']}/5")
    lines.append(f"    └ {result['probability_description']}")
    lines.append(f"  影响程度 (I):     {result['impact']}/5")
    lines.append(f"    └ {result['impact_description']}")
    lines.append(f"  不可逆性系数 (U): {result['irreversibility']}")
    lines.append(f"    └ {result['irreversibility_description']}")
    lines.append("")

    lines.append("-" * 60)
    lines.append("二、风险评估结果")
    lines.append("-" * 60)
    lines.append(f"  风险评分: {result['risk_score']}")
    lines.append(f"    公式: P × I × U = {result['probability']} × {result['impact']} × {result['irreversibility']} = {result['risk_score']}")
    lines.append(f"  风险等级: {result['risk_color']} {result['risk_level']}")
    lines.append(f"  响应要求: {result['response']}")
    lines.append("")

    # 哲学校准提示
    lines.append("-" * 60)
    lines.append("三、哲学校准提示")
    lines.append("-" * 60)
    lines.append("  ⚠ 法思僭越检查: 风险评分是辅助工具，不能替代专业法律判断")
    lines.append("  ⚠ 诗心校准: 关注风险背后真实的人——谁因此受伤？")
    lines.append("  ⚠ 和想象力: 在'承受风险'与'放弃机会'之间寻找第三条路")
    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def format_summary(result: Dict) -> str:
    """格式化为简短摘要"""
    return (
        f"{result['risk_color']} [{result['risk_level']}] "
        f"评分:{result['risk_score']} "
        f"(P={result['probability']}, I={result['impact']}, U={result['irreversibility']}) "
        f"- {result['response']}"
    )


def format_batch_report(results: List[Dict]) -> str:
    """格式化批量评估报告"""
    lines = []
    lines.append("=" * 60)
    lines.append("           法律风险评估汇总报告")
    lines.append("=" * 60)
    lines.append("")

    # 按类别分组统计
    category_stats = {}
    level_stats = {}
    for r in results:
        cat = r.get("category_name", "未分类")
        if cat not in category_stats:
            category_stats[cat] = []
        category_stats[cat].append(r)

        level = r["risk_level"]
        level_stats[level] = level_stats.get(level, 0) + 1

    # 风险等级统计
    lines.append("-" * 60)
    lines.append("一、风险等级分布")
    lines.append("-" * 60)
    for level_info in RISK_LEVELS:
        count = level_stats.get(level_info["level"], 0)
        lines.append(f"  {level_info['color']} {level_info['level']}: {count}项")
    lines.append(f"  总计: {len(results)}项")
    lines.append("")

    # 按类别统计
    lines.append("-" * 60)
    lines.append("二、按类别分布")
    lines.append("-" * 60)
    for cat, risks in category_stats.items():
        scores = [r["risk_score"] for r in risks]
        avg_score = sum(scores) / len(scores) if scores else 0
        max_score = max(scores) if scores else 0
        lines.append(f"  {cat}: {len(risks)}项 (平均分:{avg_score:.1f}, 最高分:{max_score:.1f})")
    lines.append("")

    # 风险清单（按评分降序）
    sorted_results = sorted(results, key=lambda x: x["risk_score"], reverse=True)
    lines.append("-" * 60)
    lines.append("三、风险清单（按评分降序）")
    lines.append("-" * 60)
    lines.append(f"{'序号':<4} {'编号':<8} {'类别':<16} {'评分':<6} {'等级':<8} {'描述'}")
    lines.append("-" * 60)
    for i, r in enumerate(sorted_results, 1):
        desc = r.get("description", "")[:30]
        if len(r.get("description", "")) > 30:
            desc += "..."
        lines.append(
            f"{i:<4} {r.get('risk_id', '-'):<8} {r.get('category_name', '-')[:14]:<16} "
            f"{r['risk_score']:<6} {r['risk_color']}{r['risk_level']:<6} {desc}"
        )
    lines.append("")

    # 高风险项详情
    high_risks = [r for r in sorted_results if r["risk_score"] >= 25]
    if high_risks:
        lines.append("-" * 60)
        lines.append("四、高风险项详情（评分≥25）")
        lines.append("-" * 60)
        for r in high_risks:
            lines.append(f"\n  {r['risk_color']} {r.get('risk_id', '')} - {r['risk_level']} (评分:{r['risk_score']})")
            if r.get("description"):
                lines.append(f"  描述: {r['description']}")
            lines.append(f"  P={r['probability']}({r['probability_description'][:20]}...)")
            lines.append(f"  I={r['impact']}({r['impact_description'][:20]}...)")
            lines.append(f"  U={r['irreversibility']}({r['irreversibility_description'][:20]}...)")
            lines.append(f"  响应: {r['response']}")
    lines.append("")
    lines.append("=" * 60)
    lines.append("言语无相 — 本报告是特定时点的风险评估，须持续更新。")
    lines.append("=" * 60)

    return "\n".join(lines)


# ============================================================
# 交互模式
# ============================================================

def interactive_mode():
    """交互式风险评估"""
    print()
    print("=" * 60)
    print("     法律风险计算器 - 交互模式")
    print("     基于万物互爱安好哲学体系")
    print("=" * 60)
    print()

    results = []

    while True:
        print("\n" + "-" * 60)
        print("请输入风险评估参数（输入q退出）")
        print("-" * 60)

        # 风险编号
        risk_id = input("风险编号（可选，回车跳过）: ").strip()
        if risk_id.lower() == "q":
            break

        # 风险类别
        print("\n风险类别:")
        for k, v in RISK_CATEGORIES.items():
            print(f"  {k}: {v}")
        category = input("请输入类别编号（回车跳过）: ").strip()
        if category.lower() == "q":
            break

        # 风险描述
        description = input("风险描述（可选）: ").strip()
        if description.lower() == "q":
            break

        # 发生概率
        print("\n--- 发生概率 (P) ---")
        for i in range(1, 6):
            print(f"  {i}: {get_probability_description(i)}")
        while True:
            try:
                p_input = input("请输入发生概率 (1-5): ").strip()
                if p_input.lower() == "q":
                    sys.exit(0)
                probability = int(p_input)
                if 1 <= probability <= 5:
                    break
                print("⚠ 请输入1-5之间的整数")
            except ValueError:
                print("⚠ 请输入有效整数")

        # 影响程度
        print("\n--- 影响程度 (I) ---")
        for i in range(1, 6):
            print(f"  {i}: {get_impact_description(i)}")
        while True:
            try:
                i_input = input("请输入影响程度 (1-5): ").strip()
                if i_input.lower() == "q":
                    sys.exit(0)
                impact = int(i_input)
                if 1 <= impact <= 5:
                    break
                print("⚠ 请输入1-5之间的整数")
            except ValueError:
                print("⚠ 请输入有效整数")

        # 不可逆性系数
        print("\n--- 不可逆性系数 (U) ---")
        for u in [1.0, 1.2, 1.5, 1.8, 2.0]:
            print(f"  {u}: {get_irreversibility_description(u)}")
        while True:
            try:
                u_input = input("请输入不可逆性系数 (1.0-2.0): ").strip()
                if u_input.lower() == "q":
                    sys.exit(0)
                irreversibility = float(u_input)
                if 1.0 <= irreversibility <= 2.0:
                    break
                print("⚠ 请输入1.0-2.0之间的数值")
            except ValueError:
                print("⚠ 请输入有效数值")

        # 评估
        result = assess_risk(
            probability=probability,
            impact=impact,
            irreversibility=irreversibility,
            category=category,
            description=description,
            risk_id=risk_id,
        )

        print()
        print(format_report(result))
        results.append(result)

        # 是否继续
        cont = input("\n是否继续评估其他风险？(y/n): ").strip().lower()
        if cont != "y":
            break

    # 批量汇总
    if len(results) > 1:
        print("\n\n")
        print(format_batch_report(results))

    print("\n评估完成。致一而行——请根据评估结果采取相应行动。")


# ============================================================
# 命令行模式
# ============================================================

def command_line_mode(args):
    """命令行参数模式"""
    try:
        result = assess_risk(
            probability=args.probability,
            impact=args.impact,
            irreversibility=args.irreversibility,
            category=args.category or "",
            description=args.description or "",
            risk_id=args.risk_id or "",
        )

        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.format == "summary":
            print(format_summary(result))
        else:
            print(format_report(result))

    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


# ============================================================
# JSON批量模式
# ============================================================

def json_batch_mode(args):
    """JSON文件批量模式"""
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            risks_data = json.load(f)

        # 支持单个风险对象或风险数组
        if isinstance(risks_data, dict):
            risks_data = [risks_data]

        results = []
        for risk in risks_data:
            try:
                result = assess_risk(
                    probability=risk["probability"],
                    impact=risk["impact"],
                    irreversibility=risk["irreversibility"],
                    category=risk.get("category", ""),
                    description=risk.get("description", ""),
                    risk_id=risk.get("risk_id", ""),
                )
                results.append(result)
            except (KeyError, ValueError) as e:
                print(f"警告: 跳过无效风险项 {risk.get('risk_id', '?')}: {e}", file=sys.stderr)

        if args.format == "json":
            print(json.dumps(results, ensure_ascii=False, indent=2))
        elif args.format == "summary":
            for r in results:
                print(format_summary(r))
        else:
            if len(results) == 1:
                print(format_report(results[0]))
            else:
                print(format_batch_report(results))

    except FileNotFoundError:
        print(f"错误: 文件不存在 - {args.input}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"错误: JSON解析失败 - {e}", file=sys.stderr)
        sys.exit(1)


# ============================================================
# 演示模式
# ============================================================

def demo_mode():
    """演示模式 - 展示典型法律风险场景"""
    demo_risks = [
        {
            "risk_id": "C-001",
            "category": "contract",
            "description": "核心业务合同未约定争议解决条款",
            "probability": 3,
            "impact": 3,
            "irreversibility": 1.5,
        },
        {
            "risk_id": "L-001",
            "category": "labor",
            "description": "部分员工入职超1个月未签订书面劳动合同",
            "probability": 5,
            "impact": 3,
            "irreversibility": 1.2,
        },
        {
            "risk_id": "D-001",
            "category": "data_compliance",
            "description": "APP收集个人信息未取得用户有效同意",
            "probability": 4,
            "impact": 4,
            "irreversibility": 1.5,
        },
        {
            "risk_id": "I-001",
            "category": "ip",
            "description": "核心技术未申请专利且未作商业秘密保护",
            "probability": 3,
            "impact": 5,
            "irreversibility": 2.0,
        },
        {
            "risk_id": "S-001",
            "category": "litigation",
            "description": "重要债权即将超过诉讼时效",
            "probability": 4,
            "impact": 4,
            "irreversibility": 2.0,
        },
    ]

    results = []
    for risk in demo_risks:
        result = assess_risk(
            probability=risk["probability"],
            impact=risk["impact"],
            irreversibility=risk["irreversibility"],
            category=risk["category"],
            description=risk["description"],
            risk_id=risk["risk_id"],
        )
        results.append(result)

    print()
    print(format_batch_report(results))


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="法律风险计算器 - 基于万物互爱安好哲学体系",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 交互模式
  python legal_risk_calculator.py

  # 命令行模式
  python legal_risk_calculator.py --probability 4 --impact 5 --irreversibility 1.5

  # JSON批量模式
  python legal_risk_calculator.py --input risks.json --format report

  # 演示模式
  python legal_risk_calculator.py --demo

风险评分公式: 风险评分 = 发生概率(P) × 影响程度(I) × 不可逆性系数(U)
  P: 1-5 (1=极低, 5=极高)
  I: 1-5 (1=微小, 5=灾难性)
  U: 1.0-2.0 (1.0=完全可逆, 2.0=完全不可逆)
        """,
    )

    parser.add_argument(
        "--probability", "-p",
        type=int,
        choices=[1, 2, 3, 4, 5],
        help="发生概率 (1-5)",
    )
    parser.add_argument(
        "--impact", "-i",
        type=int,
        choices=[1, 2, 3, 4, 5],
        help="影响程度 (1-5)",
    )
    parser.add_argument(
        "--irreversibility", "-u",
        type=float,
        help="不可逆性系数 (1.0-2.0)",
    )
    parser.add_argument(
        "--category", "-c",
        type=str,
        choices=list(RISK_CATEGORIES.keys()),
        help="风险类别",
    )
    parser.add_argument(
        "--description", "-d",
        type=str,
        help="风险描述",
    )
    parser.add_argument(
        "--risk-id",
        type=str,
        help="风险编号",
    )
    parser.add_argument(
        "--input",
        type=str,
        help="JSON输入文件路径（批量模式）",
    )
    parser.add_argument(
        "--format", "-f",
        type=str,
        choices=["report", "json", "summary"],
        default="report",
        help="输出格式 (默认: report)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="运行演示模式",
    )

    args = parser.parse_args()

    # 演示模式
    if args.demo:
        demo_mode()
        return

    # JSON批量模式
    if args.input:
        json_batch_mode(args)
        return

    # 命令行模式
    if args.probability is not None and args.impact is not None and args.irreversibility is not None:
        command_line_mode(args)
        return

    # 交互模式（默认）
    interactive_mode()


if __name__ == "__main__":
    main()
