---
name: agent-self-improve
description: 领域无关的可复用「自我进化 / 自净化」范式层。当需要「让任意 AI Agent 越用越聪明 / 加反思净化能力 / 人工在环学习闭环 / 经验沉淀蒸馏 / 历史案例自增长」时加载。与垂直领域彻底解耦——合同审查、工单分派、理赔初审、投标作战等任何 Agent 只需把 core/ 复制到项目并传一个领域参数即可获得：经验库 SQLite + 方案1 人工在环闸门 + EvolveR(ICML2026) 离线自蒸馏 + 原则注入 prompt + 自增长案例并入匹配。安全红线：自动产出必过人工 approve 才生效、绝不静默改写判断、不改模型权重/代码。
---

# agent-self-improve —— 通用「自我进化 / 自净化」范式层

把"某个行业的无聊高价值工作流"做成**会越用越聪明**的 Agent 的可复用骨架。与垂直领域**彻底解耦**：
核心引擎不含任何领域词，调用方只传一个领域参数即可套用。适合作为**所有垂直 Agent 的标配插件**——
合同审查、工单分派、理赔初审、投标作战、客服分派……都直接加进去。

## 何时用
- 用户要做「垂直 AI Agent」且希望它"越用越聪明 / 自我进化 / 有记忆"。
- 用户问"能不能加反思净化 / 人工在环学习 / 经验沉淀蒸馏"。
- 任何已有 Agent 想要「历史案例自增长」「原则随人工纠正自动沉淀」能力。

## 设计思想（双范式融合）
A. **方案1 —— 安全人工在环学习闭环**：经验沉淀 → 反思净化（人工纠正为锚点）→ 案例自增长 → 原则蒸馏 → 验证闸门/人工审阅。
B. **EvolveR（ICML 2026）—— 经验驱动闭环**：在线交互 → 离线自蒸馏 → 经验库维护 → 策略更新。
   我们把"生效原则注入 prompt"视作轻量策略更新，且全程置于人工闸门之后（规避 reward hacking / 自动漂移）。

## 安全红线（任何集成方都必须遵守）
- 自动产出（原则 / 案例）先入 `pending_assets`，`status='pending'`。
- **必须人工 approve 后才进入生效区**（principles.active / custom_cases.active）。绝不在不知情时改写判断。
- 蒸馏的"反思"必须有外部信号 grounding：人工评分 ≤阈值 或人工纠正意见，避免模型自说自话。
- 不修改种子案例库；自增长案例独立存表。不改模型权重、不自动改代码。

## 目录
```
agent-self-improve/
├── SKILL.md
├── core/                      # ← 通用、领域无关，复制进任意 Agent 项目即可
│   ├── memory_store.py        # SQLite 经验库：experiences/pending/principles/custom_cases
│   ├── llm_client.py          # 零依赖 OpenAI 兼容客户端（urllib，适配 SCNet/vLLM/OpenAI）
│   └── evolver.py             # SelfImprove 类：捕获/反馈/蒸馏/闸门/注入
└── references/
    └── integration_guide.md   # 集成蓝图：FastAPI 端点 + 前端面板片段 + 领域参数示例
```

## 集成契约（三步套用任意 Agent）
1. 把 `core/` 目录整体复制到你的 Agent 项目（保持 `core/` 在同目录，或用 `sys.path` 注入）。
2. 实例化领域参数：
   ```python
   from core.evolver import SelfImprove
   SI = SelfImprove(
       domain_name="合同审查",
       domain_hint="你是一名资深合同审查律师，关注权责失衡、违约条款、付款条件。",
       case_schema_hint='案例字段：id/title/contract_type/risk_point/severity/conclusion',
       field_label="合同",
   )
   ```
3. 挂接四个动作（详见 `references/integration_guide.md`）：
   - **主任务后**：`eid = SI.capture_online(task_input, task_output)`
   - **生成 prompt 时**：`system_prompt += SI.get_active_principles_text()`；案例匹配用 `SI.get_all_cases(seed_loader)`
   - **人工反馈**：`SI.feedback(eid, rating=..., correction=...)`
   - **蒸馏 + 闸门**：`SI.run_evolve(model, base_url)` → 前端展示 `SI.list_pending()` → 人工点 `SI.approve(pid)` / `SI.reject(pid)`

## 依赖与运行
- `core/` 仅用 Python 标准库（sqlite3 / json / urllib），**零三方依赖**，任何环境可直接跑。
- API Key / base_url 走环境变量：`SELF_IMPROVE_API_KEY` / `OPENAI_API_KEY` / `SCNET_API_KEY`，`SELF_IMPROVE_BASE_URL`。
- 经验库路径：`SELF_IMPROVE_DB`（默认 `agent_self_improve.db`）。

## 已验证
py_compile 通过；经验库读写 / run_evolve 无 Key 正确拦截 / 原则注入 / 案例合并 / approve-reject 全流程通过（mock 模型调用）。
真实蒸馏需有效 API Key + 网络。

## 已落地案例
`insurance-claim-agent` skill 已通过本范式复用（见其 SKILL.md「自我进化」段落），证明跨领域可复制。
