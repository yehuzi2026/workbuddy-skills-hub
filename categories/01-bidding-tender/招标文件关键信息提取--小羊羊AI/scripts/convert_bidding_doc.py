#!/usr/bin/env python3
"""
招标文件格式转换脚本 v0.2.0
支持 PDF、DOCX 和 .DOC（旧版 Word 97-2003）格式的招标文件转换为纯文本

用法:
    python convert_bidding_doc.py <input_file> [--output <output_dir>] [--format txt|md]

依赖:
    pip install python-docx PyMuPDF markitdown olefile
    可选: pywin32 (Windows .doc → .docx 转换)
"""

import sys
import os
import json
import re
from pathlib import Path
from datetime import datetime


def convert_docx(filepath: str) -> str:
    """将 DOCX 文件转换为纯文本"""
    try:
        from docx import Document
    except ImportError:
        print("ERROR: python-docx 未安装，请执行: pip install python-docx")
        sys.exit(1)

    doc = Document(filepath)
    lines = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            # 检测标题样式
            if para.style.name.startswith("Heading"):
                level = para.style.name.replace("Heading ", "").replace("Heading", "")
                if level.isdigit():
                    prefix = "#" * int(level)
                    lines.append(f"\n{prefix} {text}\n")
                else:
                    lines.append(f"\n## {text}\n")
            else:
                lines.append(text)

    # 也提取表格内容
    for i, table in enumerate(doc.tables):
        lines.append(f"\n--- 表格 {i+1} ---")
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells)
            lines.append(row_text)
        lines.append("---\n")

    return "\n".join(lines)


def convert_pdf(filepath: str) -> str:
    """将 PDF 文件转换为纯文本（优先使用 PyMuPDF，fallback 到 markitdown）"""
    text = ""

    # 方法1: 尝试 PyMuPDF (fitz)
    try:
        import fitz
        doc = fitz.open(filepath)
        lines = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text("text")
            if page_text.strip():
                lines.append(f"\n## 第 {page_num + 1} 页\n")
                lines.append(page_text)
        doc.close()
        text = "\n".join(lines)
        if len(text.strip()) > 100:
            return text
    except ImportError:
        pass
    except Exception as e:
        print(f"PyMuPDF 提取失败: {e}")

    # 方法2: 尝试 markitdown CLI
    try:
        import subprocess
        result = subprocess.run(
            ["markitdown", filepath],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0 and len(result.stdout.strip()) > 100:
            return result.stdout
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"markitdown 提取失败: {e}")

    # 方法3: 提示用户手动处理
    print("WARNING: 无法自动提取 PDF 文本，请使用 markitdown-skill 或手动转换")
    return text or f"⚠️ PDF文本提取失败: {filepath}\n请使用 markitdown-skill 或 OCR 工具手动转换。"


def convert_doc(filepath: str, output_dir: str = ".") -> str:
    """
    将旧版 .doc (Word 97-2003) 转换为文本
    逐级回退策略: Word COM → LibreOffice → olefile → 人工
    """
    # 方法1: Word COM 自动化 (Windows)
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(filepath)
        docx_path = os.path.join(output_dir, "_temp_converted.docx")
        doc.SaveAs2(docx_path, FileFormat=16)
        doc.Close()
        word.Quit()
        pythoncom.CoUninitialize()
        if os.path.exists(docx_path):
            text = convert_docx(docx_path)
            os.remove(docx_path)
            if len(text.strip()) > 500:
                print(f"✅ .doc→WordCOM→docx ({len(text)} chars)")
                return text
    except ImportError:
        pass
    except Exception as e:
        print(f"Word COM 转换失败: {e}")

    # 方法2: LibreOffice 命令行
    try:
        import subprocess
        result = subprocess.run(
            ["soffice", "--headless", "--convert-to", "docx", filepath,
             "--outdir", output_dir],
            capture_output=True, text=True, timeout=60
        )
        base = os.path.splitext(os.path.basename(filepath))[0]
        docx_path = os.path.join(output_dir, f"{base}.docx")
        if os.path.exists(docx_path):
            text = convert_docx(docx_path)
            os.remove(docx_path)
            if len(text.strip()) > 500:
                print(f"✅ .doc→LibreOffice→docx ({len(text)} chars)")
                return text
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"LibreOffice 转换失败: {e}")

    # 方法3: olefile 降级提取
    try:
        import olefile, re
        ole = olefile.OleFileIO(filepath)
        text_parts = []
        for stream_name in ole.listdir():
            stream_path = '/'.join(stream_name)
            try:
                data = ole.openstream(stream_path).read()
                decoded = data.decode('utf-16-le', errors='ignore')
                runs = re.findall(
                    r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\d\w\s'
                    r'，。；：""''！？（）【】《》、+\-*/%=<>@#&|]+',
                    decoded
                )
                long_runs = [r for r in runs if len(r) > 15]
                if long_runs:
                    text_parts.append('\n'.join(long_runs))
            except:
                pass
        ole.close()
        combined = '\n'.join(text_parts)
        if len(combined.strip()) > 500:
            print(f"⚠️ .doc→olefile 降级提取 ({len(combined)} chars) — 建议人工核对")
            return f"⚠️ [低质量提取] 旧版.doc格式，通过olefile降级提取。建议用Word另存为.docx后重新上传。\n\n{combined}"
    except ImportError:
        pass
    except Exception as e:
        print(f"olefile 提取失败: {e}")

    # 方法4: 全部失败
    return f"❌ 无法读取旧版 .doc 文件: {os.path.basename(filepath)}\n请用 Microsoft Word 打开后另存为 .docx 格式后重新上传。"


def detect_format(filepath: str) -> str:
    """检测文件格式"""
    ext = Path(filepath).suffix.lower()
    if ext == ".docx":
        return "docx"
    elif ext == ".pdf":
        return "pdf"
    elif ext == ".doc":
        return "doc"  # 需要先转 docx
    else:
        return "unknown"


def basic_extraction(text: str) -> dict:
    """执行基础的正则提取，输出初步结构"""
    result = {
        "project_name": "",
        "project_number": "",
        "procurement_method": "",
        "total_pages_estimate": 0,
        "has_scoring_section": False,
        "has_tech_requirements": False,
        "star_clause_count": 0,
        "equipment_keywords_found": [],
        "sections_found": []
    }

    # 项目名称（通常在文件开头）
    name_match = re.search(r'项目名称[：:]\s*(.+?)(?:\n|$)', text)
    if name_match:
        result["project_name"] = name_match.group(1).strip()

    # 项目编号
    number_match = re.search(r'项目编号[：:]\s*(.+?)(?:\n|$)', text)
    if number_match:
        result["project_number"] = number_match.group(1).strip()

    # 采购方式
    method_patterns = ["公开招标", "竞争性磋商", "竞争性谈判", "询价", "单一来源"]
    for method in method_patterns:
        if method in text[:2000]:
            result["procurement_method"] = method
            break

    # 页数估算（按换页符或页标记）
    page_markers = re.findall(r'第\s*\d+\s*页|Page\s+\d+', text)
    result["total_pages_estimate"] = len(page_markers) if page_markers else 1

    # 章节检测
    section_keywords = {
        "采购内容及要求": ["采购内容及要求", "采购需求", "技术要求", "货物需求"],
        "评分标准": ["评审的标准和方法", "评分标准", "综合评分", "评标办法", "评审办法"],
        "投标人须知": ["投标人须知", "供应商须知"],
        "合同条款": ["合同主要条款", "合同草案", "合同条款"],
    }

    for section_name, keywords in section_keywords.items():
        for kw in keywords:
            if kw in text:
                result["sections_found"].append(section_name)
                if section_name == "评分标准":
                    result["has_scoring_section"] = True
                if section_name == "采购内容及要求":
                    result["has_tech_requirements"] = True
                break

    # ★条款计数
    star_matches = re.findall(r'★', text)
    result["star_clause_count"] = len(star_matches)

    # 设备关键词检测
    equipment_keywords = ["台", "套", "个", "设备清单", "货物清单", "采购清单"]
    for kw in equipment_keywords:
        if kw in text:
            result["equipment_keywords_found"].append(kw)

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="招标文件格式转换与基础提取")
    parser.add_argument("input", help="输入文件路径 (PDF 或 DOCX)")
    parser.add_argument("--output", "-o", default=".", help="输出目录 (默认: 当前目录)")
    parser.add_argument("--format", "-f", choices=["txt", "md"], default="md", help="输出格式")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: 文件不存在: {args.input}")
        sys.exit(1)

    fmt = detect_format(str(input_path))
    print(f"检测到文件格式: {fmt}")
    print(f"文件名: {input_path.name}")

    # 转换
    if fmt == "docx":
        text = convert_docx(str(input_path))
    elif fmt == "doc":
        text = convert_doc(str(input_path), str(output_dir))
    elif fmt == "pdf":
        text = convert_pdf(str(input_path))
    else:
        print(f"ERROR: 不支持的文件格式: {fmt}")
        sys.exit(1)

    # 输出目录
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存转换后的全文
    txt_path = output_dir / f"{input_path.stem}_full_text.md"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"全文已保存: {txt_path}")

    # 基础提取
    basic_info = basic_extraction(text)
    json_path = output_dir / f"{input_path.stem}_basic_info.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(basic_info, f, ensure_ascii=False, indent=2)
    print(f"基础信息已保存: {json_path}")

    # 输出摘要
    print("\n=== 快速扫描结果 ===")
    print(f"项目名称: {basic_info['project_name'] or '未检测到'}")
    print(f"项目编号: {basic_info['project_number'] or '未检测到'}")
    print(f"采购方式: {basic_info['procurement_method'] or '未检测到'}")
    print(f"估算页数: {basic_info['total_pages_estimate']}")
    print(f"★条款数量: {basic_info['star_clause_count']}")
    print(f"检测到的章节: {', '.join(basic_info['sections_found']) or '无'}")
    print(f"全文长度: {len(text)} 字符")
    print(f"\n下一步: 将 {txt_path} 提供给 AI 进行深度结构化提取")


if __name__ == "__main__":
    main()
