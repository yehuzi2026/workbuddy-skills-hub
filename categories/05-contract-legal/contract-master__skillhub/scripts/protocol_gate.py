#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合同智囊 · 协议锁硬门槛（Protocol Gate）

把 SKILL.md 中的「规则 0」从口头约束改造成可执行门禁：
  1. 生成 loading_manifest.json 模板（init）
  2. 校验 loading_manifest.json 是否完整（validate）

用法：
  # 生成模板（AI 填充后再校验）
  python scripts/protocol_gate.py init --mode review --contract-type 买卖合同 --out .workbuddy/loading_manifest.json

  # 校验门禁
  python scripts/protocol_gate.py validate --manifest .workbuddy/loading_manifest.json

返回码：
  0 = 门禁通过，可以继续审查/起草
  1 = 门禁未通过，必须在补齐前阻断流程

设计原则：
  - 「必须输出」改为「必须产出文件并通过校验」
  - 校验失败给出明确的 blocking 项，AI/用户必须处理
  - 不替代模型思考，只作为不可绕过的质量门

注意：本脚本只负责「协议锁」门禁，不含任何付费逻辑。合同智囊的全部软件功能
（审核/起草/比对/修订/IMA检索/双版本条款/批量/质控/落痕）均为免费；
仅「人工审核」为按次付费服务，其付费逻辑在 scripts/human_review.py。
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent

# 核心专用库配置（与 SKILL.md 保持一致）
REQUIRED_IMA_LIBRARIES = {
    "7304523668277375": "合同范本库",
    "7327158150131411": "合同大全3000+",
    "7331252013124181": "法务工作及合同审查",
}

# 各模式必须加载的本地 references
REQUIRED_REFERENCES = {
    "review": [
        "contract-review-knowledge.md",
        "risk-patterns/high-risk-clauses.md",
        "risk-patterns/missing-clauses.md",
    ],
    "draft": [
        "contract-review-knowledge.md",
        "risk-patterns/high-risk-clauses.md",
        "risk-patterns/missing-clauses.md",
    ],
    "diff": [
        "contract-review-knowledge.md",
        "risk-patterns/high-risk-clauses.md",
        "risk-patterns/missing-clauses.md",
    ],
    "revise": [],  # 依附于 review，不重复执行协议锁
}


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def make_manifest_template(mode: str, contract_type: str | None) -> dict:
    """生成一份待填充的 loading_manifest.json 模板。"""
    return {
        "version": "1.0.0",
        "mode": mode,
        "contract_type": contract_type or "待识别",
        "timestamp": _utc_now(),
        "passed": False,
        "ima_status": {
            lib_id: {
                "name": name,
                "subscribed": None,  # true / false / null(未知)
                "searched": False,
                "hits": None,
                "note": "",
            }
            for lib_id, name in REQUIRED_IMA_LIBRARIES.items()
        },
        "references_loaded": [
            {
                "path": ref,
                "loaded": False,
                "size_kb": None,
                "note": "",
            }
            for ref in REQUIRED_REFERENCES.get(mode, [])
        ],
        "local_files": [],  # 元素: {"path": "...", "priority": "P0", "reviewed": false, "note": ""}
        "rule_pack": {
            "path": f"rule-packs/{contract_type or '{合同类型}'}/legal_rules.json" if mode in ("review", "draft") else None,
            "loaded": False,
        },
        "ima_searches": [],  # 元素: {"library_id": "...", "query": "...", "hits": 0, "sampled": false}
        "three_way_matrix": None,  # true / false / null，审核/起草模式触发
        "coverage_extraction": None,  # true / false / null，必须输出全面覆盖提炼
        "blocking": [],
        "notes": "",
    }


def init_manifest(args):
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = make_manifest_template(args.mode, args.contract_type)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[protocol_gate] 已生成协议锁模板：{out_path}")
    print(f"[protocol_gate] 请填充后运行：python scripts/protocol_gate.py validate --manifest {out_path}")
    return 0


def _add_blocking(manifest: dict, reason: str):
    manifest["passed"] = False
    if reason not in manifest.get("blocking", []):
        manifest.setdefault("blocking", []).append(reason)


def validate_manifest(args):
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"[protocol_gate] ❌ 门禁失败：未找到 manifest 文件 {manifest_path}", file=sys.stderr)
        print("[protocol_gate] 请先生成模板并填充：python scripts/protocol_gate.py init --mode review --out .workbuddy/loading_manifest.json", file=sys.stderr)
        return 1

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[protocol_gate] ❌ 门禁失败：manifest JSON 解析错误：{e}", file=sys.stderr)
        return 1

    mode = manifest.get("mode", "review")
    manifest["blocking"] = []
    manifest["passed"] = True  # 先假设通过，再逐项打叉

    # 1. 检查 IMA 订阅状态是否已记录（不强制必须订阅，但必须检查并记录）
    ima_status = manifest.get("ima_status", {})
    for lib_id, name in REQUIRED_IMA_LIBRARIES.items():
        info = ima_status.get(lib_id)
        if not info:
            _add_blocking(manifest, f"未记录 IMA 库「{name}({lib_id})」的订阅状态")
            continue
        subscribed = info.get("subscribed")
        if subscribed is None:
            _add_blocking(manifest, f"IMA 库「{name}」订阅状态未知（subscribed 不能为 null）")
        if mode in ("review", "draft") and not info.get("searched"):
            _add_blocking(manifest, f"IMA 库「{name}」尚未完成搜索（review/draft 模式强制）")

    # 2. 检查本地 reference 是否已加载
    refs = manifest.get("references_loaded", [])
    required = REQUIRED_REFERENCES.get(mode, [])
    for req in required:
        found = any(r.get("path") == req and r.get("loaded") for r in refs)
        if not found:
            _add_blocking(manifest, f"未加载核心 reference：{req}")
    # 同时检查文件是否真实存在
    for ref in required:
        if not (SKILL_ROOT / "references" / ref).exists():
            _add_blocking(manifest, f"reference 文件在本地不存在：references/{ref}")

    # 3. 检查 rule-pack（review/draft）
    if mode in ("review", "draft"):
        rule_pack = manifest.get("rule_pack", {})
        rp_path = rule_pack.get("path")
        if not rp_path:
            _add_blocking(manifest, "未设置 rule-pack 路径")
        elif not rule_pack.get("loaded"):
            # 如果合同类型尚未识别，允许路径含占位符
            if "{" not in rp_path and not (SKILL_ROOT / "references" / rp_path).exists():
                _add_blocking(manifest, f"rule-pack 文件不存在：references/{rp_path}")
            elif "{" not in rp_path:
                _add_blocking(manifest, f"rule-pack 未标记为已加载：{rp_path}")

    # 4. 检查 IMA 搜索记录（review/draft）
    if mode in ("review", "draft"):
        searches = manifest.get("ima_searches", [])
        searched_lib_ids = {s.get("library_id") for s in searches}
        for lib_id, name in REQUIRED_IMA_LIBRARIES.items():
            if lib_id not in searched_lib_ids:
                _add_blocking(manifest, f"IMA 库「{name}」缺少搜索记录")

    # 5. 检查全面覆盖提炼（review/draft）
    if mode in ("review", "draft"):
        if manifest.get("coverage_extraction") is not True:
            _add_blocking(manifest, "未输出全面覆盖提炼（coverage_extraction 必须为 true）")

    # 6. 检查三层比选矩阵是否按需触发
    if mode in ("review", "draft"):
        # 跨来源比选：当且仅当 ≥2 个 IMA 库都有命中（多来源模板）时才强制输出矩阵
        # （单个库命中多条不算多来源，无需比选矩阵）
        hits_by_lib = {}
        for s in manifest.get("ima_searches", []):
            lib = s.get("library_id")
            h = s.get("hits") or 0
            if lib and h > 0:
                hits_by_lib[lib] = hits_by_lib.get(lib, 0) + h
        sources_with_hits = sum(1 for v in hits_by_lib.values() if v > 0)
        if sources_with_hits >= 2 and manifest.get("three_way_matrix") is not True:
            _add_blocking(manifest, "多模板来源命中（≥2 个 IMA 库有命中），但未输出三层比选矩阵")

    # 写回校验结果
    manifest["timestamp"] = _utc_now()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if manifest["passed"]:
        print(f"[protocol_gate] ✅ 协议锁门禁通过（mode={mode}）")
        return 0

    print(f"[protocol_gate] ❌ 协议锁门禁未通过（mode={mode}），blocking 项：", file=sys.stderr)
    for idx, reason in enumerate(manifest["blocking"], 1):
        print(f"  {idx}. {reason}", file=sys.stderr)
    print(f"[protocol_gate] 请在补齐上述项后重新运行：python scripts/protocol_gate.py validate --manifest {manifest_path}", file=sys.stderr)
    return 1


def main():
    parser = argparse.ArgumentParser(description="合同智囊协议锁硬门槛")
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="生成 loading_manifest.json 模板")
    init_p.add_argument("--mode", choices=["review", "draft", "diff", "revise"], default="review")
    init_p.add_argument("--contract-type", default=None, help="合同类型，如 买卖合同")
    init_p.add_argument("--out", default=".workbuddy/loading_manifest.json", help="输出路径")
    init_p.set_defaults(func=init_manifest)

    val_p = sub.add_parser("validate", help="校验 loading_manifest.json 并决定是否放行")
    val_p.add_argument("--manifest", default=".workbuddy/loading_manifest.json", help="待校验的 manifest 路径")
    val_p.set_defaults(func=validate_manifest)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
