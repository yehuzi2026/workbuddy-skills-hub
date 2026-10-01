---
name: insurance-claim-agent
description: 垂直行业 AI Agent MVP 模板（保险理赔/核保自动化方向），含「自我净化/自进化」人工在环闭环。当需要「做垂直 AI Agent / 车险物损初审 / 定损照片 OCR / 历史案例匹配 / 让 Agent 越用越聪明（经验沉淀+蒸馏+人工闸门）/ 把某个无聊 B2B 工作流做成 Web 工具」时加载。复用范式：SCNet 云端 API 推理 + 本地 RapidOCR 离线识别 + 历史案例语义检索 + 经验库 SQLite + 方案1人工在环 + EvolveR 蒸馏 + FastAPI 发布为 Web 应用。可复制改 prompt/cases.json 适配任意垂直（车辆/合同审查/工单分派等）。
---

# 保险理赔 / 核保自动化 Agent（垂直 AI Agent MVP 模板 · 含自我净化）

把"某个行业的无聊高价值工作流"做成可对外发布的 Web 工具的可复用骨架。当前内置**保险理赔/核保**垂直，
但真正价值在于**范式可复制**——换一个垂直只需改 prompt 与案例库。v0.3 起**内置自我净化能力**：
Agent 会"越用越聪明"，但只在你（人工）批准的前提下。

## 何时用
- 用户要做「垂直行业 AI Agent / 投标作战系统 / 合同审查 / 工单分派 / 车辆估价」等具体行业的 Web 工具
- 用户有 SCNet / 任意 OpenAI 兼容推理端点，想零 GPU 实例成本发布 Web 应用
- 需要「定损照片 OCR」「历史案例/知识库匹配」「经验自我沉淀」这类"动作型"能力而非纯聊天
- 用户问"这东西会不会越用越聪明 / 能不能自我进化 / 加反思净化能力"

## 核心能力（已验证可运行）
1. **结构化分析**：调 SCNet 云端 API（GLM-4 / DeepSeek，OpenAI 兼容），输出定损建议/材料完整性/
   拒赔风险/责任比例/欺诈评分/核保建议 的 JSON。
2. **定损照片 OCR**：`ocr_utils.py` 优先本地 RapidOCR 离线识别（**满足 SCNet 容器内网出网限制**，不连外网），
   未装时降级；可选智谱 GLM-4V 云端兜底（需外网+ZHIPU_API_KEY）。
3. **历史案例匹配**：`cases.py` 用 SCNet 文本模型做语义检索返回 top_k 相似案例，无 Key 时本地关键词兜底。
   自增长案例（经人工批准）自动并入匹配库。
4. **自我净化 / 自进化（v0.3）**：复用通用范式 skill **`agent-self-improve`** 的 `SelfImprove` 类
   （本目录已复制其通用 `memory_store.py` / `evolver.py` / `llm_client.py`，与通用 core 保持同步），
   融合 **方案1 人工在环闭环** 与 **EvolveR（ICML2026）经验驱动闭环**：
   - 在线交互捕获（每次 analyze 记录经验）→ 人工反馈（评分/纠正，作蒸馏锚点）→
     离线自蒸馏（调模型提炼"通用原则"+"新案例"）→ 进入**待审区** → **人工批准才生效**（原则注入 prompt、案例并入匹配）。
   - 领域参数（domain_name/domain_hint/case_schema_hint）集中在 `app.py` 实例化 `SelfImprove` 处，便于改垂直。
   - 安全红线：自动产出必过人工闸门，绝不静默生效；不改模型权重/不自动改代码（规避 reward hacking）。
5. **Web 发布**：`app.py` FastAPI，前端含反馈表单 + 自我净化管理面板。

## 目录结构
```
insurance-claim-agent/
├── app.py              # FastAPI 后端 + 路由 + OCR/案例编排 + 自我净化端点（领域参数在此实例化 SelfImprove）
├── claim_analyzer.py  # SCNet API 调用 + 结构化分析 prompt + 经验原则注入（核心）
├── ocr_utils.py        # 定损照片 OCR（本地 RapidOCR 优先）
├── cases.py            # 历史案例匹配（SCNet 语义检索 + 本地兜底 + 自增长案例合并）
├── cases.json          # 历史案例库（示例 24 条，覆盖 22 类事故形态）
├── memory_store.py     # 通用经验库（复制自 agent-self-improve/core，SQLite：经验/待审闸门/生效原则/自增长案例）
├── evolver.py          # 通用 SelfImprove 类（复制自 agent-self-improve/core，方案1+EvolveR）
├── llm_client.py       # 通用零依赖 OpenAI 兼容客户端（复制自 agent-self-improve/core）
├── templates/index.html# 前端：表单 + 照片上传 + 结果卡片 + 反馈 + 自我净化面板
├── sample_claim.json   # 示例输入
├── requirements.txt    # fastapi + uvicorn + rapidocr-onnxruntime
├── experience.db       # 运行时生成的经验库（可删，重新积累）
└── README.md
```

## 自我净化闭环怎么跑（用户视角）
1. 正常用 `/api/analyze` 分析 → 自动记录为"在线交互"（经验库 experiences 表）。
2. 对结果评分 / 写纠正意见 → `/api/feedback`（**只有带纠正或低评分≤2 的经验才参与蒸馏**，防模型自说自话）。
3. 点"运行一轮蒸馏" → `/api/evolve` 调模型从纠正记录提炼原则+新案例，写入**待审区**。
4. 在"自我净化面板"点**批准生效** → 原则注入 prompt 附录、案例并入匹配库。**绝不在不知情时改写判断**。
5. 被蒸馏经验打 reflected 标记，避免重复蒸馏；案例库在种子 cases.json 之外独立存 custom_cases，不污染原始库。

## 复用步骤（换一个垂直）
1. **改 prompt**：编辑 `claim_analyzer.py` 的 `SYSTEM_PROMPT` 与 `_build_user_prompt` 字段，换成目标行业。
2. **换案例库**：用目标行业的案例重写 `cases.json`（字段：id/title/accident_type/.../estimated_loss/conclusion）。
3. **调字段**：`app.py` 的 `_FIELDS` 与前端 `index.html` 的 textarea 对应业务字段。
4. **部署**：同下。

## 部署
- **本地**：`pip install -r requirements.txt` → `.env` 填 `SCNET_API_KEY` → `uvicorn app:app --port 8000`。
- **SCNet Web 应用**：上传目录 → 启动命令 `uvicorn app:app --host 0.0.0.0 --port 8000` →
  设 `SCNET_API_KEY` 环境变量 → 端口 8000 → 拿到 `scnet.cn` 常驻链接。
  ⚠️ 容器出网只能调平台内 API（`api.scnet.cn`）；本应用后端仅调模型服务且 OCR 走本地，正好满足。
- **切私有化**：A800 库存恢复后，把 `claim_analyzer.py` 的 `base_url` 改为本地 vLLM 地址，代码零改动。

## 关键约束
- API Key 只走环境变量 / SCNet 密钥管理，不写代码、不进聊天。
- 这是**初审辅助**，最终以人工/条款为准。
- 真实客户数据建议内网/私有化处理（云端调用会经平台模型服务）。
- 自我净化的"反思"必须有外部信号 grounding（人工纠正/低评分），且产出须经人工批准才生效。

## 已验证
py_compile 通过；经验库读写/批准/原则注入/案例并入全流程通过；空表单 400、首页 200、`/api/cases` 返回案例、
OCR 无引擎降级不崩、无 Key 时案例本地兜底、各进化端点无 Key 正确拦截（400/404）。
（真实模型调用需有效 `SCNET_API_KEY` + 网络，沙箱无法实跑。）
