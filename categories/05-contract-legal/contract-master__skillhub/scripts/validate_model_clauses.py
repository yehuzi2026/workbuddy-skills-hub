#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合同智囊 · 示范条款自动校验

把 SKILL.md 中 A7.1「示范条款完整性标准」从模型自觉遵守改造成可执行质量门：
  - 自动检查每条示范条款是否含方向性禁用词
  - 检查简洁版/全面版是否满足最低法律句式要求
  - 检查缺失条款是否仍输出完整双版本

用法：
  # 校验 ledger（推荐，在生成报告/落痕前运行）
  python scripts/validate_model_clauses.py --ledger .workbuddy/review-issues-contract.json

  # 校验包含示范条款的 markdown/json 报告
  python scripts/validate_model_clauses.py --report-text reports/审核报告.md

  # 仅校验单个条款文本
  python scripts/validate_model_clauses.py --single "如乙方未按时交付，每逾期一日按合同总价的千分之一支付违约金。"

返回码：
  0 = 全部示范条款通过校验
  1 = 存在不合格示范条款，必须修复后才能交付

设计原则：
  - 不判断法律正确性，只判断「是否可落地复制」
  - 失败项给出明确位置和原因，便于定向修复
  - 与 ledger 结构天然集成，可直接接入修订前流程
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 方向性禁用词：出现即视为「不是可直接使用的示范条款」
DIRECTIONAL_PHRASES = [
    "建议补充", "建议约定", "应考虑", "可考虑", "可约定", "需约定",
    "需要约定", "需要增加", "建议增加", "应当增加", "应增加",
    "建议明确", "应明确", "需明确", "需要明确", "建议细化",
    "应当约定", "宜约定", "最好约定", "可以约定",
    "应写入", "需写入", "建议写入",
]

# 弱化/含糊表述（出现在简洁版=硬性失败）：仅保留真正含糊、无法落地的词
# 注意：「一般」「大约」「左右」属常见合法量化表述，不应拦截，已移除
WEAK_PHRASES = [
    "尽量", "适时", "视情况", "原则上",
]

# 中文法律句式最低要素：主语（可省略）+ 行为 + 后果/责任
# 通过正则检测是否含有「违约责任 / 支付 / 承担 / 解除 / 终止 / 赔偿 / 返还」等后果词
CONSEQUENCE_KEYWORDS = [
    "违约金", "赔偿", "承担", "支付", "解除", "终止", "返还", "退还",
    "没收", "归", "所有", "有权拒绝", "有权解除", "顺延", "延期",
    "每日", "按月", "按年", "千分之", "百分之", "万分之", "倍",
]

# 示范条款双版本标记
SIMPLE_MARKERS = ["简洁版", "简版", "📝"]
FULL_MARKERS = ["全面版", "全版", "📋"]


def _norm(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", "", str(text))


def _contains_any(text: str, phrases: list[str]) -> list[str]:
    hits = []
    for p in phrases:
        if p in text:
            hits.append(p)
    return hits


def _has_consequence(text: str) -> bool:
    return any(kw in text for kw in CONSEQUENCE_KEYWORDS)


def _has_numbered_clauses(text: str) -> bool:
    """检测是否含分款分项编号（1. 2. 或 （一）（二） 等）。"""
    patterns = [
        r"(?:^|\n)\s*\d+[\.、]",
        r"(?:^|\n)\s*[（(][一二三四五六七八九十]+[）)]",
    ]
    return any(re.search(p, text) for p in patterns)


def _has_placeholder(text: str) -> bool:
    return "___" in text or "＿＿＿" in text


def validate_clause(text: str, context: str, expect_full: bool = False) -> list[dict]:
    """校验单条示范条款，返回 violations 列表。"""
    violations = []
    norm = _norm(text)

    if not text or len(text.strip()) < 10:
        violations.append({
            "context": context,
            "type": "empty_or_too_short",
            "message": "示范条款为空或过短（<10 字符），不构成可独立使用的条款",
            "snippet": text[:80],
        })
        return violations

    # 1. 方向性禁用词（硬性失败）
    directional_hits = _contains_any(text, DIRECTIONAL_PHRASES)
    if directional_hits:
        violations.append({
            "context": context,
            "type": "directional_phrase",
            "message": f"示范条款含方向性/建议性措辞：{', '.join(directional_hits)}；这是审查意见，不是可直接落地的条款",
            "snippet": text[:120],
        })

    # 2. 弱化表述（警告级，简洁版中判失败）
    weak_hits = _contains_any(text, WEAK_PHRASES)
    if weak_hits and not expect_full:
        violations.append({
            "context": context,
            "type": "weak_phrase_in_simple",
            "message": f"简洁版含弱化/模糊表述：{', '.join(weak_hits)}，应给出量化或确定性表述",
            "snippet": text[:120],
        })

    # 3. 完整法律句式：含行为+后果
    if not _has_consequence(text):
        violations.append({
            "context": context,
            "type": "missing_consequence",
            "message": "示范条款未检测到违约责任/法律后果，可能只写了义务或方向",
            "snippet": text[:120],
        })

    # 4. 全面版必须分款分项
    if expect_full and not _has_numbered_clauses(text):
        violations.append({
            "context": context,
            "type": "full_clause_not_numbered",
            "message": "全面版示范条款未检测到分款分项编号（如 1. 2. 或 （一）（二）），不符合标准合同条款格式",
            "snippet": text[:120],
        })

    # 5. 变量占位符提示（非失败，仅提示）
    if not _has_placeholder(text):
        # 如果条款中完全没有 ___，检查是否含有具体数字/日期；有具体值则不需要占位符
        if re.search(r"\d+(?:\.\d+)?(?:%|元|万元|天|日|月|年)", text):
            pass  # 已量化，无需占位符
        else:
            violations.append({
                "context": context,
                "type": "missing_placeholder",
                "message": "示范条款未使用 ___ 占位符标注待填变量，用户复制后可能不知如何填充",
                "snippet": text[:120],
                "level": "warning",
            })

    return violations


def validate_issue(issue: dict, issue_id: str) -> list[dict]:
    """校验 ledger 中单个 issue 的两条示范条款。"""
    violations = []
    simple = issue.get("model_clause_simple", "") or ""
    full = issue.get("model_clause_full", "") or ""

    if not simple and not full:
        # 如果 issue 不需要示范条款，跳过
        return violations

    if not simple:
        violations.append({
            "context": f"ISSUE {issue_id}",
            "type": "missing_simple_clause",
            "message": "缺少简洁版示范条款",
        })
    else:
        violations.extend(validate_clause(simple, f"ISSUE {issue_id} · 简洁版示范条款", expect_full=False))

    if not full:
        violations.append({
            "context": f"ISSUE {issue_id}",
            "type": "missing_full_clause",
            "message": "缺少全面版示范条款",
        })
    else:
        violations.extend(validate_clause(full, f"ISSUE {issue_id} · 全面版示范条款", expect_full=True))

    return violations


def validate_ledger(ledger_path: str):
    ledger = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
    all_violations = []

    for issue in ledger.get("issues", []):
        all_violations.extend(validate_issue(issue, issue.get("id", "?")))

    for ns in ledger.get("new_sections_needed", []):
        # 缺失条款也要求输出完整双版本（如果 ledger 中保存了）
        all_violations.extend(validate_issue(ns, f"缺失条款 {ns.get('section', '?')}"))

    return all_violations


def validate_report_text(report_path: str):
    """从 markdown/文本报告中抽取示范条款块并校验。"""
    text = Path(report_path).read_text(encoding="utf-8")
    lines = text.splitlines()
    all_violations = []

    current_context = "报告"
    current_simple = None
    current_full = None

    def flush():
        nonlocal current_simple, current_full
        v = []
        if current_simple is not None:
            v.extend(validate_clause(current_simple["text"], current_simple["context"], expect_full=False))
        if current_full is not None:
            v.extend(validate_clause(current_full["text"], current_full["context"], expect_full=True))
        current_simple = None
        current_full = None
        return v

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # 识别上下文标题（如 🔴 高风险条款、📌 缺失条款）
        if re.match(r"^[🔴🟡🟢📌]|风险条款|缺失条款|示范条款", stripped):
            all_violations.extend(flush())
            current_context = stripped[:60]
            continue

        # 识别简洁版/全面版标记
        is_simple = any(m in stripped for m in SIMPLE_MARKERS)
        is_full = any(m in stripped for m in FULL_MARKERS)

        if is_simple or is_full:
            all_violations.extend(flush())
            # 收集后续行直到下一个标记或空行/新标题
            content_lines = []
            # 当前行去掉标记后的内容
            cleaned = re.sub(r"^[📝📋]|简洁版(?:示范条款)?[:：]?|全面版(?:示范条款)?[:：]?|简版[:：]?|全版[:：]?", "", stripped).strip()
            if cleaned:
                content_lines.append(cleaned)

            j = idx + 1
            while j < len(lines):
                next_line = lines[j]
                next_strip = next_line.strip()
                # 遇到下一个双版本标记、新风险标题、或连续空行结束
                if any(m in next_strip for m in SIMPLE_MARKERS + FULL_MARKERS) or re.match(r"^[🔴🟡🟢📌]|^═══|^---", next_strip):
                    break
                if next_strip == "":
                    # 允许段内空一行，但连续空行结束
                    if j + 1 < len(lines) and lines[j + 1].strip() == "":
                        break
                else:
                    content_lines.append(next_strip)
                j += 1

            clause_text = "\n".join(content_lines)
            if is_simple:
                current_simple = {"text": clause_text, "context": f"{current_context} · 简洁版"}
            else:
                current_full = {"text": clause_text, "context": f"{current_context} · 全面版"}

    all_violations.extend(flush())
    return all_violations


def validate_single(text: str):
    return validate_clause(text, "单行校验", expect_full=False)


def main():
    parser = argparse.ArgumentParser(description="合同智囊示范条款自动校验")
    parser.add_argument("--ledger", help="ledger JSON 文件路径")
    parser.add_argument("--report-text", help="报告文本/markdown 路径")
    parser.add_argument("--single", help="单条示范条款文本")
    parser.add_argument("--out", help="校验结果 JSON 输出路径（可选）")
    parser.add_argument("--strict", action="store_true", help="严格模式：warning 也视为失败")
    args = parser.parse_args()

    if not any([args.ledger, args.report_text, args.single]):
        parser.print_help()
        sys.exit(2)

    if args.ledger:
        violations = validate_ledger(args.ledger)
    elif args.report_text:
        violations = validate_report_text(args.report_text)
    else:
        violations = validate_single(args.single)

    # warning 级默认不阻断；strict 模式下全部视为失败
    failures = [v for v in violations if args.strict or v.get("level") != "warning"]

    result = {
        "valid": len(failures) == 0,
        "total_violations": len(violations),
        "blocking_violations": len(failures),
        "violations": violations,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if failures:
        print(f"\n[validate_model_clauses] ❌ 发现 {len(failures)} 项不合格的示范条款，请在修复后重新校验。", file=sys.stderr)
        sys.exit(1)

    print("\n[validate_model_clauses] ✅ 全部示范条款通过校验。")
    sys.exit(0)


if __name__ == "__main__":
    main()
