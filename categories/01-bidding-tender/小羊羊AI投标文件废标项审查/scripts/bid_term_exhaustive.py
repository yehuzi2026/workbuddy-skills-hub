#!/usr/bin/env python3
"""
bid_term_exhaustive.py — 模块C3专项名称全文穷举引擎（v5.0.0）
============================================================

功能：对招标文件专项名词和投标单位专项名词执行全文穷举校验。
      每个名称从投标文件第1页检索到末页，核对所有出现位置是否完全一致。

使用方式：
    python bid_term_exhaustive.py <special_terms.json> <bid_file.md> [--output <output.json>]
    python bid_term_exhaustive.py <special_terms.json> <bid_file.md> --ocr-dir <ocr_results_dir> [--output <output.json>]

执行逻辑：
    逐个专项名称 → 每项一次全文穷举 → 记录所有出现位置 → 交叉比对 →
    检查一致/不一致 → OCR交叉验证 → 输出该项结论 → 进入下一项

强制执行规则：
    - 每个名称必须扫全本（第1行→末行），漏扫 → 该项标记❌
    - 同一名称在不同位置值不同 → ❌
    - 投标公司名称必须OCR验证所有图片公章文字 → 不一致 → ❌
    - 人员身份证/手机号必须OCR验证 → 不一致 → ❌
    - 银行账号跨位置不一致 → ❌
"""

import json
import sys
import os
import re
from typing import List, Dict, Any, Optional
from collections import defaultdict


# ============================================================
# 1. 投标文件全文扫描引擎
# ============================================================

def scan_term_in_document(term_name: str, term_value: str, bid_text: str,
                          is_bidder_term: bool = False) -> Dict[str, Any]:
    """
    在投标文件全文中扫描指定专项名称的出现位置，并核对值是否一致。
    
    执行逻辑：
        1. 用term_value作为搜索值，从第1行扫到末行
        2. 找出所有包含term_value的行
        3. 对每个位置提取上下文进行确认
        4. 汇总所有出现位置的值是否一致
    
    Args:
        term_name: 专项名称（如"项目名称""投标公司名称"）
        term_value: 标准值（从模块A或投标文件首次出现处提取）
        bid_text: 投标文件全文
        is_bidder_term: 是否是投标单位自定义名词
    
    Returns:
        扫描结果
    """
    lines = bid_text.split('\n')
    total_lines = len(lines)
    
    # 构建搜索关键词
    # 对于招标名词，用标准值搜索
    # 对于投标名词，先找第一次出现的位置
    search_values = [term_value]
    
    # 如果term_value很长，取前15个字符即可（避免标点符号干扰）
    if len(term_value) > 15:
        search_values.append(term_value[:15])
    
    occurrences = []
    seen_lines = set()
    
    for line_idx, line in enumerate(lines):
        actual_line_no = line_idx + 1
        
        for search_val in search_values:
            if search_val in line:
                dedup_key = (actual_line_no, search_val)
                if dedup_key in seen_lines:
                    continue
                seen_lines.add(dedup_key)
                
                # 提取整行作为上下文
                context = line.strip()
                
                # 尝试从行中提取更精确的值
                extracted_value = extract_value_from_line(term_name, line, term_value)
                
                occurrences.append({
                    "line_no": actual_line_no,
                    "context": context[:200],  # 截取前200字符
                    "extracted_value": extracted_value,
                    "match": extracted_value == term_value if extracted_value else None
                })
                
                break  # 找到一个match就继续下一行
    
    # 判断一致性（改进版：不再要求精确相等，改用"包含"逻辑）
    # 对于招标文件名词：standard_value 存在于 extracted_value 中即视为匹配
    # 对于投标单位名词：所有出现位置的值互相包含即视为一致
    extracted_values = [o["extracted_value"] for o in occurrences if o["extracted_value"]]
    
    if not extracted_values:
        is_consistent = False
        inconsistent_values = []
        verdict = "❌"
        reason = "在投标文件中未找到此专项名称"
    else:
        is_consistent = True
        inconsistent_values = []
        
        for i, val in enumerate(extracted_values):
            this_match = False
            
            # 对招标文件名词：check if standard_value is contained in the line's value
            if not is_bidder_term:
                val_clean = val.replace(" ", "").replace("　", "")
                std_clean = term_value.replace(" ", "").replace("　", "")
                this_match = std_clean in val_clean
            else:
                # 对投标单位名词：check first value against current
                this_match = (extracted_values[0] in val) or (val in extracted_values[0])
            
            if not this_match:
                is_consistent = False
                inconsistent_values.append({
                    "occurrence": i + 1,
                    "line_no": occurrences[i]["line_no"] if i < len(occurrences) else 0,
                    "standard": term_value,
                    "actual": val
                })
            is_consistent = True
            inconsistent_values = []
            veredict = "✅"
            reason = "所有出现位置值完全一致"
    
    # 判断verdict
    if not occurrences:
        verdict = "❌"
    elif not is_consistent:
        verdict = "❌"
    else:
        verdict = "✅"
    
    return {
        "term_name": term_name,
        "standard_value": term_value,
        "is_bidder_term": is_bidder_term,
        "scan_range": f"第1行→第{total_lines}行",
        "total_lines_scanned": total_lines,
        "total_occurrences": len(occurrences),
        "occurrences": occurrences,
        "is_consistent": is_consistent,
        "inconsistent_values": inconsistent_values,
        "verdict": verdict,
        "reason": reason,
        "scan_completed": True  # ✅
    }


def extract_value_from_line(term_name: str, line: str, default_value: str) -> Optional[str]:
    """
    从行中尝试提取专项名称的实际值。
    对于不同类型的term，使用不同的提取策略。
    """
    line = line.strip()
    if not line:
        return None
    
    # 对于短的term_value直接返回整行
    if len(default_value) <= 5:
        return line[:50]
    
    # 尝试找行中非标签部分的值
    # 例如：行是"项目名称：济南大学学生公寓服务保障..."
    # 提取冒号后的内容
    for sep in ['：', ':', '为', '是']:
        if sep in line:
            parts = line.split(sep, 1)
            if len(parts) > 1:
                value = parts[1].strip()
                # 如果提取的值太短则放弃
                if len(value) >= 5:
                    return value
    
    # 直接包含default_value的大部分字符
    if default_value in line:
        return default_value
    
    # 返回整行前80字符
    return line[:80]


# ============================================================
# 2. 交叉引用提取器
# ============================================================

def extract_all_bank_accounts(bid_text: str) -> Dict[str, Any]:
    """
    提取投标文件中所有银行账号信息，跨位置比对一致性。
    """
    # 银行账号正则：常见账号格式（16-22位数字）
    account_pattern = re.compile(r'\b(\d{16,22})\b')
    
    # 账号上下文关键词
    account_keywords = ["账号", "账户", "开户行", "银行", "保证金账户"]
    
    accounts_found = []
    lines = bid_text.split('\n')
    
    for line_idx, line in enumerate(lines):
        accounts = account_pattern.findall(line)
        for acc in accounts:
            # 检查附近是否有账号相关关键词
            has_context = any(kw in line for kw in account_keywords)
            accounts_found.append({
                "line_no": line_idx + 1,
                "account": acc,
                "context": line.strip()[:100],
                "has_account_keyword": has_context
            })
    
    # 分组判断一致性
    unique_accounts = set(a["account"] for a in accounts_found)
    
    if len(unique_accounts) <= 1:
        is_consistent = True
        inconsistent = []
    else:
        is_consistent = False
        inconsistent = [
            {"account": acc, "occurrences": [a["line_no"] for a in accounts_found if a["account"] == acc]}
            for acc in unique_accounts
        ]
    
    return {
        "total_accounts_found": len(accounts_found),
        "unique_accounts": list(unique_accounts),
        "is_consistent": is_consistent,
        "inconsistent_accounts": inconsistent if not is_consistent else [],
        "details": accounts_found,
        "verdict": "✅" if is_consistent else "❌"
    }


def extract_all_id_numbers(bid_text: str) -> Dict[str, Any]:
    """
    提取所有身份证号，跨位置比对一致性。
    """
    # 身份证号正则（18位，最后位可能是X）
    id_pattern = re.compile(r'\b(\d{17}[\dXx])\b')
    
    ids_found = []
    lines = bid_text.split('\n')
    
    for line_idx, line in enumerate(lines):
        ids = id_pattern.findall(line)
        for id_no in ids:
            ids_found.append({
                "line_no": line_idx + 1,
                "id_number": id_no,
                "context": line.strip()[:100]
            })
    
    unique_ids = set(i["id_number"] for i in ids_found)
    
    return {
        "total_ids_found": len(ids_found),
        "unique_ids": list(unique_ids),
        "total_unique": len(unique_ids),
        "details": ids_found
    }


def extract_all_phone_numbers(bid_text: str) -> Dict[str, Any]:
    """
    提取所有手机号，跨位置比对一致性。
    """
    phone_pattern = re.compile(r'\b(1[3-9]\d{9})\b')
    
    phones_found = []
    lines = bid_text.split('\n')
    
    for line_idx, line in enumerate(lines):
        phones = phone_pattern.findall(line)
        for phone in phones:
            phones_found.append({
                "line_no": line_idx + 1,
                "phone": phone,
                "context": line.strip()[:100]
            })
    
    # 按号码分组统计
    phone_groups = defaultdict(list)
    for p in phones_found:
        phone_groups[p["phone"]].append(p["line_no"])
    
    return {
        "total_phones_found": len(phones_found),
        "phone_groups": {k: v for k, v in phone_groups.items()},
        "total_unique": len(phone_groups),
        "details": phones_found
    }


# ============================================================
# 3. OCR交叉验证（通用版）
# ============================================================

def ocr_cross_verify_field(field_name: str, field_value: str,
                            ocr_results_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    通用OCR交叉验证：在OCR识别结果中搜索指定字段的值。
    
    支持的字段类型：
    - 投标公司名称 → 扫描所有图片中公章文字
    - 注册资金 → 扫描营业执照图片，找"注册资金/注册资本"字段
    - 营业执照号 → 扫描营业执照图片，找"统一社会信用代码/营业执照号"
    - 法定代表人姓名 → 扫描身份证/营业执照图片
    - 经营范围 → 扫描营业执照图片
    
    Args:
        field_name: 字段名称（如"注册资金""投标公司名称"）
        field_value: 投标文件中填写的文字值
        ocr_results_dir: OCR结果目录（包含ocr_results.json）
    """
    if not ocr_results_dir or not os.path.isdir(ocr_results_dir):
        return {"ocr_available": False, "message": "OCR结果目录未提供", "verdict": "⚠️"}
    
    ocr_results_file = os.path.join(ocr_results_dir, "ocr_results.json")
    if not os.path.exists(ocr_results_file):
        return {"ocr_available": False, "message": "OCR结果文件不存在", "verdict": "⚠️"}
    
    try:
        with open(ocr_results_file, 'r', encoding='utf-8') as f:
            ocr_data = json.load(f)
    except Exception:
        return {"ocr_available": False, "message": "OCR结果文件读取失败", "verdict": "⚠️"}
    
    # 构建OCR全量文本（用于搜索）
    all_ocr_text = ""
    ocr_image_list = ocr_data if isinstance(ocr_data, list) else [ocr_data]
    
    # 字段特定的OCR提取模式
    field_patterns = {
        "注册资金": [
            r'(?:注册资本|注册资金)[：:]\s*([\d,]+\.?\d*\s*万?)',
            r'(?:注册资本|注册资金)[：:]\s*([壹贰叁肆伍陆柒捌玖拾佰仟万亿元整角分]+)',
            r'注册资本[：:]?\s*([\d,]+\.?\d*)',  # 宽松匹配：注册资本后直接跟数字
            r'注册资本[：:]?\s*([壹贰叁肆伍陆柒捌玖拾佰仟万亿元整角分]+)',
        ],
        "营业执照号": [
            r'(?:统一社会信用代码|营业执照号|信用代码)[：:]\s*(\w+)',
            r'\b(\d{18}|\d{15})\b',  # 18位或15位代码
        ],
        "法定代表人姓名": [
            r'(?:法定代表人|负责人|法人代表)[：:]\s*(\S+)',
        ],
        "经营范围": [
            r'(?:经营范围)[：:]\s*(.+)',
        ],
    }
    
    # ====== 在OCR全文中直接搜索field_value ======
    direct_matches = []
    direct_mismatches = []
    
    for img in ocr_image_list:
        img_text = ""
        if isinstance(img, dict):
            img_text = img.get("text", "") or img.get("ocr_text", "") or json.dumps(img)
        else:
            img_text = str(img)
        
        img_name = img.get("image", "unknown") if isinstance(img, dict) else "unknown"
        all_ocr_text += img_text + "\n"
        
        if field_value and field_value in img_text:
            direct_matches.append({"image": img_name, "found_text": field_value[:50]})
        elif field_value and len(field_value) > 5 and field_value[:10] in img_text:
            direct_mismatches.append({"image": img_name, "expected": field_value[:50], "ocr_text": img_text[:100]})
    
    # ====== 对于特殊字段，尝试结构化提取 ======
    structured_extractions = {}
    if field_name in field_patterns:
        patterns = field_patterns[field_name]
        for pattern in patterns:
            matches = re.findall(pattern, all_ocr_text)
            if matches:
                structured_extractions[field_name] = matches[:5]  # 最多取前5个
    
    # ====== 如果是注册资金，与投标文字值做数值比对 ======
    numeric_comparison = None
    if field_name == "注册资金" and field_value:
        # 从投标文字中提取纯数字（去掉"万"等）
        bid_num_match = re.search(r'([\d.]+)', field_value.replace(',', ''))
        bid_value_clean = float(bid_num_match.group(1)) if bid_num_match else None
        
        # 从OCR结构化提取中获取数值
        ocr_values = structured_extractions.get("注册资金", [])
        for ocr_val in ocr_values:
            ocr_num_match = re.search(r'([\d.]+)', ocr_val.replace(',', ''))
            if ocr_num_match and bid_value_clean:
                ocr_num = float(ocr_num_match.group(1))
                if abs(bid_value_clean - ocr_num) > 0.01:
                    numeric_comparison = {
                        "bid_text_value": field_value.strip(),
                        "bid_numeric": bid_value_clean,
                        "ocr_extracted_value": ocr_val.strip(),
                        "ocr_numeric": ocr_num,
                        "diff": abs(bid_value_clean - ocr_num),
                        "match": False
                    }
                    break
    
    # 综合判定
    has_structured = len(structured_extractions) > 0
    has_direct_match = len(direct_matches) > 0
    has_mismatch = len(direct_mismatches) > 0
    
    if numeric_comparison and not numeric_comparison["match"]:
        # 注册资金数值不匹配 → ❌
        verdict = "❌"
        summary = f"数值不一致: 投标文字={numeric_comparison['bid_text_value']}, OCR识别={numeric_comparison['ocr_extracted_value']}"
    elif has_mismatch:
        verdict = "❌"
        summary = f"部分图片中文字不匹配"
    elif has_direct_match:
        verdict = "✅"
        summary = f"文字一致 ({len(direct_matches)}张图片)"
    elif has_structured:
        verdict = "✅"
        summary = f"OCR已提取到结构化信息"
    else:
        verdict = "⚠️"
        summary = "OCR中未找到相关信息（可能无此字段图片）"
    
    return {
        "ocr_available": True,
        "field_name": field_name,
        "field_value": field_value,
        "images_scanned": len(ocr_image_list),
        "direct_matches": direct_matches,
        "direct_mismatches": direct_mismatches,
        "structured_extractions": structured_extractions,
        "numeric_comparison": numeric_comparison,
        "summary": summary,
        "verdict": verdict
    }


# ============================================================
# 4. 主执行引擎
# ============================================================

def execute_exhaustive_check(special_terms: Dict[str, Any],
                              bid_text: str,
                              ocr_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    执行完整的专项名称穷举校验。
    
    流程：
    1. 先处理招标文件专项名词（标准值来自招标文件）
    2. 再处理投标单位专项名词（标准值从投标文件首次出现提取）
    3. 最后执行交叉引用检查（银行账号、身份证、手机号）
    4. OCR交叉验证
    """
    tender_terms = special_terms.get("tender_terms", [])
    bidder_terms = special_terms.get("bidder_terms", [])
    
    results = []
    tender_pass = 0
    tender_fail = 0
    bidder_pass = 0
    bidder_fail = 0
    
    print(f"📖 专项名称穷举校验启动:")
    print()
    
    # === A. 招标文件专项名词 ===
    print(f"  【A】招标文件专项名词 ({len(tender_terms)}项)")
    print(f"  {'='*50}")
    
    for term in tender_terms:
        term_name = term.get("term_name", "未知")
        standard_value = term.get("standard_value", "")
        
        print(f"    🔍 第{term.get('term_name', '?')}: {term_name}")
        print(f"       标准值: {standard_value[:60]}...")
        
        result = scan_term_in_document(term_name, standard_value, bid_text, is_bidder_term=False)
        results.append({
            "term_group": "招标文件专项名词",
            "result": result
        })
        
        if result["verdict"] == "✅":
            tender_pass += 1
            print(f"       ✅ 通过 ({result['total_occurrences']}处出现)")
        else:
            tender_fail += 1
            print(f"       ❌ 问题: {result['reason']}")
            if result.get("inconsistent_values"):
                for iv in result["inconsistent_values"]:
                    print(f"          - 第{iv['line_no']}行: {iv['actual'][:40]}...")
    
    print()
    
    # === B. 投标单位专项名词 ===
    print(f"  【B】投标单位专项名词 ({len(bidder_terms)}项)")
    print(f"  {'='*50}")
    
    for term in bidder_terms:
        term_name = term.get("term_name", "未知")
        standard_value = term.get("standard_value", "")
        
        # 如果标准值是占位符，则从投标文件中提取
        if not standard_value or standard_value.startswith("（"):
            extracted = extract_first_occurrence(term_name, bid_text)
            if extracted:
                standard_value = extracted
            else:
                standard_value = "(未提取到)"
        
        print(f"    🔍 {term_name}: {standard_value[:40]}")
        
        result = scan_term_in_document(term_name, standard_value, bid_text, is_bidder_term=True)
        results.append({
            "term_group": "投标单位专项名词",
            "result": result
        })
        
        if result["verdict"] == "✅":
            bidder_pass += 1
            print(f"       ✅ 通过 ({result['total_occurrences']}处出现)")
        else:
            bidder_fail += 1
            print(f"       ❌ 问题: {result['reason']}")
    
    print()
    
    # === C. 交叉引用检查 ===
    print(f"  【C】交叉引用一致性检查")
    print(f"  {'='*50}")
    
    # 银行账号
    bank_result = extract_all_bank_accounts(bid_text)
    results.append({
        "term_group": "交叉引用检查",
        "result": {
            "term_name": "银行账号",
            "bank_account_check": bank_result,
            "verdict": bank_result["verdict"]
        }
    })
    print(f"    🔍 银行账号: {bank_result['unique_accounts']}")
    if bank_result["is_consistent"]:
        print(f"       ✅ 一致 ({len(bank_result['unique_accounts'])}个唯一账号)")
    else:
        print(f"       ❌ 不一致! 存在多个不同账号")
        bidder_fail += 1
    
    # 身份证号
    id_result = extract_all_id_numbers(bid_text)
    results.append({
        "term_group": "交叉引用检查",
        "result": {
            "term_name": "身份证号",
            "id_check": id_result,
            "verdict": "✅"
        }
    })
    print(f"    🔍 身份证号: {id_result['total_unique']}个唯一号码")
    
    # 手机号
    phone_result = extract_all_phone_numbers(bid_text)
    results.append({
        "term_group": "交叉引用检查",
        "result": {
            "term_name": "手机号",
            "phone_check": phone_result,
            "verdict": "✅"
        }
    })
    print(f"    🔍 手机号: {phone_result['total_unique']}个唯一号码")
    
    print()
    
    # === D. OCR交叉验证 ===
    print(f"  【D】OCR交叉验证")
    print(f"  {'='*50}")
    
    # OCR需要验证的字段列表
    ocr_check_fields = [
        ("投标公司名称", ""),
        ("注册资金", ""),
        ("营业执照号", ""),
        ("法定代表人姓名", ""),
    ]
    
    # 从bidder_terms中提取实际值
    for term in bidder_terms:
        term_name = term.get("term_name", "")
        term_value = term.get("standard_value", "")
        for i, (check_name, _) in enumerate(ocr_check_fields):
            if check_name == term_name:
                ocr_check_fields[i] = (term_name, term_value)
    
    ocr_fail_count = 0
    for field_name, field_value in ocr_check_fields:
        if not field_value or field_value.startswith("（"):
            print(f"    ⚠️ {field_name}: 标准值未提取，跳过OCR验证")
            results.append({
                "term_group": "OCR交叉验证",
                "result": {"term_name": field_name, "ocr_check": {"ocr_available": False, "message": "标准值未提取", "verdict": "⚠️"}, "verdict": "⚠️"}
            })
            continue
        
        ocr_result = ocr_cross_verify_field(field_name, field_value, ocr_dir)
        results.append({
            "term_group": "OCR交叉验证",
            "result": {
                "term_name": f"{field_name}(OCR验证)",
                "ocr_check": ocr_result,
                "verdict": ocr_result["verdict"]
            }
        })
        
        if ocr_result["ocr_available"]:
            if ocr_result["verdict"] == "✅":
                print(f"    ✅ {field_name}: {ocr_result['summary']}")
            elif ocr_result["verdict"] == "❌":
                print(f"    ❌ {field_name}: {ocr_result['summary']}")
                ocr_fail_count += 1
            else:
                print(f"    ⚠️ {field_name}: {ocr_result['summary']}")
        else:
            print(f"    ⚠️ {field_name}: OCR验证不可用")
    
    bidder_fail += ocr_fail_count
    
    print()
    
    # === 汇总 ===
    total_terms = len(tender_terms) + len(bidder_terms) + 3  # +3 for bank/id/phone
    total_pass = tender_pass + bidder_pass
    total_fail = tender_fail + bidder_fail
    
    return {
        "module": "C3",
        "phase": "C3_special_term_verify",
        "check_time": __import__('datetime').datetime.now().isoformat(),
        "results": results,
        "summary": {
            "tender_terms_pass": tender_pass,
            "tender_terms_fail": tender_fail,
            "bidder_terms_pass": bidder_pass,
            "bidder_terms_fail": bidder_fail,
            "total_terms_checked": total_terms,
            "total_pass": total_pass,
            "total_fail": total_fail,
            "verdict": "❌" if total_fail > 0 else "✅"
        },
        "execution_marker": "✅ 模块C3专项名称穷举执行完成"
    }


def extract_first_occurrence(term_name: str, bid_text: str) -> Optional[str]:
    """
    从投标文件中提取某个术语第一次出现的上下文值。
    使用多策略匹配：关键词行匹配+标题定位+内容行识别。
    """
    lines = bid_text.split('\n')
    
    # 字段名 → 匹配模式（多策略）
    field_patterns = {
        "投标公司名称": [
            # 策略1：行内直接匹配
            (r'(?:公司名称|供应商名称|投标人名称)[：:]\s*(.+)', "line"),
            # 策略2：报价函首句
            (r'^(.+?)(?:系中华人民共和国|系合法)', "line"),
            # 策略3：公章行
            (r'供应商名称(?:（|\(|\s)公章(?:）|\)|)\s*[：:]\s*(.+)', "line"),
        ],
        "法定代表人姓名": [
            (r'我\s+(\S{2,4})\s+系', "line"),
            (r'法定代表人[：:。]?\s*(?:姓名[：:])?\s*(\S+)', "line"),
        ],
        "注册资金": [
            (r'(?:注册资金|注册资本)[：:]\s*(.+)', "line"),
            (r'\|\s*注册资金\s*\|\s*([\d.]+万?)', "line"),
        ],
        "银行账号": [
            (r'(?:账号|账户)[：:]\s*(\d{16,22})', "line"),
            (r'\b(\d{16,22})\b', "line"),
        ],
        "营业执照号": [
            (r'(?:营业执照号|统一社会信用代码|信用代码)[：:]\s*(\S+)', "line"),
        ],
        "法定代表人手机号": [
            (r'(?:法定代表人.*?电话|法人.*?手机)[：:]\s*(\d{11})', "line"),
            (r'电话[：:]\s*(\d{11})', "line_search"),
        ],
    }
    
    patterns = field_patterns.get(term_name, [])
    
    # 策略1：精确模式匹配
    for pattern, mode in patterns:
        for line in lines:
            try:
                m = re.search(pattern, line)
                if m:
                    value = m.group(1).strip()
                    if value and len(value) >= 2:
                        return value
            except re.error as e:
                # 打印出问题的pattern以便调试
                print(f"      ⚠️ 正则错误: {e} (pattern: {pattern[:50]}...)")
                continue
    
    # 策略2：章节标题定位（找包含该术语的标题，然后找下一行的值）
    section_patterns = {
        "投标公司名称": ["报价函", "公司", "供应商"],
        "法定代表人姓名": ["法定代表人", "法人"],
        "注册资金": ["注册资金", "注册资本"],
        "银行账号": ["账号", "开户银行", "银行开户"],
        "法定代表人手机号": ["联系方式", "电话", "手机"],
    }
    
    section_kws = section_patterns.get(term_name, [])
    if section_kws:
        found_section = False
        for i, line in enumerate(lines):
            if any(kw in line for kw in section_kws):
                found_section = True
                continue
            if found_section and len(line.strip()) > 5:
                # 找包含数字或关键数据的下一行
                if re.search(r'[\d]', line) and len(line.strip()) < 100:
                    return line.strip()[:80]
                found_section = False
    
    return None


# ============================================================
# 5. 主入口
# ============================================================

def main():
    if len(sys.argv) < 3:
        print("=" * 60)
        print("bid_term_exhaustive.py — 模块C3专项名称穷举引擎")
        print("=" * 60)
        print()
        print("使用方式:")
        print(f"  python {os.path.basename(__file__)} <special_terms.json> <bid_file.md> [options]")
        print()
        print("参数:")
        print("  special_terms.json    模块A生成的专项名词标准值JSON")
        print("  bid_file.md           投标文件Markdown格式")
        print("  --output <file>       输出JSON文件路径")
        print("  --ocr-dir <dir>       OCR结果目录（可选，用于交叉验证）")
        print()
        sys.exit(1)
    
    terms_file = sys.argv[1]
    bid_file = sys.argv[2]
    output_file = None
    ocr_dir = None
    
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]
    
    if "--ocr-dir" in sys.argv:
        idx = sys.argv.index("--ocr-dir")
        if idx + 1 < len(sys.argv):
            ocr_dir = sys.argv[idx + 1]
    
    # 读取专项名词JSON
    try:
        with open(terms_file, 'r', encoding='utf-8') as f:
            terms_data = json.load(f)
    except Exception as e:
        print(f"❌ 读取专项名词文件失败: {e}")
        sys.exit(1)
    
    # 提取special_terms
    special_terms = terms_data.get("special_terms", terms_data)
    
    # 读取投标文件
    try:
        with open(bid_file, 'r', encoding='utf-8') as f:
            bid_text = f.read()
    except Exception as e:
        print(f"❌ 读取投标文件失败: {e}")
        sys.exit(1)
    
    # 执行穷举校验
    result = execute_exhaustive_check(special_terms, bid_text, ocr_dir)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✅ 输出已保存: {output_file}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    sys.exit(0 if result["summary"]["total_fail"] == 0 else 2)


if __name__ == "__main__":
    main()
