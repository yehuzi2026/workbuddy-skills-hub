#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合同智囊 · 人工审核付费服务（Human Review Paywall）

本脚本是合同智囊**唯一**的付费入口：用户选择「人工审核」时输出 skillpay 支付意图，
由平台渲染支付链接；支付完成后平台回调 reveal 动作读取 assets/contact.json 显露联系方式，
走线下执业律师复核。

交互机制：A（平台回调）
  skillpay 在支付成功后主动回调本脚本的 reveal_contact，确保联系方式仅在付费后可见。
  本脚本不自行轮询支付状态。如平台采用其他通知方式（如注入状态变量），
  把触发 reveal_contact 的入口改成读取该状态即可。

设计要点：
  - 不把任何真实联系方式硬编码进 SKILL.md / scripts，统一放 assets/contact.json
    （本地、权限 600、不进发布包）
  - 支付链接与商品由 skillpay 平台托管，本脚本只「声明」商品 + 「支付后动作」
  - **仅「人工审核」收费**；合同智囊其余软件功能全部免费

用法：
  python scripts/human_review.py cta      # 输出支付意图 JSON（平台渲染支付链接）
  python scripts/human_review.py contact  # 支付完成后显露联系方式与引导话术（由平台在付费事件后回调）

返回码：
  0 = 成功
  1 = 失败（如联系方式未配置）
"""
import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONTACT_FILE = SKILL_ROOT / "assets" / "contact.json"

# ===== skillpay 商品配置（在 skillpay 后台创建商品后，填入真实值）=====
PAYMENT_PRODUCT = {
    "sku": "contract-review-human-review",   # TODO: 替换为 skillpay 后台真实 SKU
    "name": "合同智囊·执业律师人工复核",
    "price_cents": 3990,                     # 单位：分（即 ¥39.90 / 份）
    "currency": "CNY",
    "desc": "执业律师人工复核，1-3 个工作日内出具书面复核意见",
    "pricing_note": "9月1日前 39.9 元/份（早鸟价）",
    "delivery": "支付完成后自动显露联系方式，线下对接",
}


def emit_cta():
    """输出支付意图 payload，交由平台渲染支付链接（机制 A：平台回调 reveal_contact）。"""
    payload = {
        "type": "skillpay_paywall",
        "version": 1,
        "product": PAYMENT_PRODUCT,
        "post_pay": {
            "action": "reveal_contact",
            "contact_file": str(CONTACT_FILE),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def reveal_contact():
    """支付完成后显露联系方式与引导话术（仅应在付费事件后由平台回调）。"""
    if not CONTACT_FILE.exists():
        print(json.dumps(
            {"error": "联系方式未配置：assets/contact.json 缺失，请在 skillpay 上线、企业认证通过后填入真实信息"},
            ensure_ascii=False,
        ), file=sys.stderr)
        return 1
    try:
        data = json.loads(CONTACT_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"contact.json 解析失败：{e}"}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="合同智囊人工审核付费服务")
    sub = parser.add_subparsers(dest="command", required=True)

    cta_p = sub.add_parser("cta", help="输出 skillpay 支付意图（平台渲染支付链接）")
    cta_p.set_defaults(func=emit_cta)

    contact_p = sub.add_parser("contact", help="支付完成后显露联系方式与引导话术")
    contact_p.set_defaults(func=reveal_contact)

    args = parser.parse_args()
    sys.exit(args.func())


if __name__ == "__main__":
    main()
