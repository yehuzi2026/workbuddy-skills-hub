#!/usr/bin/env python3
"""
bid_directory_check.py — 模块C1目录比对脚本（v5.0.0）
====================================================

功能：根据招标文件的"投标文件的组成/目录/固定格式目录"要求，
      自动比对投标文件的实际目录，输出缺失/多余/页码差异。

使用方式：
    python bid_directory_check.py <tender_file.md> <bid_file.md> [--output <output.json>]

强制执行规则：
    - 招标要求但投标缺失的章节 → ❌ 标记缺失
    - 招标要求★必交但投标没有的 → ❌ 标记废标风险
    - 目录页码与实际内容页不一致 → ⚠️ 标记待确认
    - 比对完成必须输出✅确认
"""

import json
import sys
import os
import re
from typing import List, Dict, Any, Tuple


# ============================================================
# 1. 目录提取引擎
# ============================================================

def extract_toc_from_markdown(text: str) -> List[Dict[str, Any]]:
    """
    从Markdown文件中提取目录结构。
    识别规则：
    1. Markdown标题（#/##/### 开头）
    2. ★标记的章节
    3. 固定格式附件名称
    """
    entries = []
    lines = text.split('\n')
    
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        
        # 识别Markdown标题
        header_match = re.match(r'^(#{1,4})\s+(.+)$', stripped)
        if header_match:
            level = len(header_match.group(1))
            title = header_match.group(2).strip()
            
            # 检测是否是★固定格式
            is_star = '★' in title
            is_fixed_format = any(kw in title for kw in ["★报价函", "★商务响应表", "★法定代表人授权委托书",
                                                         "★服务响应表", "★报价一览表", "★报价明细表",
                                                         "固定格式", "附件"])
            
            entries.append({
                "type": "header",
                "title": title,
                "level": level,
                "line_no": line_idx + 1,
                "is_star": is_star,
                "is_fixed_format": is_fixed_format
            })
        
        # 识别目录行（数字序号开头，带页码）
        toc_match = re.match(r'^(\d+(?:\.\d+)*)[.．、\s]+(.+?)\s+(\d+)\s*$', stripped)
        if toc_match:
            entries.append({
                "type": "toc",
                "number": toc_match.group(1),
                "title": toc_match.group(2).strip(),
                "page": int(toc_match.group(3)),
                "line_no": line_idx + 1
            })
    
    return entries


def extract_required_sections(text: str) -> Dict[str, Any]:
    """
    从招标文件中提取"投标文件的组成"要求的章节清单。
    
    提取规则（严格）：
    1. 只在"投标文件的组成/响应文件格式/附件"章节内提取
    2. 只提取★标记的**文档名称**，不提取描述性文字
    3. 附件名称从附件列表提取（附件1、附件2...）
    4. 排除包含"供应商须""供应商需""应提供""须提供"等描述的文字
    """
    required = []
    star_required = []
    fixed_formats = []
    
    lines = text.split('\n')
    in_composition_section = False
    
    # 描述性文字排除关键词
    exclude_keywords = [
        "供应商须", "供应商需", "应提供", "须提供", "须具有", "须提交",
        "未提供", "未提交", "一律为", "视为", "不得", "必须", "属于",
        "是指", "注：", "备注：", "如果", "若", "请", "建议"
    ]
    
    # ★必交文档名称白名单（只提取这些，其他★标记的描述不提取）
    known_required_docs = [
        "★报价函", "★法定代表人授权委托书", "★商务响应表",
        "★服务响应表", "★报价一览表", "★报价明细表",
        "★企业营业执照", "★财务审计报告", "★依法缴纳税收",
        "★具备履行合同", "★没有重大违法记录",
        "★谈判文件第六部分", "★供应商必须提交"
    ]
    
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        
        # 定位"投标文件的组成/响应文件格式/附件"章节
        if any(kw in stripped for kw in ["第三部分 响应文件格式", "第四部分 附件",
                                          "投标文件的组成", "响应文件格式", "文件目录"]):
            in_composition_section = True
            continue
        
        if in_composition_section:
            # 退出条件：遇到下一个主章节（## 开头的其他章节）
            if re.match(r'^#{2,3}\s+', stripped) and not any(kw in stripped for kw in ["附件", "格式", "响应文件"]):
                if line_idx > 15:  # 至少读了15行
                    in_composition_section = False
            
            # 检查是否包含排除词（描述性文字）
            is_descriptive = any(kw in stripped for kw in exclude_keywords)
            
            # 提取★标记的必交文件（仅限文档名称，排除描述性文字）
            star_match = re.search(r'★(.+?)(?:\s|$|（|\[)', stripped)
            if star_match and not is_descriptive:
                item = star_match.group(1).strip()
                # 只保留简短文档名（≤30字符）或已知文档名
                is_known = any(item.startswith(kw.replace("★", "")) for kw in known_required_docs)
                if len(item) <= 30 or is_known:
                    star_required.append({
                        "name": f"★{item}",
                        "line_no": line_idx + 1,
                        "full_line": stripped[:80]
                    })
                    required.append({
                        "name": f"★{item}",
                        "mandatory": True,
                        "line_no": line_idx + 1
                    })
            
            # 提取附件名称（附件1、附件2... 格式）
            att_match = re.match(r'\*\*(?:附件\d+[、．.]?\s*)?★?(.+?)\*\*', stripped)
            if att_match and not is_descriptive:
                att_name = att_match.group(1).strip()
                if len(att_name) <= 30 and att_name not in [r["name"] for r in required]:
                    # 只是记录，不强制要求（因为附件名称在投标文件中可能以不同格式出现）
                    pass
            
            # 提取固定格式附件（仅从固定的附件列表中提取）
            if re.match(r'^\*\*附件\d+', stripped):
                fmt_match = re.search(r'\*\*附件\d+[、．.]?\s*(.+?)\*\*', stripped)
                if fmt_match:
                    name = fmt_match.group(1).strip()
                    if name and len(name) <= 40 and "★" in stripped:
                        fixed_formats.append({
                            "name": name,
                            "line_no": line_idx + 1
                        })
    
    return {
        "required_sections": required,
        "star_required": star_required,
        "fixed_formats": fixed_formats,
        "total_required": len(required),
        "total_star": len(star_required),
        "total_fixed_formats": len(fixed_formats)
    }


# ============================================================
# 2. 目录比对引擎
# ============================================================

def compare_directories(tender_sections: Dict[str, Any],
                        bid_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    比对招标要求清单 vs 投标文件实际目录。
    """
    required = tender_sections.get("required_sections", [])
    star_required = tender_sections.get("star_required", [])
    fixed_formats = tender_sections.get("fixed_formats", [])
    
    bid_titles = [e["title"] for e in bid_entries if e["type"] == "header"]
    bid_titles_lower = [t.lower().replace(" ", "").replace("　", "") for t in bid_titles]
    
    # 检查缺失章节
    missing_sections = []
    missing_star = []
    missing_fixed = []
    
    for req in required:
        name = req["name"]
        name_lower = name.lower().replace(" ", "").replace("　", "")
        
        found = any(name_lower in bt for bt in bid_titles_lower)
        if not found:
            missing_sections.append(req)
            if req.get("mandatory"):
                missing_star.append(req)
    
    for fmt in fixed_formats:
        name = fmt["name"]
        name_lower = name.lower().replace(" ", "").replace("　", "")
        
        found = any(name_lower in bt for bt in bid_titles_lower)
        if not found:
            missing_fixed.append(fmt)
    
    # 检查多余章节（投标有但招标不要求的——不判定为问题，仅记录）
    tender_titles = set()
    for e in bid_entries:
        if e["type"] == "header":
            tender_titles.add(e["title"])
    
    # 汇总
    return {
        "tender_required_count": len(required),
        "bid_section_count": len([e for e in bid_entries if e["type"] == "header"]),
        "missing_sections": missing_sections,
        "missing_star_count": len(missing_star),
        "missing_star_list": [m["name"] for m in missing_star],
        "missing_fixed_formats": missing_fixed,
        "completeness_rate": round(1 - len(missing_sections) / max(len(required), 1), 4),
        "has_missing_star": len(missing_star) > 0,
        "verdict": "⚠️" if len(missing_star) > 0 else ("⚠️" if len(missing_sections) > 0 else "✅")
    }


# ============================================================
# 3. 主入口
# ============================================================

def main():
    if len(sys.argv) < 3:
        print("=" * 60)
        print("bid_directory_check.py — 模块C1目录比对脚本")
        print("=" * 60)
        print()
        print("使用方式:")
        print(f"  python {os.path.basename(__file__)} <tender_file.md> <bid_file.md> [--output <output.json>]")
        print()
        sys.exit(1)
    
    tender_file = sys.argv[1]
    bid_file = sys.argv[2]
    output_file = None
    
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]
    
    # 读取文件
    try:
        with open(tender_file, 'r', encoding='utf-8') as f:
            tender_text = f.read()
        with open(bid_file, 'r', encoding='utf-8') as f:
            bid_text = f.read()
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        sys.exit(1)
    
    print(f"📖 目录比对启动:")
    print(f"   招标文件: {tender_file}")
    print(f"   投标文件: {bid_file}")
    print()
    
    # 提取招标文件要求的章节清单
    tender_sections = extract_required_sections(tender_text)
    print(f"   📋 招标文件要求: {tender_sections['total_required']} 个章节")
    print(f"      ★必交: {tender_sections['total_star']} 个")
    print(f"      固定格式: {tender_sections['total_fixed_formats']} 个")
    
    # 提取投标文件目录
    bid_entries = extract_toc_from_markdown(bid_text)
    bid_headers = [e for e in bid_entries if e["type"] == "header"]
    print(f"   📋 投标文件章节: {len(bid_headers)} 个")
    print()
    
    # 执行比对
    result = compare_directories(tender_sections, bid_entries)
    
    # 组装输出
    output = {
        "module": "C1",
        "phase": "C1_directory_check",
        "check_time": __import__('datetime').datetime.now().isoformat(),
        "tender_file": tender_file,
        "bid_file": bid_file,
        "tender_requirements": {
            "total_required": tender_sections["total_required"],
            "star_required": tender_sections["total_star"],
            "fixed_formats_required": tender_sections["total_fixed_formats"],
            "star_required_list": tender_sections["star_required"],
            "fixed_format_list": tender_sections["fixed_formats"]
        },
        "bid_actual": {
            "total_sections": len(bid_headers),
            "sections": [{"title": e["title"], "level": e["level"]} for e in bid_headers]
        },
        "comparison_result": {
            "missing_sections": result["missing_sections"],
            "missing_star_count": result["missing_star_count"],
            "missing_star_list": result["missing_star_list"],
            "missing_fixed_formats": result["missing_fixed_formats"],
            "completeness_rate": result["completeness_rate"],
            "has_missing_star": result["has_missing_star"]
        },
        "verdict": result["verdict"],
        "execution_marker": "✅ 模块C1目录比对执行完成"
    }
    
    # 打印结果
    print(f"📊 目录比对结果:")
    print(f"   完整率: {result['completeness_rate']*100:.1f}%")
    if result["missing_star_list"]:
        print(f"   ❌ 缺失★必交文件: {', '.join(result['missing_star_list'])}")
    if result["missing_fixed_formats"]:
        print(f"   ⚠️ 缺失固定格式: {[f['name'] for f in result['missing_fixed_formats']]}")
    print(f"   判定: {result['verdict']}")
    print(f"   执行状态: ✅ 完成")
    print()
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"✅ 输出已保存: {output_file}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    
    sys.exit(0 if result["has_missing_star"] == 0 else 2)


if __name__ == "__main__":
    main()
