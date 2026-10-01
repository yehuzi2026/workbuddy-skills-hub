# agent-self-improve · 集成指南

把"自我进化/自净化"塞进**任意**垂直 Agent 的标准做法。核心保证：领域无关，接四个动作即可。

---

## 0. 准备
把 `core/` 整体复制到你的 Agent 项目根目录（与你的 `app.py` / 主逻辑同层）：
```
your_agent_project/
├── core/                # 复制自 agent-self-improve/core/
│   ├── memory_store.py
│   ├── llm_client.py
│   └── evolver.py
├── app.py               # 你的 FastAPI 后端
└── ...（你的领域代码）
```
> 若 `core` 不在同目录，启动前 `sys.path.insert(0, "/path/to/core")` 即可。

---

## 1. 实例化（领域参数集中一处）
在 `app.py` 顶部：
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))
from evolver import SelfImprove

SI = SelfImprove(
    domain_name="合同审查",                       # 出现在 distill 提示里
    domain_hint="你是一名资深合同审查律师，关注权责失衡、违约条款、付款条件、合规风险。",
    case_schema_hint='案例字段：id/title/contract_type/risk_point/severity/conclusion',
    field_label="合同",                           # 用于 principles 描述（"合同法判责原则"）
    low_rating_threshold=2,                       # 评分≤2 视为低分，参 distillation
)
```
**不同领域只改这一段**（示例）：
- 工单分派：
  ```python
  SI = SelfImprove(
      domain_name="工单分派",
      domain_hint="你是一名工单调度专家，关注 SLA、技能匹配、负载均衡。",
      case_schema_hint='案例字段：id/title/biz_type/urgency/owner_team/route_reason/conclusion',
      field_label="工单",
  )
  ```
- 理赔初审：
  ```python
  SI = SelfImprove(
      domain_name="车险理赔初审",
      domain_hint="你是一名车险定损核赔专家，关注事故责任、定损合理性、拒赔风险、欺诈评分。",
      case_schema_hint='案例字段：id/title/accident_type/vehicle_info/damage_desc/liability/estimated_loss/reject_risk/conclusion',
      field_label="理赔",
  )
  ```

---

## 2. 主任务后捕获（在线交互）
```python
# 你的主分析函数里，生成结果后：
eid = SI.capture_online(task_input, task_output)   # task_input/output 任意可 JSON 序列化对象
# 把 eid 随结果返回前端，供后续反馈关联
```

## 3. 生成 prompt 时注入（策略更新落地）
```python
SYSTEM_PROMPT = "你是……专家。" + SI.get_active_principles_text()   # 生效原则自动追加
# 案例匹配（如有）：
all_cases = SI.get_all_cases(seed_cases_loader=load_seed_cases)     # 种子+自增长
```

---

## 4. FastAPI 端点蓝图（直接照抄）
```python
from fastapi import FastAPI, HTTPException
app = FastAPI()

@app.post("/api/analyze")
def analyze(req: dict):
    # ...你的领域分析...
    out = your_domain_analyze(req)
    eid = SI.capture_online(req, out)
    return {"eid": eid, **out}

@app.post("/api/feedback")
def feedback(req: dict):
    eid = req.get("eid")
    if not eid:
        raise HTTPException(400, "missing eid")
    SI.feedback(eid, rating=req.get("rating"), correction=req.get("correction"))
    return {"ok": True}

@app.post("/api/evolve")
def evolve(req: dict):
    # 引擎在无 Key / 无经验 / LLM 出错时统一返回 evolved=False + reason，不会静默成功
    return SI.run_evolve(
        model=req.get("model", "glm-4-9b-chat"),
        base_url=req.get("base_url"),   # None 时取环境变量
    )

@app.get("/api/pending")
def pending():
    return SI.list_pending()

@app.post("/api/approve")
def approve(req: dict):
    if not SI.approve(req.get("pid")):
        raise HTTPException(404, "pending asset not found")
    return {"ok": True}

@app.post("/api/reject")
def reject(req: dict):
    SI.reject(req.get("pid"))
    return {"ok": True}

@app.get("/api/principles")
def principles():
    return {"principles": SI.list_active_principles()}   # 已生效原则（已批准才出现）
```

---

## 5. 前端面板片段（自我净化管理面板）
任一 Agent 前端加一块"自我净化"区，结构如下（原生 HTML，可改 Vue/React）：
```html
<section id="self-improve">
  <h3>自我净化 · 人工在环</h3>
  <button onclick="runEvolve()">运行一轮蒸馏</button>
  <div id="pending-list"></div>
</section>
<script>
async function runEvolve() {
  const r = await fetch('/api/evolve', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
  const data = await r.json();
  if (!data.evolved) { alert('未蒸馏：' + data.reason); return; }
  renderPending(data.pending);
}
async function renderPending(list) {
  const box = document.getElementById('pending-list');
  box.innerHTML = list.map(p => `
    <div class="asset">
      <span>[${p.kind}]</span> ${p.content}
      <button onclick="act(${p.id},'approve')">批准生效</button>
      <button onclick="act(${p.id},'reject')">驳回</button>
    </div>`).join('') || '暂无可审资产';
}
async function act(pid, op) {
  await fetch('/api/' + op, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({pid})});
  runEvolve();
}
</script>
```
反馈表单：每条分析结果下方放「评分(1-5) + 纠正意见」输入框，提交到 `/api/feedback`，带 `eid`。

---

## 6. 安全校验清单（上线前自检）
- [ ] 经验库读写正常，`agent_self_improve.db` 生成。
- [ ] 无 API Key 时 `/api/evolve` 返回 `{"evolved": false, "reason": "llm error: 未提供 api_key..."}`（前端据此 alert，**不应静默成功**）。
- [ ] `run_evolve` 在无纠正/无低分经验时返回 "暂无可蒸馏经验"，不臆造原则。
- [ ] 待审资产必须经 `approve` 才出现在 `get_active_principles_text()` / `get_all_cases()` 生效区。
- [ ] `reject` 后该资产不再出现于 pending，且不进入生效区。
- [ ] API Key 只走环境变量，不写代码、不进聊天。

---

## 7. 跨领域复用经验
本范式已在两个真实垂直 Agent 实战落地，证明「复制 core + 改领域参数 + 接端点」即可通用：
- `insurance-claim-agent`（车险理赔初审，Web MVP）
- `contract-review-agent`（合同风险审查，Web MVP）

任何新 Agent 只需：复制 `core/` + 改第 1 步领域参数 + 接第 4 步端点。
不要为每个垂直重写经验库/蒸馏逻辑——那会重新引入漂移与重复维护成本。

### 7.1 如何接入「文档驱动型」skill（如小羊羊标书废标审查）
小羊羊废标审查等 skill 以 SKILL.md 流程为核心、无独立 Python 工程，接入方式略有不同：
1. 在 skill 目录内新建 `self_improve/` 并复制 `core/`（memory_store/llm_client/evolver）。
2. 写一个小脚本 `capture.py`：在「审查结论产出后」调用
   `SelfImprove(domain_name="投标废标审查", domain_hint=..., case_schema_hint=...).capture_online(招标文件片段, 审查结论)`，
   把 `eid` 打印/回写进审查报告。
3. 另写 `evolve_cli.py`：跑 `run_evolve` → 打印待审资产 → 人工确认后 `approve(pid)`。
4. 在 SKILL.md 的「审查结论」步骤后追加一句：「结论产出后执行 `python capture.py` 记录经验；
   周期性跑 `python evolve_cli.py` 蒸馏并经人工批准，新原则将注入后续审查」。
   安全红线不变：自动产出必须人工批准才生效。
