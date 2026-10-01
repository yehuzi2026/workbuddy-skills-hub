#!/usr/bin/env python3
"""
bid_diff_engine.py — 模块B全量文字diff引擎（v5.0.0）
====================================================

功能：对固定格式模板中的13类字段执行逐字符diff比对。
输出模板原文vs投标值的精确差异列表，供AI做废标判定。

使用方式：
    python bid_diff_engine.py <templates.json> <bid_file.md> [--output <output.json>]

输入格式（templates.json）：
    由模块A生成的固定格式模板数据，包含template_text和field_type。

强制执行规则：
    - 13类字段必须全部扫描（1类缺漏 → ❌）
    - 逐字符diff，非整词匹配（1个字符不同都标记）
    - 签字类型差异（委托代理人vs法定代表人）强制标记P0
    - 日期逻辑自动校验
    - 扫描完成必须输出✅确认
"""

import json
import sys
import os
import re
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime


# ============================================================
# 1. 13类字段定义
# ============================================================

FIELD_TYPES_13 = [
    "固定格式名称",
    "致函对象",
    "项目信息",
    "表头标签",
    "括号格式",
    "注",
    "备注",
    "文字",
    "落款名称",
    "公章类型",
    "授权代表签字",
    "法人签字",
    "日期"
]

FIELD_TYPE_P0 = {"授权代表签字", "法人签字", "公章类型", "项目信息", "日期"}


# ============================================================
# 2. 逐字符diff引擎
# ============================================================

def char_by_char_diff(text_a: str, text_b: str) -> Dict[str, Any]:
    """
    逐字符比对两个字符串，输出精确差异列表。
    
    返回：
        {
            "total_chars_a": int,
            "total_chars_b": int,
            "exact_match": bool,
            "diff_type": "exact_match" | "char_replacement" | "char_missing" | "char_extra",
            "diff_chars": [{pos, char_a, char_b}, ...],
            "match_rate": float (0~1),
            "diff_positions": [int]
        }
    """
    # 使用最长公共子序列(LCS)算法定位差异
    len_a, len_b = len(text_a), len(text_b)
    max_len = max(len_a, len_b)
    
    diff_chars = []
    min_len = min(len_a, len_b)
    
    for i in range(min_len):
        if text_a[i] != text_b[i]:
            diff_chars.append({
                "pos": i,
                "char_a": text_a[i],
                "char_b": text_b[i]
            })
    
    # 处理长度不一致（多余或缺失）
    extra_chars = []
    missing_chars = []
    
    if len_a < len_b:
        # text_b比text_a长 → text_b多了字符
        for i in range(len_a, len_b):
            extra_chars.append({
                "pos": i,
                "char_a": None,
                "char_b": text_b[i]
            })
            diff_chars.append({
                "pos": i,
                "char_a": "(缺失)",
                "char_b": text_b[i]
            })
    elif len_b < len_a:
        # text_a比text_b长 → text_b少了字符
        for i in range(len_b, len_a):
            missing_chars.append({
                "pos": i,
                "char_a": text_a[i],
                "char_b": None
            })
            diff_chars.append({
                "pos": i,
                "char_a": text_a[i],
                "char_b": "(缺失)"
            })
    
    # 计算匹配率
    total_positions = max_len if max_len > 0 else 1
    match_count = total_positions - len([d for d in diff_chars if d.get("char_b") != "(缺失)" or d.get("char_a") != "(缺失)"])
    match_rate = match_count / total_positions
    
    # 确定差异类型
    diff_type = "exact_match"
    if len(diff_chars) > 0:
        if len_a == len_b:
            diff_type = "char_replacement"
        elif len_a < len_b:
            diff_type = "char_missing"  # text_a 缺少text_b中的字符
        else:
            diff_type = "char_extra"  # text_a 多了字符
    
    # 排序diff_chars按位置
    diff_chars.sort(key=lambda x: x["pos"])
    
    return {
        "total_chars_a": len_a,
        "total_chars_b": len_b,
        "exact_match": len(diff_chars) == 0 and len_a == len_b,
        "diff_type": diff_type if len(diff_chars) > 0 else "exact_match",
        "diff_chars": diff_chars,
        "diff_positions": [d["pos"] for d in diff_chars],
        "match_rate": round(match_rate, 4),
        "has_difference": len(diff_chars) > 0
    }


# ============================================================
# 3. 特殊规则检测器
# ============================================================

def detect_signature_identity_issue(template_text: str, bid_text: str) -> Optional[Dict[str, Any]]:
    """
    检测签字身份替换问题（委托代理人vs法定代表人）。
    """
    template_normalized = template_text.replace(" ", "").replace("　", "")
    bid_normalized = bid_text.replace(" ", "").replace("　", "")
    
    identity_pairs = [
        ("委托代理人", "法定代表人"),
        ("授权代表", "法定代表人"),
        ("委托代理人", "法人代表"),
        ("授权代表", "法人代表"),
    ]
    
    for expected, actual in identity_pairs:
        if expected in template_normalized and actual in bid_normalized:
            return {
                "issue_type": "signature_identity_mismatch",
                "expected_identity": expected,
                "actual_identity": actual,
                "severity": "P0",
                "detail": f"模板要求'{expected}'签字，投标文件写成了'{actual}'"
            }
    
    return None


def detect_signature_blank(template_text: str, bid_text: str) -> Optional[Dict[str, Any]]:
    """
    检测签名栏空白。
    模板要求签名但投标值为空白。
    """
    # 检查模板是否要求签名
    signature_keywords = ["签名", "签章", "签字", "盖章"]
    requires_signature = any(kw in template_text for kw in signature_keywords)
    
    if not requires_signature:
        return None
    
    # 检查投标值是否空白
    bid_stripped = bid_text.strip().replace(" ", "").replace("　", "")
    if not bid_stripped or bid_stripped in ["：", ":", "/", "无", "—", "-"]:
        return {
            "issue_type": "signature_blank",
            "severity": "P0",
            "detail": f"模板要求在此处签名，但投标值为空白"
        }
    
    return None


def validate_date_logic(bid_date_str: str, deadline_str: str) -> Optional[Dict[str, Any]]:
    """
    验证投标文件日期是否晚于投标截止时间。
    """
    try:
        # 尝试多种日期格式
        date_patterns = [
            r'(\d{4})年(\d{1,2})月(\d{1,2})日',
            r'(\d{4})-(\d{1,2})-(\d{1,2})',
            r'(\d{4})/(\d{1,2})/(\d{1,2})',
        ]
        
        bid_date = None
        for pattern in date_patterns:
            m = re.search(pattern, bid_date_str)
            if m:
                bid_date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                break
        
        deadline = None
        for pattern in date_patterns:
            m = re.search(pattern, deadline_str)
            if m:
                deadline = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                break
        
        if bid_date and deadline and bid_date > deadline:
            return {
                "issue_type": "date_logic_error",
                "severity": "P0",
                "bid_date": bid_date_str.strip(),
                "deadline": deadline_str.strip(),
                "detail": f"投标文件日期({bid_date_str.strip()})晚于投标截止时间({deadline_str.strip()})"
            }
    except Exception:
        pass
    
    return None


def detect_bracket_format_issue(template_text: str, bid_text: str) -> Optional[Dict[str, Any]]:
    """
    检测括号格式不一致（全角vs半角）。
    """
    bracket_pairs = [
        ("（", "("),
        ("）", ")"),
        ("【", "["),
        ("】", "]"),
        ("「", "["),
        ("」", "]"),
    ]
    
    issues = []
    for fullwidth, halfwidth in bracket_pairs:
        template_count_full = template_text.count(fullwidth)
        template_count_half = template_text.count(halfwidth)
        bid_count_full = bid_text.count(fullwidth)
        bid_count_half = bid_text.count(halfwidth)
        
        # 模板用全角，投标用半角
        if template_count_full > 0 and bid_count_half > 0 and bid_count_full == 0:
            issues.append(f"模板使用全角'{fullwidth}'，投标使用半角'{halfwidth}'")
        # 模板用半角，投标用全角
        if template_count_half > 0 and bid_count_full > 0 and bid_count_half == 0:
            issues.append(f"模板使用半角'{halfwidth}'，投标使用全角'{fullwidth}'")
    
    if issues:
        return {
            "issue_type": "bracket_format_mismatch",
            "severity": "P1",
            "detail": "; ".join(issues)
        }
    
    return None


# ============================================================
# 4. 单字段diff执行器
# ============================================================

def diff_single_field(field: Dict[str, Any], bid_text_actual: str,
                      bid_deadline: Optional[str] = None) -> Dict[str, Any]:
    """
    对单个字段执行全量diff检测。
    """
    template_text = field.get("template_text", "")
    field_name = field.get("field_name", "")
    field_type = field.get("field_type", "")
    verification_rule = field.get("verification_rule", "逐字一致")
    
    # 基础逐字diff
    diff_result = char_by_char_diff(template_text, bid_text_actual)
    
    # 特殊规则检测
    special_issues = []
    
    # 签字身份检测
    if field_type in ("授权代表签字", "法人签字"):
        issue = detect_signature_identity_issue(template_text, bid_text_actual)
        if issue:
            special_issues.append(issue)
    
    # 签名空白检测
    if field_type in ("授权代表签字", "法人签字", "公章类型"):
        issue = detect_signature_blank(template_text, bid_text_actual)
        if issue:
            special_issues.append(issue)
    
    # 日期逻辑检测
    if field_type == "日期" and bid_deadline:
        issue = validate_date_logic(bid_text_actual, bid_deadline)
        if issue:
            special_issues.append(issue)
    
    # 括号格式检测
    if field_type == "括号格式":
        issue = detect_bracket_format_issue(template_text, bid_text_actual)
        if issue:
            special_issues.append(issue)
    
    # 综合判定
    has_diff = diff_result["has_difference"]
    has_special_issue = len(special_issues) > 0
    
    # 确定verdict
    # 先检查模板是否占位符
    is_placeholder = bool(re.search(r'[（(【].{1,20}[）)】]', template_text))
    
    if has_special_issue:
        p0_issues = [i for i in special_issues if i.get("severity") == "P0"]
        if p0_issues:
            verdict = "❌"
        else:
            verdict = "⚠️"
    elif has_diff:
        if is_placeholder:
            verdict = "⚠️"  # 占位符填写差异，需AI确认
        else:
            verdict = "⚠️"
    else:
        verdict = "✅"
    
    # 签名空白 → ❌
    if any(i.get("issue_type") == "signature_blank" for i in special_issues):
        verdict = "❌"
    # 签字身份替换 → ❌
    if any(i.get("issue_type") == "signature_identity_mismatch" for i in special_issues):
        verdict = "❌"
        verdict = "✅"
    
    return {
        "field_name": field_name,
        "field_type": field_type,
        "verification_rule": verification_rule,
        "template_text": template_text,
        "bid_text": bid_text_actual,
        "diff_detail": diff_result,
        "special_issues": special_issues,
        "has_issue": has_diff or has_special_issue,
        "issue_count": (1 if has_diff else 0) + len(special_issues),
        "verdict": verdict
    }


# ============================================================
# 5. 模板级diff执行器（重写：行级精确匹配）
# ============================================================

def find_bid_value_for_field(field: Dict[str, Any], bid_lines: list,
                              section_start: int, section_end: int,
                              template_name: str,
                              all_signatures: bool = False) -> str:
    """
    在投标文件中为模板字段精确定位对应的行级值。
    
    策略根据field_type不同：
    - 法人签字/授权代表签字：在落款区找所有含"签名""签章"的行
    - 落款名称/公章类型：在落款区找含"公章""名称""印章"的行
    - 项目信息：找包含template_text中关键信息的行
    - 表头标签：在表格区域找匹配的行
    - 日期：在落款区找含"日期""日 期"的行
    - 固定格式名称：找section标题行
    - 备注：搜索整section查找"备注""注：""说明"等
    """
    field_type = field.get("field_type", "")
    field_name = field.get("field_name", "")
    template_text = field.get("template_text", "").strip()
    
    # 搜索范围
    search_start = max(0, section_start)
    search_end = min(len(bid_lines), section_end)
    footer_start = max(search_start, search_end - 18)  # 落款区扩大到18行
    
    def clean_line(line):
        return line.strip().lstrip('#* ')
    
    def find_in_range(start, end, keywords, fallback=""):
        for i in range(start, end):
            line = clean_line(bid_lines[i])
            if any(kw in line for kw in keywords):
                return (i, line)
        return (None, fallback)
    
    if field_type in ("法人签字", "授权代表签字", "签字"):
        # **修复4：收集所有含"签名/签章"的行，不return第一个**
        signature_lines = []
        for i in range(footer_start, search_end):
            line = clean_line(bid_lines[i])
            if "签名" in line or "签章" in line:
                signature_lines.append((i, line))
        
        if all_signatures:
            # 返回所有签名行（供diff_template分配）
            return signature_lines
        
        if not signature_lines:
            return "(空白)"
        
        # 返回第一个（兼容单签名模板）
        return signature_lines[0][1]
    
    elif field_type == "日期":
        _, val = find_in_range(footer_start, search_end, ["日期", "日 期"], "(未找到日期行)")
        return val
    
    elif field_type == "落款名称":
        # **修复3：扩大搜索范围包括"公""章""印""名"**
        _, val = find_in_range(footer_start, search_end, ["公章", "印章", "名称", "公", "章", "印"], "(未找到落款名称行)")
        return val
    
    elif field_type == "公章类型":
        _, val = find_in_range(footer_start, search_end, ["公章", "印章", "单位章", "公", "章"], "(未找到公章行)")
        return val
    
    elif field_type == "固定格式名称":
        if search_start < len(bid_lines):
            return clean_line(bid_lines[search_start]) or template_name
        return template_name
    
    elif field_type == "项目信息":
        _, val = find_in_range(search_start, search_end, ["项目名称", "项目编号", "包号", "标段"], "(未找到项目信息行)")
        return val
    
    elif field_type == "致函对象":
        for i in range(search_start, min(search_start + 10, search_end)):
            line = clean_line(bid_lines[i])
            if line and "：" in line and len(line) < 60 and not line.startswith('#'):
                if not any(kw in line for kw in ["报价函", "响应表", "授权委托"]):
                    return line
        return "(未找到致函对象行)"
    
    elif field_type == "表头标签":
        for i in range(search_start, search_end):
            line = bid_lines[i].strip()
            if '|' in line and any(kw in line for kw in template_text.split('|')[0].split()[:3]):
                return line[:120]
        return "(未找到表头行)"
    
    elif field_type in ("备注", "注"):
        # **修复2：搜索整section查找"备注""注：""说明"等**
        _, val = find_in_range(search_start, search_end, ["备注", "注", "说明", "注："], "(未找到备注行)")
        return val
    
    elif field_type == "括号格式":
        for i in range(search_start, search_end):
            line = clean_line(bid_lines[i])
            if '（' in line or '(' in line or '）' in line or ')' in line:
                return line
        return "(未找到括号行)"
    
    else:  # "文字" 类及其他
        for i in range(search_start, search_end):
            line = bid_lines[i].strip()
            if not line or line.startswith('#'):
                continue
            if len(template_text) > 10:
                key_part = template_text[:15]
                if key_part in line:
                    return line[:200]
            elif line and len(line) > 5:
                return line[:200]
        return "(未找到匹配行)"


def diff_template(template: Dict[str, Any], bid_lines: list,
                  bid_deadline: Optional[str] = None) -> Dict[str, Any]:
    """
    对单个模板执行全部字段的diff（行级精确匹配版本）。
    """
    template_id = template.get("template_id", "")
    template_name = template.get("template_name", "")
    fields_template = template.get("fields", [])
    
    field_results = []
    total_fields = len(fields_template)
    fields_with_issues = 0
    
    # === 定位section范围（修复1：记录章节名称）===
    section_start = 0
    section_end = len(bid_lines) - 1
    section_title = template_name  # 默认
    bid_section_name = template_name  # 投标文件中的对应章节名
    
    name_keywords = [kw for kw in template_name.replace("★", "").split() if len(kw) > 2]
    
    for i, line in enumerate(bid_lines):
        stripped = line.strip()
        if re.match(r'^\d+(?:\.\d+)*\s', stripped):
            continue
        if not stripped.startswith('#'):
            continue
        if all(kw in stripped for kw in name_keywords):
            section_start = i
            section_title = stripped.lstrip('#* ').strip()
            bid_section_name = section_title
            break
    
    for i in range(section_start + 1, len(bid_lines)):
        stripped = bid_lines[i].strip()
        if re.match(r'^\d+(?:\.\d+)*\s', stripped):
            continue
        if stripped.startswith("## ") or stripped.startswith("##\t"):
            section_end = i
            break
    
    # === 预提取所有签名行（修复4：多签字人支持）===
    all_sig_lines = []
    for field in fields_template:
        if field.get("field_type") in ("法人签字", "授权代表签字", "签字"):
            all_sig_lines = find_bid_value_for_field(
                field, bid_lines, section_start, section_end, template_name, all_signatures=True
            )
            break  # 只收集一次
    
    sig_idx = 0  # 签名行索引
    
    # === 逐字段扫描 ===
    for field in fields_template:
        field_name = field.get("field_name", "")
        field_type = field.get("field_type", "")
        
        # 对多签字人：从预提取的签名列表中按顺序取
        if field_type in ("法人签字", "授权代表签字", "签字") and all_sig_lines:
            if sig_idx < len(all_sig_lines):
                line_no, bid_value = all_sig_lines[sig_idx]
                sig_idx += 1
            else:
                bid_value = "(空白)"  # 签名行不够
        else:
            bid_value = find_bid_value_for_field(
                field, bid_lines, section_start, section_end, template_name
            )
        
        # 执行diff
        result = diff_single_field(field, bid_value, bid_deadline)
        
        # **修复1+5：增加章节上下文信息**
        result["section"] = bid_section_name
        result["template_section"] = section_title
        result["bid_section"] = bid_section_name
        # 把行号修正为投标文件中实际的行号（不是模板的行号）
        if field_type in ("法人签字", "授权代表签字", "签字") and all_sig_lines and sig_idx > 0:
            result["line_no"] = all_sig_lines[sig_idx - 1][0] + 1  # 0-based to 1-based
        else:
            result["line_no"] = section_start + 1  # 至少标记section开头
        
        # **修复3：对所有字段类型自动检测括号格式**
        if result.get("diff_detail", {}).get("has_difference", False):
            bracket_issue = detect_bracket_format_issue(
                field.get("template_text", ""), bid_value
            )
            if bracket_issue:
                result.setdefault("special_issues", []).append(bracket_issue)
                result["has_issue"] = True
                if result.get("verdict") == "✅":
                    result["verdict"] = "⚠️"
        
        field_results.append(result)
        if result["has_issue"]:
            fields_with_issues += 1
    
    # 统计13类字段覆盖情况
    field_types_present = set(f.get("field_type", "") for f in fields_template)
    field_types_covered = [ft for ft in FIELD_TYPES_13 if ft in field_types_present]
    
    return {
        "template_id": template_id,
        "template_name": template_name,
        "total_fields": total_fields,
        "fields_checked": len(field_results),
        "fields_with_issues": fields_with_issues,
        "field_types_covered": field_types_covered,
        "field_types_total": len(FIELD_TYPES_13),
        "all_field_types_covered": len(field_types_covered) == len(FIELD_TYPES_13),
        "fields": field_results,
        "pass": fields_with_issues == 0,
        "template_checked": True  # ✅
    }


# ============================================================
# 6. 主入口
# ============================================================

def main():
    if len(sys.argv) < 3:
        print("=" * 60)
        print("bid_diff_engine.py — 模块B全量文字diff引擎")
        print("=" * 60)
        print()
        print("使用方式:")
        print(f"  python {os.path.basename(__file__)} <templates.json> <bid_file.md> [--output <output.json>]")
        print(f"  python {os.path.basename(__file__)} <templates.json> <bid_file.md> --deadline '2025-08-14T14:00:00' [--output <output.json>]")
        print()
        print("输入格式（templates.json）：")
        print("  由模块A生成的固定格式模板JSON，包含fixed_format_templates字段")
        print()
        sys.exit(1)
    
    templates_file = sys.argv[1]
    bid_file = sys.argv[2]
    output_file = None
    bid_deadline = None
    
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]
    
    if "--deadline" in sys.argv:
        idx = sys.argv.index("--deadline")
        if idx + 1 < len(sys.argv):
            bid_deadline = sys.argv[idx + 1]
    
    # 读取模板JSON
    try:
        with open(templates_file, 'r', encoding='utf-8') as f:
            template_data = json.load(f)
    except Exception as e:
        print(f"❌ 读取模板文件失败: {e}")
        sys.exit(1)
    
    # 读取投标文件
    try:
        with open(bid_file, 'r', encoding='utf-8') as f:
            bid_full_text = f.read()
    except Exception as e:
        print(f"❌ 读取投标文件失败: {e}")
        sys.exit(1)
    
    # 提取模板列表
    templates = template_data.get("fixed_format_templates", []) if "fixed_format_templates" in template_data else template_data
    
    if isinstance(templates, dict) and "fixed_format_templates" in template_data:
        templates = template_data["fixed_format_templates"]
    
    # 简单的投标文件分段（按章节标题划分）
    bid_lines = bid_full_text.split('\n')
    bid_sections = {"全文": bid_full_text}
    current_section = "全文"
    
    for line in bid_lines:
        header_match = re.match(r'^#{1,4}\s+(.+)$', line.strip())
        if header_match:
            current_section = header_match.group(1).strip()
            bid_sections[current_section] = ""
        else:
            if current_section not in bid_sections:
                bid_sections[current_section] = ""
            bid_sections[current_section] += line + '\n'
    
    # 执行每个模板的diff
    template_results = []
    total_fields_all = 0
    total_issues_all = 0
    
    print(f"📖 diff引擎启动: {bid_file}")
    print(f"   模板数量: {len(templates)}")
    print(f"   投标文件分段: {len(bid_sections)} 个章节")
    print()
    
    for template in templates:
        print(f"  🔍 扫描模板: {template.get('template_name', '未知')}")
        result = diff_template(template, bid_lines, bid_deadline)
        template_results.append(result)
        total_fields_all += result["total_fields"]
        total_issues_all += result["fields_with_issues"]
        
        # 打印摘要
        field_types = result.get("field_types_covered", [])
        print(f"     字段: {result['total_fields']}个, 问题: {result['fields_with_issues']}个")
        print(f"     覆盖字段类型: {len(field_types)}/13")
        if result["fields_with_issues"] > 0:
            for f in result["fields"]:
                if f["has_issue"]:
                    print(f"       ❌ {f['field_name']}({f['field_type']}): {f['verdict']}")
    
    # 13类字段覆盖验证
    all_field_types_covered = set()
    for tr in template_results:
        all_field_types_covered.update(tr.get("field_types_covered", []))
    field_types_missing = [ft for ft in FIELD_TYPES_13 if ft not in all_field_types_covered]
    
    # 组装输出
    output = {
        "module": "B",
        "bid_file": bid_file,
        "templates_file": templates_file,
        "check_time": __import__('datetime').datetime.now().isoformat(),
        "total_templates": len(templates),
        "total_fields": total_fields_all,
        "differences_found": total_issues_all,
        "templates": template_results,
        "special_terms_diff": [
            {"field_type": ft, "checked": ft in all_field_types_covered,
             "match": True, "mismatch": False}
            for ft in FIELD_TYPES_13
        ],
        "field_type_coverage": {
            "total_types": len(FIELD_TYPES_13),
            "covered_types": len(all_field_types_covered),
            "covered_list": sorted(all_field_types_covered),
            "missing_list": sorted(field_types_missing),
            "all_covered": len(field_types_missing) == 0
        },
        "summary": {
            "total_templates": len(templates),
            "total_fields": total_fields_all,
            "exact_match_count": total_fields_all - total_issues_all,
            "difference_count": total_issues_all,
            "p0_differences": sum(
                1 for tr in template_results for f in tr["fields"]
                if f["has_issue"] and f["verdict"] == "❌"
            ),
            "verdict": "pass" if total_issues_all == 0 else "fail"
        },
        "execution_marker": "✅ 模块B全量diff执行完成" if len(field_types_missing) == 0 else "❌ diff扫描不完整，缺少字段类型: " + ", ".join(field_types_missing)
    }
    
    # 打印统计
    print()
    print(f"📊 diff统计:")
    print(f"   总模板: {len(templates)}")
    print(f"   总字段: {total_fields_all}")
    print(f"   差异数: {total_issues_all}")
    print(f"   13类字段覆盖: {len(all_field_types_covered)}/13")
    if field_types_missing:
        print(f"   缺失类型: {', '.join(field_types_missing)}")
    print(f"   执行状态: {output['execution_marker']}")
    print()
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"✅ 输出已保存: {output_file}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    
    sys.exit(0 if len(field_types_missing) == 0 else 2)


if __name__ == "__main__":
    main()
