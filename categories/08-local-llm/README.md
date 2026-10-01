# 🧠 本地大模型部署与调用 / Local LLM Deployment

> Windows 本地 GPU 部署、Ollama 多模型自动网关、超算 Llama 部署、Hermes Agent 安装接入国产大模型。

**本分类共 4 个技能。**


| 技能文件夹 | 名称 | 简介 |
| --- | --- | --- |
| `local-llm-gpu-deploy` | local-llm-gpu-deploy | 在 Windows 上把本地大模型用 NVIDIA GPU 跑起来并接入 WorkBuddy（或任何 OpenAI 兼容客户端）的完整方法论。覆盖：硬件/显存档位选型、Ollama… |
| `local-model-auto-gateway` | local-model-auto-gateway | 本机 Ollama 多模型「自动选模型 + Laya 决策兜底」统一网关（AUTO 入口）。当用户要「调用 AUTO / 自动挑最合适的本地模型 / 本地大模型统一入口 / 工单自… |
| `scnet-llama-deploy` | scnet-llama-deploy | SCNet（国家超算互联网平台）A800 实例私有化部署 Llama-3-70B / 大模型，提供 vLLM OpenAI 兼容 API 用于投标文件解析（招标文件提取/废标审查/… |
| `hermes-agent-windows-setup` | hermes-agent-windows-setup | 在 Windows 上安装并配置 NousResearch Hermes Agent（开源 Agent 运行时，github.com/NousResearch/hermes-age… |

## 安装

将本分类下对应的技能文件夹整体复制到 WorkBuddy 用户级技能目录：

```bash
# Windows
xcopy "%USERPROFILE%\.workbuddy\skills"  # 放入对应子文件夹
# 或直接把某个技能文件夹复制到 (Windows 示例):
C:\Users\<你>\.workbuddy\skills\<技能名>
```

放入后重启 WorkBuddy 即可在对话中触发。
