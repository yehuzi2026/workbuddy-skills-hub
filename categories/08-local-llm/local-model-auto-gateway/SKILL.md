---
name: local-model-auto-gateway
description: 本机 Ollama 多模型「自动选模型 + Laya 决策兜底」统一网关（AUTO 入口）。当用户要「调用 AUTO / 自动挑最合适的本地模型 / 本地大模型统一入口 / 工单自动分类不手动指定模型」时使用。核心原则：轻量模型优先，只有大文本/多诉求/需推理时才动用 deepseek-r1:7b；图片走视觉模型；模型挂了逐级降级，最终 Laya 兜底不崩。
agent_created: true
---

# 本地大模型自动路由网关（AUTO）

## 定位
用户只丢「文本 / 图片」，**不指定模型**；网关自动判断任务类型 → 自动挑最合适的本地模型 →
抽字段 → Laya 判结论。模型挂了逐级降级，最终 Laya 兜底，**永不崩**。
这不是「提高电脑性能」的工具，是**任务路由 / 省 token / 省电的效率编排层**。

**核心原则（用户 2026-09-30 明确）：轻量模型优先。**
平时一律用轻模型（快、省电、能进显存）；**只有大文本 / 多诉求 / 需推理**、
其他模型吃得吃力时，才动用 `deepseek-r1:7b`；而 `deepseek-r1:7b` 这条路必须有 Laya 兜底、绝不崩。
⚠️ 不要把 AUTO 简化/退化成一个固定模型——模型池要保留，靠自动选档调度。

## 何时用
- 用户说「调用 AUTO」「自动用最合适的模型」「本地模型统一入口」
- 需要把本地多个 Ollama 模型按任务自动调度，而不是手动切
- 车拍拍 / 物损系统的工单分派、报案初筛、动作门控等「固定答案空间」分类

## 实现文件（参考实现，放在工作区）
- `laya_orchestrator.py`：核心。含自动选档引擎 + 五模式(route/pipeline/score/fallback/auto) + `--serve` 常驻 HTTP :8787
- `auto.bat`：一键入口（清代理 → 起 Ollama → 起常驻服务）

## 自动选档策略（核心知识）
复杂度 `estimate_complexity(text)`：中文按 1 计权、其他按 0.3 得 eff_len；
再加 疑问数×0.5 + 关键词(投诉/赔偿/评估/请判断/分析…)×1.0 + 换行×0.2 = score。

| 档位 | 判定条件 | 首选模型 | 理由 |
|---|---|---|---|
| image | 请求带图片 | `qwen3-vl:4b` | 视觉（deepseek-r1 看不了图） |
| complex | score ≥ 2.5（大文本/多诉求，如 98 字的投诉+退款+评估诉求） | `deepseek-r1:7b` | **其他模型吃力时才上**，推理强 |
| simple | 其余 | `qwen3.5:4b` | 快、能进 4G 显存 |
| trivial | eff_len ≤ 12 且无关键词/疑问 | `deepseek-r1:1.5b` | 秒回 |

阈值可用环境变量 `AUTO_COMPLEX_THRESHOLD` 覆盖（默认 2.5）。

每档给**多个备选**（`MODEL_TIERS`），按序取本机第一个可用。
**降级链**：选中模型 → 同档备选 → 任意可用模型 → 全挂则 `Laya-only` 兜底。
会话内用 `_DEAD` 集合标记挂掉的模型，避免反复重试。
用户可 `--model` 手动覆盖自动选择。

## 提升准确率：冻结编码器 + 训练决策头（轻量微调）
Laya 零样本在短/歧义文本上≈瞎猜（置信 0.19–0.27）。官方全量微调需 **2×T4 GPU / 4-5h**（Kaggle notebook），
4GB 显存机型跑不了。可行路线：**冻结 Laya 编码器，只训练一个线性决策头**（生态 stuntd 同款）。
- 取嵌入：`from laya.shortlist import embed_fn_from_agent` → `ef=embed_fn_from_agent(agent,max_length=256)`
  → `ef(list[str]) -> np.ndarray(n,768)`（mean-pool，不跑决策头、不下载新权重）
- 训练器：`laya_train_head.py`（纯 numpy 逻辑回归 + 标准化 + Adam + 5折CV + 温度标定；**零外部依赖**，
  别用 sklearn——依赖树重、慢网拉不动）。产出 `models/head_<task>.pkl`。
- **必须只存纯 numpy 数组**（mu/sd/W/b/temperature/classes），**不要 pickle 类实例**：
  类若定义在训练脚本 `__main__`，加载端找不到类会静默失败。
- **温度标定**：线性头原始 softmax 常出 1.0（过度自信），网格搜索 NLL 最小拟合 T。
- 集成：`head_decide()` 用 `criteria` 与头标签集一致才启用，否则退回 Laya；`--mode head`。常驻后响应 ~0.1s。
- **决策优先级（mode_auto，用户 2026-09-30 拍板）**：
  - **大文本(complex) / 图片 / 手动指定 → 直接走「模型抽字段 → Laya 判」**；
    大文本强制 `deepseek-r1:7b`，**不先过决策头**（用户明确要求）
  - 其余文本 → **训练头 > 模型抽字段+Laya判 > Laya零样本**
  - 诊断：`--plan` 会返回 `decider`(trained_head / 模型→Laya)、`will_call_model`、`tier`
- ⚠️ 数据是瓶颈：种子数据（合成）上 5折CV 约 0.72→0.78(+6%)，提升有限；
  **要真提升必须用真实业务工单**（文本+正确标签对）替换种子数据重训。

## 关键坑（都踩过）
1. **本机注册表代理**：Windows 上 `urllib` 会从**注册表**读代理（不只环境变量），
   导致访问 `127.0.0.1:8787` 返回 `501 Unsupported method`。
   客户端必须用 `urllib.request.build_opener(urllib.request.ProxyHandler({}))` 显式禁用代理；
   服务端启动前清 `HTTP_PROXY/HTTPS_PROXY`（否则 huggingface_hub 拉权重 502）。
2. **SO_REUSEADDR 双服务**：`http.server.HTTPServer` 默认 `allow_reuse_address=True`，
   旧 serve 没杀干净时会与新 serve **同时绑 8787**，请求随机落到旧代码 → 行为诡异。
   重启前必须 `Get-CimInstance Win32_Process | Where CommandLine -like "*laya_orchestrator*"`
   全部杀掉，并 `Get-NetTCPConnection -LocalPort 8787 -State Listen` 确认端口释放。
3. **中文阈值**：字符数阈值对中文失效（100 字中文即长文本）；用「有效字数 + 信号」双条件判「极短」。
4. **冷启动**：首次 Laya 加载 + 模型加载约 90s；`--serve` 常驻预热后请求毫秒级。
   走 7B 的大文本任务本身是分钟级（实测 134s，其中 7B 加载约 40s）——Ollama 请求已带
   `keep_alive`（env `AUTO_KEEP_ALIVE`，默认 `30m`），7B 加载一次后驻留 30 分钟，后续调用不再重加载。
5. **Laya 零样本弱**：短/歧义文本置信度常 <0.3 且可能判错；**机制通 ≠ 结论准**，
   要结论靠谱需用业务历史数据微调 Laya。诊断用 `--plan`（只选模型不跑，秒回）。

## 验证步骤
```bash
PY=/c/Users/AHS/.workbuddy/binaries/python/envs/laya/Scripts/python.exe   # Laya venv
$PY laya_orchestrator.py --models                 # 列本机模型 + 档位偏好
$PY laya_orchestrator.py --plan "文本"             # 看会选哪个模型(秒回)
$PY laya_orchestrator.py --mode auto "文本"        # 真实端到端
```
HTTP（客户端务必禁代理）：
```python
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# POST {"text":"...","mode":"auto"}  或 {"text":"...","image":"<base64>"}
# POST {"text":"...","plan":true}   只看选哪个模型
```

## 环境速查
- Laya venv：`C:\Users\AHS\.workbuddy\binaries\python\envs\laya`（laya 0.3.22 + torch）
- 本机 4GB 显存：4B 级模型能进显存流畅；7B(4.7GB) 溢出到内存变慢（复杂任务可接受）
- 常驻服务：`http://127.0.0.1:8787`

---

## ⚠️ 实战补充：WorkBuddy 真正在用的网关是 8090（2026-09-30 实测）

**本机有两套都叫 "auto" 的东西，别搞混：**

| 入口 | 脚本 | 端口 | 定位 |
|---|---|---|---|
| WorkBuddy 自定义模型 `custom-local:auto`（**生产在用**） | `.ollama-gw\ollama-local\local-model-gateway.py` | **8090** | 纯多模型路由，用 llama.cpp `llama-cuda\llama-server.exe` 按模型分端口 8181-8186，**完全不走 Ollama** |
| Laya 决策实验（本技能主体） | 工作区 `laya_orchestrator.py` | 8787 | 7B 抽字段 + Laya 判 |

WorkBuddy 设置里「自定义模型」的 base_url = `http://127.0.0.1:8090/v1/chat/completions`，模型名 `auto`。

**坑：超上下文报错 `exceed_context_size_error`（已修）**
- 症状：WorkBuddy 发**图片**或长对话 → 400 `request (N tokens) exceeds the available context size (8192)`
- 根因：`local-model-gateway.py` 的 `Router.classify()` 判定「图片 + 命中 OCR 关键词（识别/提取/抽取/表格/票据/发票/盖章/图中文字…）」
  → 路由到 `image_ocr` = `deepseek-ocr-3b`；而该模型**训练上下文只有 8192**，配置里写 16384 也会被
  llama.cpp 强制 cap（日志 `exceeds the training context of the model (8192) - capping`）。
  WorkBuddy 的 system prompt 恒定上万 token（全量 memory + 几十个 skill + identity）→ **每次必爆**
- **修复方案（已落地）**：
  1. `classify()` 加**上下文守卫**：命中取字意图时先估算请求规模
     `est = sum(msg_tokens(m) for m in msgs)`；若 `est > ocr_ctx - 512` 就降级为 `image`（走 `qwen3-vl-4b`，ctx=16384）。
     这样**短取字请求仍用高精度 OCR 模型，长请求自动降级**（两全）
  2. `models.json` 把 `deepseek-ocr-3b.ctx` 从 16384 改成 **8192**（如实反映硬上限，否则守卫按 16384 会漏判）
- 备份：`local-model-gateway.py.bak-20260930-ctxguard` / `models.json.bak-20260930-ctxguard`
- 回归自检：`自检-上下文守卫.py`（`import` 网关模块直调 `classify()`，不加载模型、秒回）
- 重启网关：`python 重启网关.py`（内部用 WMI **脱离 WorkBuddy 进程树**，否则网关会被父 job 连带杀掉）
- ⚠️ 用 Ollama 的 `Modelfile PARAMETER num_ctx` 建 32K tag **对这网关无效**（它直接读 `~\.ollama\models\blobs` 的
  GGUF + llama-server，不经 Ollama 运行时）——别走弯路
- 遗留：对话若继续变长超过 `qwen3-vl-4b` 的 16384 仍会报错 → 届时把 vl-4b 的 ctx 提到 24576/32768
  （4GB 显存有 KV 缓存溢出风险，需实测；可用 `free-vram.ps1` / `立即释放显存.cmd` 配合）
