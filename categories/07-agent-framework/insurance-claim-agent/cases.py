#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史理赔案例匹配模块

从案例库（cases.json）中，为新案件检索最相似的 top_k 历史案例，供核赔参考。

匹配策略：
1. 主路径：用 SCNet 文本模型做语义检索 —— 把案例摘要 + 新案件拼成 prompt，
   让模型返回最相似案例的 id 与相似理由（更准，能理解"事故形态/受损部位/责任"语义）。
2. 兜底：本地关键词字符重叠相似度（无 Key / 模型不可用时仍能工作）。

接口：
  load_cases(path) -> list
  match_cases(query_text, cases=None, model=..., top_k=3) -> list[{case_id, reason, case}]
"""
import os
import json

from claim_analyzer import (
    call_llm,
    _extract_json,
    get_api_key,
    SCNET_BASE_URL,
)
from memory_store import active_custom_cases

_DEFAULT_CASES = os.path.join(os.path.dirname(__file__), "cases.json")


def load_cases(path=_DEFAULT_CASES):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_all_cases():
    """种子案例库 + 经人工批准的自增长案例（EvolveR 经验库维护产物）。"""
    try:
        custom = active_custom_cases()
    except Exception:
        custom = []
    return load_cases() + custom


def _case_summary(c):
    return (
        f"[{c.get('id','')}] {c.get('title','')} | 类型:{c.get('accident_type','')} | "
        f"事故:{c.get('accident_desc','')} | 车:{c.get('vehicle_info','')} | "
        f"损失:{c.get('damage_desc','')} | 维修:{c.get('repair_list','')} | "
        f"责任:{c.get('liability','')} | 定损:{c.get('estimated_loss','')}"
    )


def match_cases(query_text, cases=None, model="glm-4-9b-chat",
                base_url=SCNET_BASE_URL, api_key=None, top_k=3):
    """为新案件检索最相似的历史案例。返回 [{case_id, reason, case}]。"""
    if cases is None:
        cases = get_all_cases()
    if not cases or not query_text or not query_text.strip():
        return []

    summaries = "\n".join(_case_summary(c) for c in cases)
    prompt = (
        "你是车险理赔案例检索专家。下面是一批历史理赔案例摘要：\n"
        f"{summaries}\n\n"
        "【待匹配的新案件】\n"
        f"{query_text}\n\n"
        f"请从上面的历史案例中挑出与新案件最相似（事故类型、受损部位、责任形态、车型相近）"
        f"的 {top_k} 个，按相似度从高到低返回 JSON 数组，每项含 'case_id' 与 'reason'"
        "（一句话说明相似点）。只返回 JSON 数组，不要额外说明。\n"
        '示例：[{{"case_id":"C001","reason":"同为追尾全责，前杠与大灯受损"}}]'
    )

    try:
        if api_key is None:
            api_key = get_api_key()
        raw = call_llm([{"role": "user", "content": prompt}], model,
                       base_url=base_url, api_key=api_key)
        arr = _extract_json(raw)
        if isinstance(arr, list) and arr:
            by_id = {c["id"]: c for c in cases}
            out = []
            for item in arr[:top_k]:
                cid = item.get("case_id")
                if cid in by_id:
                    out.append({"case_id": cid, "reason": item.get("reason", ""), "case": by_id[cid]})
            if out:
                return out
    except Exception:
        pass

    # 兜底：本地关键词字符重叠
    return _local_match(query_text, cases, top_k)


def _local_match(query, cases, top_k):
    q_chars = set(query)
    scored = []
    for c in cases:
        text = _case_summary(c)
        denom = max(len(set(text)), 1)
        overlap = len(q_chars & set(text)) / denom
        scored.append((overlap, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"case_id": c["id"], "reason": "关键词重叠匹配（本地兜底）", "case": c}
        for _, c in scored[:top_k]
    ]


if __name__ == "__main__":
    cs = load_cases()
    print(f"案例库共 {len(cs)} 条")
    print(_case_summary(cs[0]))
