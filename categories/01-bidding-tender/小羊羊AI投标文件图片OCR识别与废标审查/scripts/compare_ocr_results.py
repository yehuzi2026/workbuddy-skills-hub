#!/usr/bin/env python3
"""
将OCR识别结果与招标文件要求进行智能比对，识别图片内容中的废标风险。

用法:
    python compare_ocr_results.py <ocr_result.json> <tender_requirements.json> <output_report.md>

参数:
    ocr_result.json          : OCR识别结果JSON文件
    tender_requirements.json : 招标文件要求JSON文件(结构化)
    output_report.md         : 输出的比对报告Markdown文件
"""

import os
import sys
import json
import argparse
import re
from pathlib import Path
from datetime import datetime


def load_json(path):
    """加载JSON文件"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_key_info_from_ocr(ocr_results):
    """从OCR结果中提取关键信息"""
    info = {
        "company_names": [],       # 公司名称
        "license_numbers": [],     # 营业执照号
        "dates": [],               # 日期(有效期等)
        "amounts": [],             # 金额
        "person_names": [],        # 人员姓名
        "seal_found": False,       # 是否发现印章
        "signature_found": False,  # 是否发现签名
        "certificates": [],        # 证书/资质
        "full_texts": [],          # 所有文本
    }

    # 印章/签名关键词
    seal_keywords = ['章', '印', '公章', '专用章', '财务章', '合同章']
    signature_keywords = ['签字', '签名', '签章', '法定代表人']

    for result in ocr_results:
        full_text = result.get('full_text', '')
        if not full_text.strip():
            continue

        info['full_texts'].append({
            'image': result['image_file'],
            'text': full_text
        })

        # 检测印章关键词
        for kw in seal_keywords:
            if kw in full_text:
                info['seal_found'] = True
                break

        # 检测签名关键词
        for kw in signature_keywords:
            if kw in full_text:
                info['signature_found'] = True
                break

        # 提取公司名称(常见格式)
        company_patterns = [
            r'([\u4e00-\u9fa5]{2,10}(?:有限公司|股份公司|集团公司|有限责任公司|科技有限公司|电子科技有限公司))',
        ]
        for pattern in company_patterns:
            matches = re.findall(pattern, full_text)
            info['company_names'].extend(matches)

        # 提取营业执照号
        license_patterns = [
            r'统一社会信用代码[：:]\s*([A-Z0-9]{18})',
            r'注册号[：:]\s*(\d{15})',
            r'营业执照[号编号：:]*\s*([A-Z0-9]{15,18})',
        ]
        for pattern in license_patterns:
            matches = re.findall(pattern, full_text)
            info['license_numbers'].extend(matches)

        # 提取日期
        date_patterns = [
            r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日',
            r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        ]
        for pattern in date_patterns:
            matches = re.findall(pattern, full_text)
            info['dates'].extend(matches)

        # 提取金额
        amount_patterns = [
            r'(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:万元|元|圆)',
            r'(?:人民币|RMB|CNY)\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)',
        ]
        for pattern in amount_patterns:
            matches = re.findall(pattern, full_text)
            info['amounts'].extend(matches)

        # 提取证书/资质关键词
        cert_keywords = [
            '营业执照', '资质证书', '安全生产许可证', 'ISO', '认证证书',
            '职业资格证书', '安全生产考核合格证', '建造师', '工程师',
            '社保', '纳税证明', '财务报表', '审计报告',
            '业绩证明', '合同', '竣工验收'
        ]
        for kw in cert_keywords:
            if kw in full_text:
                info['certificates'].append({
                    'type': kw,
                    'image': result['image_file']
                })

    # 去重
    info['company_names'] = list(set(info['company_names']))
    info['license_numbers'] = list(set(info['license_numbers']))
    info['amounts'] = list(set(info['amounts']))

    return info


def compare_with_requirements(ocr_info, tender_req):
    """将OCR提取信息与招标要求比对"""
    findings = []

    # 1. 检查盖章
    if tender_req.get('seal_required', True):
        if ocr_info['seal_found']:
            findings.append({
                'item': '盖章检查',
                'status': 'PASS',
                'detail': f"图片中发现印章关键词",
                'risk': 'LOW'
            })
        else:
            findings.append({
                'item': '盖章检查',
                'status': 'WARN',
                'detail': '图片中未发现印章关键词，需人工确认盖章是否齐全',
                'risk': 'HIGH'
            })

    # 2. 检查签名
    if tender_req.get('signature_required', True):
        if ocr_info['signature_found']:
            findings.append({
                'item': '签名检查',
                'status': 'PASS',
                'detail': '图片中发现签名/签章关键词',
                'risk': 'LOW'
            })
        else:
            findings.append({
                'item': '签名检查',
                'status': 'WARN',
                'detail': '图片中未发现签名关键词，需人工确认法定代表人是否签字',
                'risk': 'MEDIUM'
            })

    # 3. 检查营业执照
    if tender_req.get('business_license_required', True):
        if ocr_info['license_numbers']:
            findings.append({
                'item': '营业执照',
                'status': 'PASS',
                'detail': f"发现信用代码/注册号: {', '.join(ocr_info['license_numbers'])}",
                'risk': 'LOW'
            })
        else:
            cert_images = [c['image'] for c in ocr_info['certificates'] if c['type'] == '营业执照']
            if cert_images:
                findings.append({
                    'item': '营业执照',
                    'status': 'WARN',
                    'detail': f"发现营业执照图片但未识别到证号，需人工核查: {', '.join(cert_images)}",
                    'risk': 'MEDIUM'
                })
            else:
                findings.append({
                    'item': '营业执照',
                    'status': 'FAIL',
                    'detail': '未发现营业执照相关图片',
                    'risk': 'HIGH'
                })

    # 4. 检查资质证书
    required_certs = tender_req.get('required_certificates', [])
    for cert in required_certs:
        found = any(c['type'] == cert for c in ocr_info['certificates'])
        if found:
            cert_images = [c['image'] for c in ocr_info['certificates'] if c['type'] == cert]
            findings.append({
                'item': f'资质证书-{cert}',
                'status': 'PASS',
                'detail': f"发现{cert}相关图片: {', '.join(cert_images)}",
                'risk': 'LOW'
            })
        else:
            # 模糊匹配
            fuzzy_found = any(cert in c['type'] or c['type'] in cert
                            for c in ocr_info['certificates'])
            if fuzzy_found:
                findings.append({
                    'item': f'资质证书-{cert}',
                    'status': 'WARN',
                    'detail': f'发现类似资质"{cert}"的图片，需人工确认',
                    'risk': 'MEDIUM'
                })
            else:
                findings.append({
                    'item': f'资质证书-{cert}',
                    'status': 'FAIL',
                    'detail': f'未发现{cert}相关图片',
                    'risk': 'HIGH'
                })

    # 5. 公司名称一致性检查
    if tender_req.get('bidder_name'):
        bidder = tender_req['bidder_name']
        if ocr_info['company_names']:
            matching = [n for n in ocr_info['company_names'] if bidder in n or n in bidder]
            if matching:
                findings.append({
                    'item': '投标人名称一致性',
                    'status': 'PASS',
                    'detail': f"图片中公司名称与投标人一致: {', '.join(matching)}",
                    'risk': 'LOW'
                })
            else:
                findings.append({
                    'item': '投标人名称一致性',
                    'status': 'WARN',
                    'detail': f'图片中公司名称({", ".join(ocr_info["company_names"])})与投标人"{bidder}"不一致，需核查',
                    'risk': 'HIGH'
                })

    return findings


def generate_report(findings, ocr_info, ocr_results, output_path):
    """生成比对报告"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 统计
    total = len(findings)
    pass_count = sum(1 for f in findings if f['status'] == 'PASS')
    warn_count = sum(1 for f in findings if f['status'] == 'WARN')
    fail_count = sum(1 for f in findings if f['status'] == 'FAIL')

    # 有文本的图片统计
    images_with_text = sum(1 for r in ocr_results if r.get('total_blocks', 0) > 0)
    total_images = len(ocr_results)

    lines = []
    lines.append(f"# 投标文件图片内容审查报告")
    lines.append(f"")
    lines.append(f"**生成时间**: {now}")
    lines.append(f"**图片总数**: {total_images} | **有文字图片**: {images_with_text}")
    lines.append(f"")
    lines.append(f"## 审查摘要")
    lines.append(f"")
    lines.append(f"| 状态 | 数量 | 占比 |")
    lines.append(f"|------|------|------|")
    if total > 0:
        lines.append(f"| PASS | {pass_count} | {pass_count/total*100:.1f}% |")
        lines.append(f"| WARN | {warn_count} | {warn_count/total*100:.1f}% |")
        lines.append(f"| FAIL | {fail_count} | {fail_count/total*100:.1f}% |")
    lines.append(f"")

    # 高风险项
    high_risk = [f for f in findings if f['risk'] == 'HIGH']
    if high_risk:
        lines.append(f"### HIGH 风险项")
        lines.append(f"")
        for f in high_risk:
            lines.append(f"- **{f['item']}**: {f['detail']}")
        lines.append(f"")

    # 详细比对结果
    lines.append(f"## 逐项比对结果")
    lines.append(f"")
    lines.append(f"| 序号 | 审查项 | 状态 | 风险等级 | 详情 |")
    lines.append(f"|------|--------|------|----------|------|")
    for i, f in enumerate(findings, 1):
        status_icon = {'PASS': 'PASS', 'WARN': 'WARN', 'FAIL': 'FAIL'}.get(f['status'], '?')
        lines.append(f"| {i} | {f['item']} | {status_icon} | {f['risk']} | {f['detail']} |")
    lines.append(f"")

    # OCR提取关键信息汇总
    lines.append(f"## 图片关键信息提取汇总")
    lines.append(f"")
    lines.append(f"### 公司/机构名称")
    if ocr_info['company_names']:
        for name in ocr_info['company_names']:
            lines.append(f"- {name}")
    else:
        lines.append(f"- 未识别到")
    lines.append(f"")

    lines.append(f"### 信用代码/注册号")
    if ocr_info['license_numbers']:
        for num in ocr_info['license_numbers']:
            lines.append(f"- {num}")
    else:
        lines.append(f"- 未识别到")
    lines.append(f"")

    lines.append(f"### 证书/资质类型")
    cert_types = set(c['type'] for c in ocr_info['certificates'])
    if cert_types:
        for ct in sorted(cert_types):
            images = [c['image'] for c in ocr_info['certificates'] if c['type'] == ct]
            lines.append(f"- {ct} ({len(images)}张): {', '.join(images[:3])}{'...' if len(images) > 3 else ''}")
    else:
        lines.append(f"- 未识别到")
    lines.append(f"")

    # 有文字的图片列表(摘要)
    lines.append(f"## 图片文字识别详情(前20张)")
    lines.append(f"")
    text_images = [r for r in ocr_results if r.get('total_blocks', 0) > 0][:20]
    for r in text_images:
        lines.append(f"### {r['image_file']}")
        lines.append(f"- 识别文字块: {r['total_blocks']}, 平均置信度: {r.get('avg_confidence', 0):.2f}")
        # 只显示前200字
        text_preview = r.get('full_text', '')[:200]
        if text_preview:
            lines.append(f"- 文字预览: {text_preview}{'...' if len(r.get('full_text', '')) > 200 else ''}")
        lines.append(f"")

    report = "\n".join(lines)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"Report saved to: {output_path}")
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Compare OCR results with tender requirements')
    parser.add_argument('ocr_result', help='OCR result JSON file')
    parser.add_argument('tender_requirements', help='Tender requirements JSON file')
    parser.add_argument('output_report', help='Output report Markdown file')

    args = parser.parse_args()

    ocr_results = load_json(args.ocr_result)
    tender_req = load_json(args.tender_requirements)

    ocr_info = extract_key_info_from_ocr(ocr_results)
    findings = compare_with_requirements(ocr_info, tender_req)
    generate_report(findings, ocr_info, ocr_results, args.output_report)
