# SCNet 私有化部署 Llama-3-70B 详细 Runbook

> 目标：在「国家超算互联网平台（SCNet）」上，把 Llama-3-70B-Instruct 跑成私有化 vLLM 服务，
> 提供 OpenAI 兼容 API，用于投标文件（招标文件解析 / 废标审查 / 技术方案生成）本地化、不出域处理。
> 流程依据 SCNet 官方文档：快速开始、Notebook 快速使用、模型部署:vLLM 教程。

---

## 0. 两条部署路线（按你抢到的资源选）

| 路线 | 需要的卡 | 权重 | 效果 | 适用场景 |
|---|---|---|---|---|
| **A. 全量 BF16** | 4×A800（同区） | Llama-3-70b-instruct（~140GB） | 最好 | 资源充足时 |
| **B. 4bit AWQ 量化** | **1×A800**（80GB） | Llama-3-70B-Instruct-AWQ（~40GB） | 略降，标书解析够用 | **4 卡抢不到时（你当前情况）** |

> ⚠️ 实测：华东五区【山东】4×A800 提示「加速卡资源不足」。此时直接走**路线 B**，用 1 张 A800 + 量化权重即可部署 70B。

---

## 1. 创建 Notebook 算力实例（控制台操作）

1. 浏览器登录 https://www.scnet.cn → 右上角「控制台」。
2. 快捷入口点「**Notebook**」→ 进入创建 Notebook 页面。
3. 配置项：
   - **区域**：选 A800 资源充足的区（华东五区【山东】/ 华南一区【广东】都行；哪个能开就选哪个）。
   - **加速卡型号**：选 **NVIDIA A800**（注意：教程里的 `异构加速卡 AI-64GB` 是华为昇腾卡，A800 不能用）。
   - **加速卡数量**：
     - 能开 4 卡 → 填 **4**（路线 A）
     - 抢不到 4 卡 → 填 **1**（路线 B，量化）
   - **开发镜像**：选 **CUDA 版 PyTorch** 基础镜像，例如
     `jupyterlab-pytorch:2.4.1-ubuntu22.04-cuda12.x-py3.10-devel`
     （不要选 `dtk25.04.1`，那是昇腾专用）。
4. 点「创建」。若黄条提示「加速卡资源不足」，把数量降到 1 重试，或换区域/稍后重试。
5. 状态变为「**运行中**」后，点快捷工具列的「**JupyterLab**」进入容器终端。

> 💡 进容器后，按公告栏提示把模型/数据集放在 `/root/private_data` 路径下，避免只存临时盘。

---

## 2. 获取模型权重（关键：用模型库克隆，不要从外网拉）

SCNet 计算节点通常**不能直连互联网**，所以权重必须走平台内「模型库克隆」，不要 `huggingface-cli download`。

- **路线 A（全量）**：AI 社区 → 模型库 → 搜 `Llama-3-70b-instruct` → 「克隆至控制台」→ 复制路径。
- **路线 B（量化）**：AI 社区 → 模型库 → 搜 `Llama-3-70B-Instruct-AWQ` → 「克隆至控制台」→ 复制路径。
  （AWQ 是 4bit 量化版，单卡即可加载）

> 若模型库搜不到，回到「我的订单」里你订购的 `Meta-Llama-3-70B-Instruct 源码`，
> 看是否有「下载/克隆到控制台」入口，路径同理复制。

---

## 3. 启动 vLLM 推理服务（容器内终端执行）

`deploy_llama70b.sh` 已**自动适配**：
- 自动检测 `nvidia-smi` 可用卡数；
- 没传 TP 或卡数不足时，自动降级为 **1 卡 + 4bit AWQ 量化**（需传入 AWQ 权重路径）；
- 4 卡全量时走 BF16。

**路线 A（4 卡全量）：**
```bash
bash deploy_llama70b.sh /root/private_data/Llama-3-70b-instruct 4 10304
```

**路线 B（1 卡量化，你当前推荐）：**
```bash
bash deploy_llama70b.sh /root/private_data/Llama-3-70B-Instruct-AWQ 1 10304 awq
```

> 也可以完全不传卡数，让脚本自己判断：
> `bash deploy_llama70b.sh /root/private_data/Llama-3-70B-Instruct-AWQ "" 10304 awq`

启动成功标志：日志出现 `Application startup complete` 和 `Uvicorn running on http://0.0.0.0:10304`。

---

## 4. 验证服务可用

```bash
# 在容器内另开一个终端
curl http://localhost:10304/v1/models
# 应返回含 "Llama-3-70B-Instruct" 的 JSON
```

然后用测试脚本跑一条真实招标文件片段，验证「评分标准/废标条款/技术需求」提取：

```bash
python scnet_tender_test.py \
  --base-url http://localhost:10304/v1 \
  --api-key EMPTY \
  --model Llama-3-70B-Instruct \
  --file tender_sample.md
```

输出 JSON 且三类都提取到（脚本打 ✅），即说明 Llama-70B 已可接入标书自动化。

---

## 5. 把实例暴露给外部调用（可选）

- 默认 `0.0.0.0:10304` 只在实例内可达。
- 要从你本机/其他系统调用：在 Notebook 实例页点「**访问自定义服务**」→ 粘贴端口 `10304` → 启动任务，
  会生成一个可访问的端口链接；或绑定公网 IP / SSH 端口转发。
- **安全**：本地 vLLM 的 Key 随便填（脚本 `--api-key EMPTY` 即可）。SCNet 云端 API 的 Key 仍走
  环境变量/`.env`，**绝不进聊天、不截图**。

---

## 6. 收尾与持久化

- **共享型实例会回收**：模型权重存到 SCNet 对象存储 / `/root/private_data`，别只放临时实例盘。
- **不用时关机**：Notebook 实例「运行中」即计费，用完在实例列表点「停止/关机」。
- **下次复用**：重新启动实例 → 从第 2 步复制的模型路径直接起 vLLM（权重已克隆过，无需再克隆）。
- **量化权重更小**：路线 B 的 AWQ 权重约 40GB，比全量 140GB 更易持久化与迁移。

---

## 7. 与标书自动化的衔接

部署完成后，Llama-3-70B-Instruct 可替代 SCNet 云端 API，挂载到「小羊羊AI标书技能体系」前置：

```
招标文件 PDF → Llama-70B 本地解析（不出域）
            ↓
        提取评分标准 / 废标条款 / 技术需求
            ↓
        小羊羊AI：技术方案编写监督 → 主观分编写 → 标书排版 → 废标审查
```

调用方式统一：本项目 `scnet_tender_test.py` 只改 `--base-url` 即可在「SCNet 云端 / 本地 A800」之间切换。
