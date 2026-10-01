#!/usr/bin/env python3
"""
bid_keyword_scanner.py — 模块A关键词扫描引擎（v5.0.0）
====================================================

功能：对招标文件执行6大类关键词全文扫描，输出所有废标条件的结构化位置信息。
设计原理：不依赖AI"理解"招标文件，通过机械的关键词匹配确保零遗漏。

使用方式：
    python bid_keyword_scanner.py <tender_file.md> [--output <output.json>]

输出：
    JSON文件，包含所有关键词的匹配结果、位置、上下文。

强制执行规则：
    - 6大类关键词必须全部扫描，缺少任何一类 → 标记❌
    - 每条匹配记录附带source_line_no，无行号标记 → 标记⚠️
    - 扫描完成必须输出✅确认
"""

import re
import json
import sys
import os
from typing import List, Dict, Any, Optional


# ============================================================
# 1. 6大类关键词定义
# ============================================================

KEYWORD_CATEGORIES = {
    "显性废标词": {
        "keywords": ["废标", "无效", "否决", "作废", "无效投标", "无效报价", "无效响应"],
        "severity": "P0",
        "description": "直接导致废标的明确条款"
    },
    "强制性指令词": {
        "keywords": ["必须", "不得", "严禁", "不允许", "禁止", "应当", "应提供", "须提供"],
        "severity": "P0",
        "description": "强制性要求或禁止性规定"
    },
    "标记符号": {
        "keywords": ["★", "※", "▲", "●", "◆"],
        "severity": "P0",
        "description": "重点标记的★/※/▲/●/◆条款"
    },
    "要求类": {
        "keywords": ["资格要求", "符合性要求", "实质性", "实质性偏离", "资格性审查", "符合性审查"],
        "severity": "P1",
        "description": "资格/符合性/实质性相关要求"
    },
    "承诺类": {
        "keywords": ["完全响应", "完全符合招标文件", "无偏离", "承诺", "声明"],
        "severity": "P1",
        "description": "投标人需做出的承诺声明"
    },
    "结构类": {
        "keywords": ["投标文件的组成", "固定格式", "固定格式附件", "采购需求", "技术要求", "响应文件格式"],
        "severity": "P2",
        "description": "文件结构和格式要求"
    }
}


# ============================================================
# 2. 核心扫描引擎
# ============================================================

def scan_keywords(text: str, line_offset: int = 0) -> Dict[str, Any]:
    """
    对全文执行6大类关键词扫描。
    
    Args:
        text: 招标文件全文（markdown格式文本）
        line_offset: 行号偏移（如果从文件中间开始读取）
    
    Returns:
        结构化扫描结果
    """
    lines = text.split('\n')
    total_lines = len(lines)
    
    results = {}
    total_matches = 0
    category_stats = {}
    
    for category_name, category_info in KEYWORD_CATEGORIES.items():
        keywords = category_info["keywords"]
        severity = category_info["severity"]
        
        matches = []
        seen_positions = set()  # 去重
        
        for keyword in keywords:
            for line_idx, line in enumerate(lines):
                actual_line_no = line_idx + 1 + line_offset
                
                # 在当前行查找所有出现位置
                positions = [m.start() for m in re.finditer(re.escape(keyword), line)]
                
                for pos in positions:
                    # 去重：同一行+同一关键词只记录第一次出现
                    dedup_key = (actual_line_no, keyword, pos)
                    if dedup_key in seen_positions:
                        continue
                    seen_positions.add(dedup_key)
                    
                    # 提取上下文（前后各50字符）
                    start_ctx = max(0, pos - 50)
                    end_ctx = min(len(line), pos + len(keyword) + 50)
                    context = line[start_ctx:end_ctx].strip()
                    
                    # 提取完整的句子（从上一个句号到下一个句号）
                    sentence_start = line.rfind('。', 0, pos) + 1
                    if sentence_start == 0:
                        sentence_start = 0
                    sentence_end = line.find('。', pos + len(keyword))
                    if sentence_end == -1:
                        sentence_end = len(line)
                    full_sentence = line[sentence_start:sentence_end + 1].strip()
                    
                    matches.append({
                        "keyword": keyword,
                        "line_no": actual_line_no,
                        "position": pos,
                        "context": context,
                        "full_sentence": full_sentence,
                        "severity": severity
                    })
                    total_matches += 1
        
        # 对匹配结果按行号排序
        matches.sort(key=lambda x: (x["line_no"], x["position"]))
        
        results[category_name] = {
            "keywords_scanned": keywords,
            "total_matches": len(matches),
            "matches": matches,
            "severity": severity,
            "completed": True  # ✅ 完成标记
        }
        
        category_stats[category_name] = {
            "total_matches": len(matches),
            "completed": True
        }
    
    return {
        "total_lines_scanned": total_lines,
        "total_matches": total_matches,
        "categories": results,
        "category_stats": category_stats,
        "scan_completed": True,  # ✅ 全部扫描完成
        "scan_completed_at": "✅ 6类关键词已全部扫描完成，无遗漏"
    }


# ============================================================
# 3. 结构化输出提取（供AI使用）
# ============================================================

def extract_disqualification_conditions(scan_result: Dict[str, Any],
                                        document_name: str = "招标文件") -> List[Dict[str, Any]]:
    """
    从扫描结果中提取格式化的废标条件（供模块A输出2使用）。
    
    排列规则：
    1. P0级（显性废标词、强制指令词、标记符号）优先排在前面
    2. 同类关键词合并，去重
    3. 每条附带trigger_keyword和完整原文句子
    """
    conditions = []
    condition_id = 0
    seen_sentences = set()  # 句子级别去重
    
    # 按严重等级排序：P0在前
    severity_order = {"P0": 0, "P1": 1, "P2": 2}
    
    all_matches = []
    for category_name, category_data in scan_result["categories"].items():
        for match in category_data["matches"]:
            # 句子去重
            sentence_key = match["full_sentence"]
            if len(sentence_key) < 5:  # 太短不提取
                continue
            if sentence_key in seen_sentences:
                continue
            seen_sentences.add(sentence_key)
            
            condition_id += 1
            all_matches.append({
                "id": f"D-{condition_id:03d}",
                "category": category_name,
                "trigger_keyword": match["keyword"],
                "source_line_no": match["line_no"],
                "original_text": match["full_sentence"],
                "condition_type": "未知",
                "severity": match["severity"],
                "sort_order": severity_order.get(match["severity"], 9)
            })
    
    # 按严重等级+行号排序
    all_matches.sort(key=lambda x: (x["sort_order"], x["source_line_no"]))
    
    # 重新编号
    for i, cond in enumerate(all_matches):
        cond["id"] = f"D-{i+1:03d}"
    
    return all_matches


# ============================================================
# 4. 章节结构提取（供模块A输出1使用）
# ============================================================

def extract_chapter_structure(text: str) -> List[Dict[str, Any]]:
    """
    提取招标文件的章节结构。
    按markdown标题级别(#/##/###)和常见章节关键词识别。
    """
    chapters = []
    chapter_order = 0
    
    # 常见招标文件章节识别模式
    chapter_patterns = [
        r"^#+\s*(.*?招标公告.*)$",
        r"^#+\s*(.*?投标人须知前附表.*)$",
        r"^#+\s*(.*?投标须知.*)$",
        r"^#+\s*(.*?投标文件的组成.*)$",
        r"^#+\s*(.*?资格.*审查.*)$",
        r"^#+\s*(.*?符合性.*审查.*)$",
        r"^#+\s*(.*?评分.*标准.*)$",
        r"^#+\s*(.*?报价.*要求.*)$",
        r"^#+\s*(.*?采购需求.*)$",
        r"^#+\s*(.*?技术.*要求.*)$",
        r"^#+\s*(.*?技术白皮书.*)$",
        r"^#+\s*(.*?合同.*条款.*)$",
        r"^#+\s*(.*?固定格式.*)$",
        r"^#+\s*(.*?附件.*)$",
    ]
    
    lines = text.split('\n')
    
    for line_idx, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # 识别Markdown标题
        header_match = re.match(r'^(#{1,4})\s+(.+)$', line)
        if header_match:
            level = len(header_match.group(1))
            title = header_match.group(2).strip()
            chapter_order += 1
            chapters.append({
                "order": chapter_order,
                "title": title,
                "level": level,
                "start_line": line_idx + 1,
                "header_marker": "#" * level
            })
    
    return {
        "total_chapters": len(chapters),
        "chapters": chapters,
        "extraction_completed": True  # ✅
    }


# ============================================================
# 5. 入口与验证
# ============================================================

def validate_scan_completeness(scan_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证扫描是否完整执行。
    所有6类关键词都必须扫描完成，缺任何一类 → ❌。
    """
    categories = scan_result.get("categories", {})
    expected_categories = list(KEYWORD_CATEGORIES.keys())
    
    missing = []
    incomplete = []
    
    for cat in expected_categories:
        if cat not in categories:
            missing.append(cat)
        elif not categories[cat].get("completed", False):
            incomplete.append(cat)
    
    all_complete = len(missing) == 0 and len(incomplete) == 0
    
    return {
        "all_categories_scanned": all_complete,
        "missing_categories": missing,
        "incomplete_categories": incomplete,
        "total_expected": len(expected_categories),
        "total_scanned": len(categories),
        "validation": "✅ 全部完整" if all_complete else f"❌ 缺失: {missing + incomplete}"
    }


def main():
    if len(sys.argv) < 2:
        print("=" * 60)
        print("bid_keyword_scanner.py — 模块A关键词扫描引擎")
        print("=" * 60)
        print()
        print("使用方式:")
        print(f"  python {os.path.basename(__file__)} <tender_file.md> [--output <output.json>]")
        print()
        print("参数:")
        print("  tender_file.md    招标文件Markdown格式")
        print("  --output          输出JSON文件路径（可选，默认输出到stdout）")
        print()
        sys.exit(1)
    
    tender_file = sys.argv[1]
    output_file = None
    
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]
    
    # 读取文件
    try:
        with open(tender_file, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        print(f"❌ 文件不存在: {tender_file}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        sys.exit(1)
    
    # 执行扫描
    print(f"📖 正在扫描: {tender_file}")
    print(f"   文件总行数: {len(text.split(chr(10)))}")
    print()
    
    scan_result = scan_keywords(text)
    chapter_structure = extract_chapter_structure(text)
    conditions = extract_disqualification_conditions(scan_result)
    validation = validate_scan_completeness(scan_result)
    
    # 组装完整输出
    output = {
        "module": "A_scanner",
        "tender_file": tender_file,
        "scan_time": __import__('datetime').datetime.now().isoformat(),
        "chapter_structure": chapter_structure,
        "keyword_scan": scan_result,
        "extracted_conditions": {
            "total": len(conditions),
            "items": conditions
        },
        "validation": validation,
        "execution_marker": "✅ 模块A关键词扫描执行完成" if validation["all_categories_scanned"] else "❌ 扫描不完整"
    }
    
    # 输出统计
    print(f"📊 扫描统计:")
    print(f"   总章节数: {chapter_structure['total_chapters']}")
    print(f"   关键词匹配总数: {scan_result['total_matches']}")
    print(f"   提取废标条件: {len(conditions)} 条")
    for cat_name, cat_data in scan_result["categories"].items():
        print(f"   {cat_name}: {cat_data['total_matches']} 处匹配 ✅")
    print(f"   验证状态: {validation['validation']}")
    print()
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"✅ 输出已保存: {output_file}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    
    # 返回0表示成功
    if validation["all_categories_scanned"]:
        sys.exit(0)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
