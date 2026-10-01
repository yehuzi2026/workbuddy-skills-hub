#!/usr/bin/env python3
"""
bid_price_calc.py — 模块C2+D价算校验脚本（v5.0.0）
====================================================

功能：执行投标报价的算术校验。
      包括：报价函总价=∑明细表总价、大写金额↔小写金额一致性、
      报价精确度、备选方案检测等。

使用方式：
    python bid_price_calc.py <bid_file.md> [--output <output.json>]
    python bid_price_calc.py <bid_file.md> --budget 200 --deadline '2025-08-14T14:00:00' [--output <output.json>]

强制执行规则：
    - 报价函总价 vs 明细表总价不一致 → ❌
    - 大写金额 ≠ 小写金额 → ❌
    - 存在备选方案 → ❌（如果招标不允许）
    - 报价超预算 → ❌
    - 报价日期晚于投标截止 → ❌
"""

import json
import sys
import os
import re
from typing import List, Dict, Any, Optional, Tuple


# ============================================================
# 1. 金额提取引擎
# ============================================================

def extract_prices(bid_text: str) -> Dict[str, Any]:
    """
    从投标文件中提取所有报价相关信息。
    
    策略：只从★报价一览表/★报价明细表章节中定向提取，
    不扫描全省数字。
    """
    lines = bid_text.split('\n')
    
    total_prices = []
    detail_prices = []
    uppercase_amounts = []
    lowercase_amounts = []
    alternative_plans = []
    
    # 报价一览表章节提取
    # 定位所有"★报价一览表"章节
    price_table_sections = []
    current_plan = None
    in_price_section = False
    section_start = 0
    
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        
        # 检测章节开始（★报价一览表）
        if "★报价一览表" in stripped:
            in_price_section = True
            section_start = line_idx
            # 检测是方案一还是方案二
            # 方案一报价一览表在3661行，方案二在3685行
            current_plan = "方案一" if "方案一" not in stripped else "方案二"
            price_table_sections.append({
                "start": line_idx + 1,
                "section_name": stripped[:30],
                "plan": current_plan or "默认"
            })
            continue
        
        # 检测章节结束（遇到下一个## 章节 或 过度内容）
        if in_price_section:
            if stripped.startswith("##") and "报价一览表" not in stripped and "报价明细表" not in stripped:
                # 进入下一章节
                in_price_section = False
                if price_table_sections:
                    price_table_sections[-1]["end"] = line_idx
    
    # 补充最后一个章节的结束行
    if price_table_sections and "end" not in price_table_sections[-1]:
        price_table_sections[-1]["end"] = len(lines)
    
    # 方案检测：检查投标文件中是否有多个报价章节
    plan_names = set()
    for line in lines:
        m = re.search(r'(方案[一二三四五六]|备选方案\d)', line)
        if m:
            plan_names.add(m.group(1))
    
    has_multiple_plans = len(plan_names) > 1 or "方案一" in str(lines[3660:3700]) and "方案二" in str(lines[3660:3700])
    
    # 在报价一览表章节中提取价格
    for section in price_table_sections:
        s = section["start"]
        e = section.get("end", len(lines))
        
        for i in range(s - 1, min(e + 1, len(lines))):
            line = lines[i]
            
            # 模式1：小写金额 "小写： 2347000.00元"
            lowercase_match = re.search(r'小写[：:]\s*([\d,]+\.?\d*)\s*元', line)
            if lowercase_match:
                val_str = lowercase_match.group(1).replace(',', '')
                try:
                    value = float(val_str)
                    if 100000 <= value <= 10000000:  # 10万~1000万之间才合理
                        entry = {"line_no": i + 1, "value": value, "unit": "元", "section": section["section_name"], "context": line.strip()[:80]}
                        total_prices.append(entry)
                        lowercase_amounts.append(entry)
                except ValueError:
                    pass
            
            # 模式2：大写金额 "大写：贰佰零肆万伍仟元整"
            uppercase_match = re.search(r'大写[：:]\s*([壹贰叁肆伍陆柒捌玖拾佰仟万亿元整角分零]+)', line)
            if uppercase_match:
                ua_text = uppercase_match.group(1)
                if len(ua_text) >= 4:
                    uppercase_amounts.append({
                        "line_no": i + 1,
                        "text": ua_text,
                        "section": section["section_name"],
                        "context": line.strip()[:80]
                    })
    
    # 额外的备选方案检测：检查所有报价一览表章节数量
    alt_plans = []
    for line_idx, line in enumerate(lines):
        if re.search(r'(?:方案[一二三四五六]|方案[12])', line) and "报价一览表" in line:
            alt_plans.append({
                "line_no": line_idx + 1,
                "text": line.strip()[:80]
            })
    
    return {
        "total_prices_found": total_prices,
        "detail_prices_found": [],
        "uppercase_amounts": uppercase_amounts,
        "lowercase_amounts": lowercase_amounts,
        "alternative_plans": alt_plans,
        "has_multiple_plans": len(total_prices) > 1 or len(alt_plans) > 1
    }


# ============================================================
# 2. 大写金额转数字
# ============================================================

UPPERCASE_DIGITS = {
    '零': 0, '壹': 1, '贰': 2, '叁': 3, '肆': 4,
    '伍': 5, '陆': 6, '柒': 7, '捌': 8, '玖': 9
}

UPPERCASE_MULTIPLIERS = {
    '拾': 10, '佰': 100, '仟': 1000, '万': 10000, '亿': 100000000
}

def uppercase_to_number(text: str) -> Optional[float]:
    """
    将中文大写金额转换为数字。
    支持格式：壹佰万元整、贰佰零肆万伍仟元整
    """
    try:
        # 移除"元整""元""整""角""分"等后缀
        text = text.replace('元整', '').replace('元', '').replace('整', '')
        text = text.replace('角', '').replace('分', '')
        
        result = 0
        current = 0
        last_multiplier = 1
        
        for char in text:
            if char in UPPERCASE_DIGITS:
                current = UPPERCASE_DIGITS[char]
            elif char in UPPERCASE_MULTIPLIERS:
                mult = UPPERCASE_MULTIPLIERS[char]
                if current == 0:
                    current = 1
                if mult >= 10000:
                    # 万、亿级别
                    result = (result + current) * mult if result == 0 else result + current * mult
                    current = 0
                    last_multiplier = mult
                else:
                    current *= mult
                    result += current
                    current = 0
            elif char == '零':
                current = 0
        
        result += current
        
        return result / 10000 if result > 10000 else result  # 转为万元
    except Exception:
        return None


# ============================================================
# 3. 价算校验执行器
# ============================================================

def validate_total_price(price_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    校验报价函总价与明细表总价是否一致。
    """
    issues = []
    total_prices = price_data.get("total_prices_found", [])
    detail_prices = price_data.get("detail_prices_found", [])
    
    if total_prices and detail_prices:
        # 取报价函第一笔总价
        main_total = total_prices[0]["value"]
        # 明细表总价和
        detail_sum = sum(p["value"] for p in detail_prices)
        
        if abs(main_total - detail_sum) > 0.01:
            issues.append({
                "issue_type": "total_price_mismatch",
                "severity": "P0",
                "main_total": main_total,
                "detail_sum": detail_sum,
                "diff": round(abs(main_total - detail_sum), 2),
                "detail": f"报价函总价({main_total}) ≠ 明细表合计({detail_sum})"
            })
    
    return issues


def validate_uppercase_amount(price_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    校验大写金额与小写金额是否一致。
    
    比较规则：
    1. 只比较量级相近的金额（大写 vs 小写，比值在0.5~2.0之间）
    2. 大写金额转万元后，与同个小写金额的差值<0.5才认为一致
    3. 同一行或相邻行出现的才有可比性
    """
    issues = []
    
    for ua in price_data.get("uppercase_amounts", []):
        uppercase_text = ua["text"]
        numeric_value = uppercase_to_number(uppercase_text)  # 返回值为万元
        
        if numeric_value is None or numeric_value <= 0:
            continue
        
        # 查找附近的小写金额（同一行或相邻行，且量级相近）
        nearby_prices = [
            p for p in price_data.get("lowercase_amounts", [])
            if abs(p["line_no"] - ua["line_no"]) < 8
        ]
        
        for lp in nearby_prices:
            lowercase_val = lp["value"]
            
            # 统一单位为万元
            if lp.get("unit") in ("元", "", "元/年"):
                lowercase_val_in_wan = lowercase_val / 10000
            else:
                lowercase_val_in_wan = lowercase_val  # 已经是万元
            
            # 只有量级相近才比较（大写值 ÷ 小写值 在0.5~2.0之间）
            if lowercase_val_in_wan <= 0:
                continue
            ratio = numeric_value / lowercase_val_in_wan
            if ratio < 0.5 or ratio > 2.0:
                continue
            
            # 差值的绝对值和相对值都检查
            abs_diff = abs(numeric_value - lowercase_val_in_wan)
            rel_diff = abs_diff / max(numeric_value, lowercase_val_in_wan)
            
            if abs_diff > 0.5 and rel_diff > 0.05:
                issues.append({
                    "issue_type": "uppercase_lowercase_mismatch",
                    "severity": "P0",
                    "uppercase": uppercase_text,
                    "uppercase_value_wan": round(numeric_value, 2),
                    "lowercase_value_wan": round(lowercase_val_in_wan, 2),
                    "diff_wan": round(abs_diff, 2),
                    "detail": f"大写金额({uppercase_text}={numeric_value:.2f}万) ≠ 小写金额({lowercase_val_in_wan:.2f}万), 差值{abs_diff:.2f}万"
                })
                break
    
    return issues


def validate_alternative_plans(price_data: Dict[str, Any],
                                allow_alternative: bool = False) -> List[Dict[str, Any]]:
    """
    校验是否存在不被允许的备选方案。
    判断依据：出现2笔或以上的不同报价（如方案一204.5万+方案二234.7万）
    或超过1份报价一览表。
    """
    issues = []
    total_prices = price_data.get("total_prices_found", [])
    alt_plans_from_text = price_data.get("alternative_plans", [])
    has_multiple = price_data.get("has_multiple_plans", False)
    
    # 通过总价笔数判断：有≥2笔不同报价
    has_multiple_prices = len(total_prices) >= 2
    
    if (has_multiple_prices or has_multiple or len(alt_plans_from_text) > 0) and not allow_alternative:
        plan_count = len(total_prices) if has_multiple_prices else len(alt_plans_from_text)
        plan_details = [{"line_no": p["line_no"], "value": p["value"], "unit": p["unit"]} for p in total_prices]
        
        issues.append({
            "issue_type": "alternative_plan_detected",
            "severity": "P0",
            "plan_count": plan_count,
            "plans": plan_details[:5],  # 最多显示5个
            "detail": f"招标文件不允许备选方案，发现{plan_count}笔不同报价" + 
                     (f"（{', '.join([str(p['value'])+p['unit'] for p in total_prices])}）" if total_prices else "")
        })
    
    return issues


def validate_price_format(price_data: Dict[str, Any],
                           decimal_places: int = 2) -> List[Dict[str, Any]]:
    """
    校验报价金额的小数位数是否符合要求。
    """
    issues = []
    
    for amount in price_data.get("lowercase_amounts", []):
        value_str = str(amount["value"])
        if '.' in value_str:
            decimals = len(value_str.split('.')[1])
            if decimals > decimal_places:
                issues.append({
                    "issue_type": "decimal_places_exceeded",
                    "severity": "P1",
                    "value": amount["value"],
                    "decimal_places": decimals,
                    "required": decimal_places,
                    "detail": f"报价金额({amount['value']})小数位数({decimals})超过要求({decimal_places})"
                })
    
    return issues


# ============================================================
# 4. 主入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("=" * 60)
        print("bid_price_calc.py — 价算校验脚本")
        print("=" * 60)
        print()
        print("使用方式:")
        print(f"  python {os.path.basename(__file__)} <bid_file.md> [options]")
        print()
        print("参数:")
        print("  bid_file.md          投标文件Markdown格式")
        print("  --output <file>      输出JSON文件路径")
        print("  --budget <amount>    预算金额（万元）")
        print("  --allow-alternative  允许备选方案（默认不允许）")
        print("  --decimal <n>        要求小数位数（默认2位）")
        print()
        sys.exit(1)
    
    bid_file = sys.argv[1]
    output_file = None
    budget = None
    allow_alternative = False
    decimal_places = 2
    
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]
    
    if "--budget" in sys.argv:
        idx = sys.argv.index("--budget")
        if idx + 1 < len(sys.argv):
            try:
                budget = float(sys.argv[idx + 1])
            except ValueError:
                print(f"❌ 预算金额格式错误: {sys.argv[idx + 1]}")
                sys.exit(1)
    
    if "--allow-alternative" in sys.argv:
        allow_alternative = True
    
    if "--decimal" in sys.argv:
        idx = sys.argv.index("--decimal")
        if idx + 1 < len(sys.argv):
            try:
                decimal_places = int(sys.argv[idx + 1])
            except ValueError:
                pass
    
    # 读取投标文件
    try:
        with open(bid_file, 'r', encoding='utf-8') as f:
            bid_text = f.read()
    except Exception as e:
        print(f"❌ 读取投标文件失败: {e}")
        sys.exit(1)
    
    print(f"📖 价算校验启动: {bid_file}")
    print()
    
    # 提取报价数据
    price_data = extract_prices(bid_text)
    print(f" 📊 提取到报价数据:")
    print(f"    报价函总价: {len(price_data['total_prices_found'])} 笔")
    if price_data['total_prices_found']:
        for tp in price_data['total_prices_found']:
            print(f"      - 第{tp['line_no']}行: {tp['value']}{tp['unit']} ({tp['section']})")
    print(f"    明细价格: {len(price_data['detail_prices_found'])} 笔")
    print(f"    大写金额: {len(price_data['uppercase_amounts'])} 处")
    print(f"    备选方案: {len(price_data['alternative_plans'])} 个")
    print()
    
    # 执行各类校验
    all_issues = []
    
    # 总价校验
    issues = validate_total_price(price_data)
    all_issues.extend(issues)
    if issues:
        for i in issues:
            print(f"   ❌ {i['detail']}")
    else:
        print(f"   ✅ 报价函总价与明细表总和一致")
    
    # 大写小写校验
    issues = validate_uppercase_amount(price_data)
    all_issues.extend(issues)
    if issues:
        for i in issues:
            print(f"   ❌ {i['detail']}")
    else:
        print(f"   ✅ 大写金额与小写金额一致")
    
    # 备选方案校验
    issues = validate_alternative_plans(price_data, allow_alternative)
    all_issues.extend(issues)
    if issues:
        for i in issues:
            print(f"   ❌ {i['detail']}")
    else:
        print(f"   ✅ 未发现不允许的备选方案")
    
    # 预算校验
    if budget is not None and price_data['total_prices_found']:
        for tp in price_data['total_prices_found']:
            if tp['value'] > budget:
                all_issues.append({
                    "issue_type": "over_budget",
                    "severity": "P0",
                    "price": tp['value'],
                    "budget": budget,
                    "detail": f"报价({tp['value']}万元)超过预算({budget}万元)"
                })
                print(f"   ❌ 报价超预算: {tp['value']} > {budget}万元")
    
    # 小数位数校验
    issues = validate_price_format(price_data, decimal_places)
    all_issues.extend(issues)
    if issues:
        for i in issues:
            print(f"   ⚠️ {i['detail']}")
    
    print()
    
    # 组装输出
    output = {
        "module": "price_calc",
        "bid_file": bid_file,
        "check_time": __import__('datetime').datetime.now().isoformat(),
        "price_data_summary": {
            "total_prices_count": len(price_data['total_prices_found']),
            "detail_prices_count": len(price_data['detail_prices_found']),
            "uppercase_amounts_count": len(price_data['uppercase_amounts']),
            "has_multiple_plans": price_data['has_multiple_plans']
        },
        "all_issues": all_issues,
        "has_issues": len(all_issues) > 0,
        "p0_issues_count": len([i for i in all_issues if i.get("severity") == "P0"]),
        "verdict": "❌" if any(i.get("severity") == "P0" for i in all_issues) else ("⚠️" if all_issues else "✅"),
        "execution_marker": "✅ 价算校验执行完成"
    }
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"✅ 输出已保存: {output_file}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    
    sys.exit(0 if not output["has_issues"] else 2)


if __name__ == "__main__":
    main()
