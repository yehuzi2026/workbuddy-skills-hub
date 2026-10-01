---
name: scnet-llama-deploy
version: 1.0.0
agent_created: true
description: SCNet（国家超算互联网平台）A800 实例私有化部署 Llama-3-70B / 大模型，提供 vLLM OpenAI 兼容 API 用于投标文件解析（招标文件提取/废标审查/技术方案）。含 Notebook 创建、模型库克隆权重、vLLM 启动、标书解析验证脚本。
triggers:
  - SCNet
  - 国家超算互联网
  - 超算部署
  - A800
  - Llama-3-70B
  - 私有化部署
  - vLLM
  - 模型部署
  - 标书解析部署
  - 大模型本地部署
  - 超算 大模型
---

# SCNet A800 私有化部署 Llama-3-70B（vLLM）

## 何时用本技能
- 用户要在「国家超算互联网平台（scnet.cn）」上把大模型跑成私有化 API。
- 用户有 A800 / L20 / 4090 等算力，且希望标书等敏感数据不出域。
- 用户要把 SCNet 云端模型（GLM-4 / DeepSeek）或本地 Llama-70B 接进标书自动化流程。

## 核心事实（已核实，依据 SCNet 官方文档）
1. **创建实例 = 创建 Notebook**：控制台 → 快捷入口「Notebook」→ 选区域、加速卡型号、数量、开发镜像。
2. **A800 是 NVIDIA 卡**：必须选 A800 型号 + **CUDA 版 PyTorch 镜像**（如 `jupyterlab-pytorch:2.4.1-ubuntu22.04-cuda12.x-py3.10-devel`）。
   注意教程里的 `异构加速卡 AI-64GB` / `dtk25.04.1` 镜像是**华为昇腾**专用，A800 不能用。
3. **多卡并行**：4×A800 做 tensor-parallel，需 4 卡在**同一实例、同一区域**（优先选有 NVLink 的华南一区）。**抢不到 4 卡时**，可用 **1 张 A800 + 4bit AWQ 量化权重**跑（权重约 40GB），效果略降但标书解析完全可用。
4. **权重获取**：SCNet 计算节点通常**不通外网**，权重走「AI 社区 → 模型库 → 克隆至控制台」复制路径，
   **不要** `huggingface-cli download`。用户已订购的 `Meta-Llama-3-70B-Instruct 源码` 应在模型库可直接克隆。
5. **vLLM 命令**（官方教程格式）：
   ```
   python3 -m vllm.entrypoints.openai.api_server \
     --model <克隆的模型路径> --host 0.0.0.0 --port 10304 \
     --tensor-parallel-size 4 --gpu-memory-utilization 0.85 \
     --dtype bfloat16 --served-model-name Llama-3-70B-Instruct \
     --max-model-len 8192 --trust-remote-code
   ```
6. **API 协议**：OpenAI 兼容。`/v1/chat/completions`、`/v1/models`。SCNet 云端 base_url=`https://api.scnet.cn/api/llm/v1`。

## 标准流程（详细逐步骤见 references/SCNET_A800_LLAMA70B_部署指南.md）
1. 控制台创建 Notebook：区域选 A800 充足区，型号 A800，数量 **4（抢不到则选 1 卡）**，镜像选 CUDA PyTorch。
2. 进入 JupyterLab 终端。
3. AI 社区→模型库 搜 Llama-3-70b-instruct → 克隆至控制台 → 复制模型路径。
4. 跑 `deploy_llama70b.sh <模型路径> 4 10304`（4 卡全量）或 `deploy_llama70b.sh <AWQ模型路径> 1 10304 awq`（1 卡量化）。脚本会自动检测 GPU 数并在卡数不足时降级为量化模式。
5. `curl http://localhost:10304/v1/models` 验证。
6. 用 `scnet_tender_test.py --base-url http://localhost:10304/v1 --api-key EMPTY --model Llama-3-70B-Instruct --file tender_sample.md` 验证标书解析。

## 配套文件
- `deploy_llama70b.sh` — 一键启动 vLLM（含 4bit AWQ 备选、路径自检）。
- `scnet_tender_test.py` — SCNet 云端 / 本地 vLLM 通用调用脚本，提取评分标准/废标条款/技术需求并校验。
- `tender_sample.md` — 示例招标文件（酒店住宿服务采购，贴合东航技术福州项目）。
- `references/SCNET_A800_LLAMA70B_部署指南.md` — 完整 Runbook（控制台截图级步骤、收尾持久化、外部暴露）。

## 安全铁律
- SCNet 云端 API Key 只走环境变量 `SCNET_API_KEY` 或同目录 `.env`，**绝不进聊天、不截图**。
- 本地 vLLM 的 Key 随便填（脚本 `--api-key EMPTY`）。
- 共享型实例会回收：权重存对象存储 / `/root/private_data`，别只放临时盘；不用时关机避免计费。

## 显存账（快速判断）
| 配置 | 权重占用 | 适用卡 |
|---|---|---|
| 70B BF16 全量 | ~140GB | 4×A800（320GB）绰绰有余 |
| 70B 4bit AWQ | ~40GB | 单卡 A800 / L20 即可 |
| 9B / 1.5B 模型 | <20GB | 4090 / L20 |
