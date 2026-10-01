#!/usr/bin/env bash
# =============================================================
# SCNet A800 实例：私有化部署 Llama-3-70B-Instruct（vLLM）
#
# 支持两种模式，自动适配你抢到的资源：
#   A) 全量 BF16  —— 需要 4×A800（同区），效果最好
#   B) 4bit AWQ 量化 —— 只需 1 张 A800（80GB），权重约 40GB
#
# 部署后提供 OpenAI 兼容 API：http://<实例IP/localhost>:端口/v1
#
# 用法：
#   bash deploy_llama70b.sh <模型路径> [TP卡数] [端口] [量化模式]
#
# 例 1（4 卡全量）：
#   bash deploy_llama70b.sh /root/private_data/Llama-3-70b-instruct 4 10304
#
# 例 2（1 卡量化，资源不足时）：
#   bash deploy_llama70b.sh /root/private_data/Llama-3-70b-instruct-AWQ 1 10304 awq
#
# 例 3（自动模式：不传 TP，脚本按实际 GPU 数决策）：
#   bash deploy_llama70b.sh /root/private_data/Llama-3-70b-instruct
#   bash deploy_llama70b.sh /root/private_data/Llama-3-70b-instruct-AWQ "" 10304 awq
#
# 模型路径获取：
#   SCNet「AI社区→模型库」搜 Llama-3-70b-instruct（全量）
#   或 Llama-3-70B-Instruct-AWQ（量化，单卡用）→「克隆至控制台」→ 复制路径
#   ⚠️ 不要从外网 huggingface 拉（SCNet 计算节点通常不通网）。
# =============================================================
set -e

MODEL=${1:-"/root/private_data/Llama-3-70b-instruct"}
TP_IN=${2:-""}          # 留空 = 自动模式
PORT=${3:-10304}
QUANT=${4:-""}          # awq = 4bit 量化

# ---------- 自动检测可用 GPU 数量 ----------
detect_gpus() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l | tr -d ' '
  else
    echo "0"
  fi
}

GPU_COUNT=$(detect_gpus)
echo "==> 检测到 GPU 数量: $GPU_COUNT"

# ---------- 决定 TP 与是否量化 ----------
if [ -z "$TP_IN" ]; then
  # 自动模式：有 4 卡及以上且非量化 → 全量 tp=4；否则按实际卡数量化兜底
  if [ "$GPU_COUNT" -ge 4 ] && [ "$QUANT" != "awq" ]; then
    TP=4
  elif [ "$GPU_COUNT" -ge 1 ]; then
    TP=1
    if [ "$QUANT" != "awq" ]; then
      echo "    ⚠️  GPU < 4 张，自动改用 4bit AWQ 量化模式（需传入 AWQ 权重路径）。"
      QUANT="awq"
    fi
  else
    echo "    ❌ 未检测到 GPU，无法部署。"
    exit 1
  fi
else
  TP=$TP_IN
  if [ "$TP" -gt "$GPU_COUNT" ]; then
    echo "    ⚠️  请求 TP=$TP 但只有 $GPU_COUNT 张 GPU，自动降级为 TP=$GPU_COUNT"
    TP=$GPU_COUNT
  fi
  if [ "$TP" -lt 4 ] && [ "$QUANT" != "awq" ]; then
    echo "    ⚠️  TP=$TP < 4，全量 70B 显存不够，自动改用 4bit AWQ 量化（需 AWQ 权重）。"
    QUANT="awq"
  fi
fi

echo "==> 模型: $MODEL | TP=$TP | PORT=$PORT | QUANT=${QUANT:-none(全量BF16)}"

echo "==> [1/3] 确认 vLLM（SCNet CUDA 版 PyTorch 基础镜像通常已预装）"
python3 -c "import vllm; print('vLLM', vllm.__version__)" 2>/dev/null \
  || { echo "    未检测到 vLLM，尝试安装（需实例可连镜像源）"; pip install vllm; }

echo "==> [2/3] 确认权重可访问：$MODEL"
if [ ! -d "$MODEL" ]; then
  echo "    ❌ 路径不存在！请按部署指南第 2 步从『模型库』克隆并在控制台复制真实路径。"
  echo "       全量路径例: /root/private_data/Llama-3-70b-instruct"
  echo "       量化路径例: /root/private_data/Llama-3-70b-instruct-AWQ"
  echo "       不要用 huggingface-cli 从外网拉（SCNet 计算节点通常不通网）。"
  exit 1
fi

echo "==> [3/3] 启动 vLLM OpenAI 兼容服务"
if [ "$QUANT" = "awq" ]; then
  echo "    [4bit AWQ 量化模式 · 单卡即可跑 70B，权重约 40GB]"
  python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --tensor-parallel-size "$TP" \
    --quantization awq \
    --dtype auto \
    --gpu-memory-utilization 0.90 \
    --served-model-name Llama-3-70B-Instruct \
    --max-model-len 8192 \
    --trust-remote-code
else
  echo "    [全量 BF16 模式 · 需 4×A800]"
  python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --tensor-parallel-size "$TP" \
    --gpu-memory-utilization 0.85 \
    --dtype bfloat16 \
    --served-model-name Llama-3-70B-Instruct \
    --max-model-len 8192 \
    --trust-remote-code
fi

# -------------------------------------------------------------
# 启动后验证（实例内另开终端）：
#   curl http://localhost:$PORT/v1/models
#   python scnet_tender_test.py --base-url http://localhost:$PORT/v1 \
#          --api-key EMPTY --model Llama-3-70B-Instruct --file tender_sample.md
#
# 资源不足应对速查：
#   - 4 卡抢不到：用 1 张 A800 + AWQ 量化权重（模型库克隆 Llama-3-70B-Instruct-AWQ）
#   - 1 卡也抢不到：先改用 SCNet 云端 GLM-4/DeepSeek API（deploy 前先跑通云端）
# -------------------------------------------------------------
