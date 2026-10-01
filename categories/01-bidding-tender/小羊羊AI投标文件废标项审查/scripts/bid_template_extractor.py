#!/usr/bin/env python3
"""
bid_template_extractor.py — 招标文件固定格式精准提取器 v2（v5.0.0）
====================================================================

功能：从招标文件的"第四部分 附件"章节中，精准提取所有固定格式附件的
      全部文字内容，逐行逐字段输出供模块B diff引擎使用。

精准提取规则：
  1. 只提取真实的附件内容（跳过目录/列举行）
  2. 每个附件只提取一次（去重）
  3. 附件命名精确（★报价函 而非 **★）
  4. 提取附件的每一行文字（非空、非格式行）
  5. 按行号标注来源位置

使用方式：
  python bid_template_extractor.py <tender_file.md> [--output <templates.json>]
"""

import json, sys, os, re
from typing import List, Dict, Any


def locate_attachments(text: str) -> List[Dict[str, Any]]:
    """
    精准定位招标文件中的固定格式附件。
    
    策略：
    - 找到 "第四部分 附件" 章节后开始扫描
    - 真实附件标题格式：**N、★名称**（N是数字，无双星号包裹的"附件"前缀）
    - 跳过列举行：**附件N、名称**（双星号包裹"附件"前缀的）
    - 跳过非附件内容："采购文件的澄清""采购文件的修改"等
    - 下一个 ## 主章节时结束
    """
    lines = text.split('\n')
    attachments = []
    in_section = False
    current = None
    
    # 非附件白名单（这些虽然出现在附件区但不是固定格式模板）
    skip_names = {"采购文件的澄清", "采购文件的修改", "踏勘现场"}
    
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        
        # 进入附件章节：仅在Markdown加粗格式的"第四部分 附件"行触发
        if s.startswith("**") and "第四部分 附件" in s:
            in_section = True
            continue
        if not in_section:
            continue
        
        # 退出条件：遇到下一个 ## 主章节且不是附件
        if re.match(r'^##\s+', s) and "附件" not in s and "格式" not in s and "说明" not in s:
            if current:
                current["end"] = i
                attachments.append(current)
                current = None
            break
        
        # 真实附件标题
        # 跳过列举行：**附件N、名称**
        if re.match(r'\*\*附件\d+', s):
            continue
        
        # 检测附件标题行：**数字、内容**
        # 格式可能为 **1、★报价函** 或 **1、**★**报价函**
        m = re.match(r'\*\*(\d+)[、．.,]\s*(.*)', s)
        if m:
            num = int(m.group(1))
            rest = m.group(2).strip()
            
            # 从rest中提取真正的名称（去掉尾部**和中间**）
            name = rest.replace('**', '').strip()
            
            if name in skip_names or "采购文件" in name:
                continue
            
            # 标准化名称
            if name.startswith("★"):
                pass  # 已正确
            elif num in (1, 2, 3, 6, 7, 8, 12, 13, 14):
                name = f"★{name}"
            # 其他：保持原名
            
            # 关闭上一个
            if current:
                current["end"] = i
                attachments.append(current)
            
            current = {
                "number": num, "name": name,
                "start": i, "end": len(lines)
            }
            continue
        
        # 处理多段式附件（同编号的下一段）
        if current and s.startswith("**") and s.endswith("**"):
            # 检查是否是同一附件号的第二部分
            m2 = re.match(r'\*\*(\d+)[、．.,]?\s*\*?\*?(.+?)\*?\*?\s*\*\*', s)
            if m2:
                n2 = int(m2.group(1))
                if n2 == current["number"]:
                    continue  # 同编号的续段，合并
    
    # 最后一个
    if current:
        current["end"] = len(lines)
        attachments.append(current)
    
    return attachments


def is_format_line(s: str) -> bool:
    """判断是否是纯格式行（表格分隔线、空Markdown等）。"""
    if re.match(r'^[\|\s\-:+=\*]+$', s):
        return True
    if re.match(r'^[-=]{3,}$', s):
        return True
    if s.startswith("![") or s.startswith("data:image"):
        return True
    return False


def extract_lines(lines: List[str], start: int, end: int) -> List[Dict[str, Any]]:
    """提取附件范围内的所有有效文字行。"""
    extracted = []
    seen = set()
    
    for i in range(start, min(end, len(lines))):
        raw = lines[i]
        s = raw.strip()
        if not s or is_format_line(s):
            continue
        
        # 去重：短内容的相邻重复
        key = s[:40]
        if key in seen:
            continue
        
        # 判断字段类型
        ftype = "文字"
        if "签名" in s or "签章" in s or "签字" in s:
            ftype = "签字"
        elif "公章" in s or "印章" in s:
            ftype = "公章类型"
        elif s.startswith("日 期") or s.startswith("日期"):
            ftype = "日期"
        elif "项目名称" in s or "项目编号" in s or "包号" in s:
            ftype = "项目信息"
        elif "备注" in s or s.startswith("注"):
            ftype = "备注"
        elif "供应商名称" in s or "投标人名称" in s:
            ftype = "落款名称"
        
        # 判断验证规则
        if "（" in s or "(" in s or "＿" in s:
            vrule = "逐字填写"
        else:
            vrule = "逐字一致"
        
        seen.add(key)
        extracted.append({
            "row": i + 1,
            "text": s[:300],
            "type": ftype,
            "rule": vrule
        })
    
    return extracted


def main():
    if len(sys.argv) < 2:
        print("使用: python bid_template_extractor.py <招标文件.md> [--output <output.json>]")
        sys.exit(1)
    
    tender_file = sys.argv[1]
    output_file = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]
    
    with open(tender_file, 'r', encoding='utf-8') as f:
        text = f.read()
    lines = text.split('\n')
    
    attachments = locate_attachments(text)
    
    templates = []
    total_fields = 0
    
    print(f"招标文件: {tender_file}")
    print(f"发现 {len(attachments)} 个固定格式附件:\n")
    
    for att in attachments:
        fields = extract_lines(lines, att["start"], att["end"])
        
        # 统计类型
        tc = {}
        for f in fields:
            tc[f["type"]] = tc.get(f["type"], 0) + 1
        summary = ", ".join([f"{k}×{v}" for k, v in sorted(tc.items())])
        
        templates.append({
            "template_id": f"FF-{att['number']:03d}",
            "template_name": att["name"],
            "source": f"招标文件第四部分附件{att['number']} (第{att['start']+1}-{att['end']}行)",
            "fields": [{
                "field_name": f"{att['name']}_第{f['row']}行",
                "field_type": f["type"],
                "template_text": f["text"],
                "verification_rule": f["rule"]
            } for f in fields]
        })
        total_fields += len(fields)
        
        print(f"  {att['name']}: {len(fields)}字段 [{summary}]")
    
    print(f"\n总计: {len(templates)}个模板, {total_fields}个字段")
    
    output = {
        "module": "A_template_extractor_v2",
        "tender_file": tender_file,
        "total_templates": len(templates),
        "total_fields": total_fields,
        "fixed_format_templates": templates,
        "execution_marker": f"✅ 已提取{len(templates)}个固定格式模板共{total_fields}个字段"
    }
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n已保存: {output_file}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
