#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自我进化 · 通用自进化引擎（领域无关）
================================================================
融合两套思想：

A. 方案1 —— 安全「人工在环」学习闭环
   经验沉淀 → 反思净化（人工纠正为锚点）→ 案例自增长 → 经验原则蒸馏 → 验证闸门/人工审阅

B. EvolveR（浙大 + 上海 AI 实验室, ICML 2026）—— 经验驱动闭环
   在线交互 (online interaction) → 离线自蒸馏 (offline self-distillation)
   → 经验库维护 (experience library maintenance) → 策略更新 (policy / RL update)
   注：我们不在生产系统跑真 RL；把「生效原则注入 prompt」视为轻量策略更新，
       且全程置于人工闸门之后（对应 EvolveR 的验证/回滚思想）。

设计红线（防 reflection ≠ improvement、防自动改代码漂移）：
- 任何自动产出（原则 / 案例）先入 pending_assets，status='pending'。
- 必须人工 approve 后才进入生效区（principles.active / custom_cases.active）。
- 蒸馏的"反思"必须有外部信号 grounding：人工评分 ≤2 或人工纠正意见，避免模型自说自话。

------------ 与领域解耦的设计 ------------
调用方只需在实例化 SelfImprove 时传领域参数：
    si = SelfImprove(
        domain_name="合同审查",
        domain_hint="你是一名资深合同审查律师……",
        case_schema_hint='案例字段：id/title/contract_type/risk_point/...',
    )
其余流程（捕获交互、反馈、蒸馏、闸门、注入）完全一致，可套用到任何垂直 Agent。

对外主入口（供 Agent 集成）：
    si.capture_online(task_input, task_output) -> experience_id
    si.feedback(eid, rating=None, correction=None)
    si.run_evolve(model, base_url)             -> 蒸馏一轮 + 提案
    si.get_active_principles_text()            -> 注入 prompt 的附录
    si.get_all_cases(seed_cases_loader)        -> 种子案例 + 自增长案例
    si.list_pending() / si.approve(pid) / si.reject(pid)
"""
from memory_store import (
    record_experience,
    list_experiences,
    update_experience,
    add_pending,
    mark_reflected,
    list_pending,
    approve_asset,
    reject_asset,
    active_principles,
    active_custom_cases,
)
import json

from llm_client import call_llm, extract_json


# 默认蒸馏系统提示（领域无关骨架；{domain_name}/{domain_hint}/{case_schema_hint}/{records} 由实例填充）
_DISTILL_TEMPLATE = """{domain_hint}

下面是一批「{domain_name}」任务的评审/纠正记录，每条含：原始任务材料、AI 输出、人工评分或人工纠正意见。
请从中提炼可复用的"经验资产"，让 {domain_name} Agent 下次更准。

只输出 JSON：
{{
  "principles": ["若干条通用{field_label}判责/处理原则，每条是独立、可执行的判断规则，避免空话套话"],
  "cases": [
    {case_schema_hint}
  ]
}}

铁律：
- principles 必须源自真实纠正信号（人工纠正或低评分），绝不臆造；无可信信号则 principles 返回 []。
- cases 仅从「人工纠正后的正确结论」提炼，且需有别于已有案例；无则 cases 返回 []。
- 不重复该领域人人皆知的常识（那不算经验资产）。

评审记录如下：
{{records}}
"""


class SelfImprove:
    def __init__(
        self,
        domain_name="通用任务",
        domain_hint="你是一名专业的任务处理助手。",
        case_schema_hint='示例案例字段：id/title/type/desc/conclusion',
        field_label="",
        low_rating_threshold=2,
    ):
        self.domain_name = domain_name
        self.domain_hint = domain_hint
        self.case_schema_hint = case_schema_hint
        self.field_label = field_label or domain_name
        self.low_rating_threshold = low_rating_threshold
        # 预热 DB
        import memory_store as _ms
        _ms.init_db()

    # ---------- 在线交互捕获（EvolveR: online interaction） ----------

    def capture_online(self, task_input, task_output):
        """记录一次主任务交互，返回 experience id（供后续 feedback 关联）。"""
        return record_experience(task_input, task_output)

    def feedback(self, eid, rating=None, correction=None):
        """对一条经验追加人工评分/纠正（蒸馏锚点）。"""
        return update_experience(eid, human_rating=rating, human_correction=correction)

    # ---------- 离线自蒸馏（EvolveR: offline self-distillation） ----------

    def _format_records(self, exps):
        out = []
        for e in exps:
            ti, to = e.get("task_input"), e.get("task_output")
            try:
                ti = json.loads(ti) if isinstance(ti, str) else ti
            except Exception:
                pass
            try:
                to = json.loads(to) if isinstance(to, str) else to
            except Exception:
                pass
            block = "【任务材料】" + json.dumps(ti, ensure_ascii=False)
            block += "\n【AI 输出】" + json.dumps(to, ensure_ascii=False)
            if e.get("human_rating") is not None:
                block += "\n【人工评分】" + str(e["human_rating"]) + "/5"
            if e.get("human_correction"):
                block += "\n【人工纠正】" + e["human_correction"]
            out.append(block)
        return "\n\n----\n\n".join(out)

    def _distill(self, exps, model, base_url):
        records = self._format_records(exps)
        prompt = _DISTILL_TEMPLATE.format(
            domain_name=self.domain_name,
            domain_hint=self.domain_hint,
            case_schema_hint=self.case_schema_hint,
            field_label=self.field_label,
            records=records,
        )
        try:
            raw = call_llm(
                [{"role": "user", "content": prompt}],
                model, base_url=base_url, api_key=None,
            )
        except Exception as e:  # noqa
            return {"ok": False, "reason": "llm error: %s" % e}
        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            return {"ok": False, "reason": "distill 未返回 JSON"}
        return {
            "ok": True,
            "principles": parsed.get("principles") or [],
            "cases": parsed.get("cases") or [],
        }

    def _propose(self, distilled, source_ids):
        """把蒸馏结果写入 pending_assets（人工闸门前一律 pending）。"""
        proposed = []
        for p in distilled.get("principles", []):
            if isinstance(p, str) and p.strip():
                pid = add_pending("principle", p.strip(), source_ids)
                proposed.append({"id": pid, "kind": "principle", "content": p.strip()})
        for c in distilled.get("cases", []):
            if isinstance(c, dict) and c.get("title"):
                if not c.get("id"):
                    c["id"] = "NEW" + str(abs(hash(c.get("title", ""))) % 100000)
                pid = add_pending("case", c, source_ids)
                proposed.append({"id": pid, "kind": "case", "content": c.get("title")})
        return proposed

    def run_evolve(self, model="glm-4-9b-chat", base_url=None, batch_limit=20):
        """
        触发一轮 EvolveR 闭环：
          取未反思经验 → 优先挑有纠正/低评分 → 离线自蒸馏 → 提案入 pending → 标记已反思。
        返回结构化摘要（含当前 pending 列表，供前端展示人工审核）。
        """
        exps = list_experiences(limit=batch_limit, reflected=0)
        priority = [
            e for e in exps
            if (e.get("human_correction")
                 or (e.get("human_rating") is not None and e["human_rating"] <= self.low_rating_threshold))
        ]
        rest = [e for e in exps if e not in priority]
        to_process = priority + rest
        if not to_process:
            return {"evolved": False, "reason": "暂无可蒸馏经验（请先对结果评分/写纠正）",
                    "pending": list_pending()}
        distilled = self._distill(to_process, model, base_url)
        if not distilled.get("ok"):
            return {"evolved": False, "reason": distilled.get("reason"), "pending": list_pending()}
        src_ids = [e["id"] for e in to_process]
        proposed = self._propose(distilled, src_ids)
        mark_reflected(src_ids)
        return {
            "evolved": True,
            "processed": len(to_process),
            "principles": len(distilled.get("principles", [])),
            "cases": len(distilled.get("cases", [])),
            "proposed": proposed,
            "pending": list_pending(),
        }

    # ---------- 策略更新落地（原则注入 prompt / 案例并入匹配） ----------

    def get_active_principles_text(self):
        """返回生效原则文本（追加进 system prompt 附录）。无则空串。"""
        try:
            ps = active_principles()
        except Exception:
            return ""
        if not ps:
            return ""
        lines = ["\n\n【历史经验原则（经人工审核生效，须优先遵循）】"]
        for i, p in enumerate(ps, 1):
            lines.append("%d. %s" % (i, p["text"]))
        return "\n".join(lines)

    def get_all_cases(self, seed_cases_loader=None):
        """种子案例（领域自带，可选）+ 自增长案例（经人工批准）。供案例匹配器使用。"""
        seed = []
        if callable(seed_cases_loader):
            try:
                seed = seed_cases_loader()
            except Exception:
                seed = []
        try:
            custom = active_custom_cases()
        except Exception:
            custom = []
        return seed + custom

    # ---------- 闸门工具（供 HTTP 层直接暴露） ----------

    def list_pending(self):
        return list_pending()

    def list_active_principles(self):
        """已生效原则（供面板 / 调试展示）。"""
        return active_principles()

    def approve(self, pid):
        return approve_asset(pid)

    def reject(self, pid):
        return reject_asset(pid)

    def list_experiences(self, limit=50, reflected=None):
        return list_experiences(limit=limit, reflected=reflected)


if __name__ == "__main__":
    si = SelfImprove(domain_name="合同审查")
    print("SelfImprove 自检：", si.domain_name)
    print("无经验时 run_evolve ->", si.run_evolve())
