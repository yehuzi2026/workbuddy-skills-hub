# 保险理赔 / 核保自动化 Agent（MVP v0.3 · 含自我净化）

车险物损智能初审工具：上传理赔材料（**可选定损照片**）→ 后端调 SCNet 云端模型（GLM-4 / DeepSeek）
→ 输出 **定损金额建议 / 材料完整性 / 拒赔风险 / 责任比例 / 欺诈评分 / 核保建议**，
并自动做 **定损照片 OCR 识别** 与 **历史相似案例匹配**，辅助核赔决策。

> 定位：垂直行业 AI Agent 的 MVP。后端仅用 SCNet 云端 API 推理，**不依赖 GPU 实例库存**；
> 前端用 SCNet「模型部署 → Web 应用」发布成常驻链接，零算力成本。
> OCR 采用本地 RapidOCR 离线识别，**满足 SCNet 容器内网出网限制**（不连外网）。

---

## 1. 新增能力（v0.2）

- **定损照片 OCR 识别**：上传事故现场 / 定损单照片，本地 RapidOCR 离线提取文字（车牌、损伤部位、
  维修项目、金额、单据字段），自动补充进分析材料。未装 RapidOCR 时自动降级（不阻塞）。
- **历史相似案例匹配**：从 `cases.json` 案例库检索最相似历史案件，由 SCNet 文本模型做语义检索，
  给出参考定损区间与结论，帮助核赔收窄判断。无 Key / 模型不可用时切换本地关键词兜底。

---

## 2. 自我净化 / 自进化能力（v0.3，方案1 人工在环 + EvolveR）

> 回答"这东西会不会越用越聪明"：**会，但只在你批准的前提下。** 不做自动改代码的疯狂自指，
> 而是「人工在环」的安全闭环，融合两套思想：
> - **方案1 学习闭环**：经验沉淀 → 反思净化（人工纠正为锚点）→ 案例自增长 → 经验原则蒸馏 → 验证闸门/人工审阅
> - **EvolveR（ICML 2026）经验驱动闭环**：在线交互 → 离线自蒸馏 → 经验库维护 → 策略更新（原则注入 prompt）

### 闭环怎么跑
1. **在线交互捕获**：每次 `/api/analyze` 自动把「案件材料 + AI 分析」写入经验库（`experiences` 表）。
2. **人工反馈（锚点）**：前端对分析结果评分 / 写纠正意见 → `POST /api/feedback`。**只有带纠正或低评分（≤2）的经验才参与蒸馏**，避免模型自说自话（reflection ≠ improvement 的坑）。
3. **离线自蒸馏**：`POST /api/evolve` 调 SCNet 模型，从纠正记录提炼「通用原则」与「新案例」，写入**待审区 `pending_assets`**。
4. **人工闸门**：前端「自我净化面板」列出待审资产，**你必须点「批准生效」**才进入生效区——原则注入 prompt 附录、案例并入匹配库。**绝不在你不知情时改写判断。**
5. **经验库维护**：被蒸馏过的经验打 `reflected` 标记，避免重复蒸馏；案例库在种子 `cases.json` 之外独立存 `custom_cases`，不污染原始库。

### 为什么安全
- 任何自动产出（原则/案例）先 `pending`，**必须人工 approve**。
- 不修改模型权重、不自动改代码（规避 reward hacking / 漂移）。
- 所有交互可追溯（`GET /api/experiences`）。

---

## 3. 本地运行

```bash
cd insurance-claim-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env 填入 SCNET_API_KEY=sk-xxxx
# （可选）如需云端视觉兜底 OCR：再填 ZHIPU_API_KEY=...

uvicorn app:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000
```

命令行快速验证（无需前端）：
```bash
python claim_analyzer.py --list-models                 # 确认模型名（不耗 Token）
python claim_analyzer.py --model glm-4-9b-chat --file sample_claim.json
python ocr_utils.py 定损照片.jpg                       # 测试 OCR（需装 rapidocr-onnxruntime）
python cases.py                                        # 查看案例库
```

---

## 4. 部署到 SCNet（Web 应用，对外常驻）

控制台路径：**人工智能服务 → 模型部署 → 自定义创建 → 服务方式选「Web 应用」**

1. 上传本目录（含 `app.py` / `claim_analyzer.py` / `ocr_utils.py` / `cases.py` / `cases.json` /
   `templates/` / `requirements.txt`）。
2. 启动命令：`uvicorn app:app --host 0.0.0.0 --port 8000`
3. 环境变量：`SCNET_API_KEY=sk-xxxx`（SCNet 密钥管理，不在代码里）。
4. 端口：`8000`
5. 发布：平台分配 `scnet.cn` 子域常驻链接，团队/客户可直接访问。
6. **出网限制**：容器只能访问 SCNet 平台内 API（`api.scnet.cn`）。本应用后端只调 SCNet 模型服务，
   且 OCR 走本地 RapidOCR 离线，**均不出网**，恰好满足。

---

## 5. 切换到私有化（等 A800 库存恢复后）

本地 vLLM 部署 Llama-3-70B 后，把 `claim_analyzer.py` 的 `base_url` 改成
`http://<实例IP>:10304/v1` 并传 `--api-key EMPTY` 即可，前端与逻辑零改动。

---

## 6. 目录结构

```
insurance-claim-agent/
├── app.py                 # FastAPI 后端 + 静态页路由 + 图片 OCR + 案例匹配 + 自我净化端点
├── claim_analyzer.py      # 核心：SCNet API 调用 + 结构化分析 prompt + 经验原则注入
├── ocr_utils.py           # 定损照片 OCR（本地 RapidOCR 优先 / 智谱视觉兜底）
├── cases.py               # 历史案例匹配（SCNet 语义检索 + 本地兜底 + 自增长案例合并）
├── cases.json             # 历史理赔案例库（24 条示例，覆盖 22 类事故形态）
├── memory_store.py        # 经验库（SQLite）：在线交互 / 待审资产闸门 / 生效原则 / 自增长案例
├── evolver.py             # 自进化引擎：捕获交互 → 离线蒸馏 → 提案 → 经验库维护（方案1+EvolveR）
├── templates/index.html   # 前端表单、照片上传、结果卡片、反馈表单、自我净化面板
├── sample_claim.json      # 示例理赔材料
├── requirements.txt
├── .env.example
├── experience.db          # 运行时生成的经验库（可删，重新积累）
└── README.md
```

## 7. 接口说明

核心分析：
- `GET  /`                前端页面（含反馈 + 自我净化面板）
- `POST /api/analyze`     请求体：6 个文本字段 + `image_base64`(可选) + `use_cases`(默认 true)
                          返回：`{analysis, ocr_text, ocr_engine, matched_cases, experience_id}`
- `GET  /api/models`      可用模型列表
- `GET  /api/cases`       历史案例库摘要（含自增长案例）

自我净化 / 人工在环闭环：
- `POST /api/feedback`    请求体：`{experience_id, rating(1-5), correction}` 记录人工纠正（蒸馏锚点）
- `POST /api/evolve`      触发一轮蒸馏（提炼原则+新案例）→ 进入待审区（需 SCNET_API_KEY）
- `GET  /api/pending`     列出待审资产
- `POST /api/approve`     请求体：`{id}` 人工批准某待审资产 → 生效
- `POST /api/reject`      请求体：`{id}` 人工拒绝某待审资产
- `GET  /api/principles`  列出已生效经验原则
- `GET  /api/experiences` 列出在线交互记录（审计）

## 8. 安全与合规

- API Key 只走环境变量 / SCNet 密钥管理，不写代码、不截图发聊天。
- 本工具为**初审辅助**，最终以人工核赔与条款为准；不得替代合规核赔流程。
- 理赔材料含个人隐私，建议仅在内网 / 私有化部署处理真实客户数据；SCNet 云端调用时
  材料会经平台模型服务，请评估合规要求。
