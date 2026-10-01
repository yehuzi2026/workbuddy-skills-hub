#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SCNet / 本地私有化 模型服务调用测试脚本
用途：验证大模型能否用于投标文件解析（评分标准 / 废标条款 / 技术需求提取）
API：OpenAI 兼容协议
  - SCNet 云端：base_url=https://api.scnet.cn/api/llm/v1 （需 SNNET_API_KEY）
  - 本地 vLLM：base_url=http://localhost:8000/v1          （Key 可随便填）

安全说明：
- API Key 优先从 --api-key 参数、其次环境变量 SNNET_API_KEY、再次同目录 .env 读取。
- 绝不硬编码、绝不打印 Key 值。

用法：
  # SCNet 云端：先查模型名（不耗 Token）
  export SNNET_API_KEY="sk-xxxx"
  python scnet_tender_test.py --list-models

  # SCNet 云端：跑示例解析
  python scnet_tender_test.py --model glm-4-9b-chat --file tender_sample.md

  # 本地私有化（A800 上 vLLM 部署的 Llama-3-70B）：复用同一脚本
  python scnet_tender_test.py --base-url http://localhost:8000/v1 \
         --api-key EMPTY --model meta-llama/Llama-3-70b-instruct --file tender_sample.md
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error

DEFAULT_BASE_URL = "https://api.scnet.cn/api/llm/v1"
DEFAULT_MODEL = "glm-4-9b-chat"   # SCNet 平台模型名以 --list-models 查到的为准

SYSTEM_PROMPT = """你是一名资深投标审查专家。请从给定的招标文件片段中，严格、准确地提取以下三类信息：
1. 评分标准：列出每一项评分维度、分值、得分规则。
2. 废标/无效投标条款：逐条列出所有会导致废标的实质性要求。
3. 技术/服务需求：列出所有实质性服务要求（含数量、规格、资质证照等）。

输出要求：
- 仅输出 JSON，不要输出任何解释性文字、不要使用 Markdown 代码块包裹。
- JSON 结构：{"评分标准":[{"维度":str,"满分":int,"规则":str}],"废标条款":[{"条款":str}],"技术需求":[{"需求":str}]}
- 所有内容必须来自原文，不得臆造、不得改写含义。原文没有的信息不要编造。"""


def get_api_key(explicit: str = None) -> str:
    key = explicit or os.environ.get("SCNET_API_KEY")
    if not key:
        # 退路：从同目录 .env 读取（避免把 Key 写进命令行/聊天）
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    if k.strip() == "SCNET_API_KEY":
                        key = v.strip().strip('"').strip("'")
                        break
    if not key:
        sys.stderr.write(
            "错误：未找到 API Key。\n"
            "方式一：--api-key sk-xxxx 或 export SNNET_API_KEY=\"...\"\n"
            "方式二：在同目录创建 .env 文件，写入一行：SCNET_API_KEY=你的key\n"
            "（本地 vLLM 部署可传 --api-key EMPTY）\n"
        )
        sys.exit(1)
    return key


def _post(base_url: str, key: str, path: str, payload: dict, timeout: int = 120) -> dict:
    url = base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"HTTP 错误 {e.code}：{body}\n")
        sys.exit(1)
    except urllib.error.URLError as e:
        sys.stderr.write(f"网络错误：{e.reason}\n")
        sys.exit(1)


def list_models(key: str, base_url: str):
    """查询可用模型列表（SCNet 不消耗 Token；本地 vLLM 也支持）"""
    req = urllib.request.Request(
        base_url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("data", data) if isinstance(data, dict) else data
        print("可用模型：")
        for m in models:
            if isinstance(m, dict):
                print(f"  - {m.get('id') or m.get('name')}")
            else:
                print(f"  - {m}")
    except Exception as e:
        sys.stderr.write(f"查询模型列表失败：{e}\n")


def chat(key: str, model: str, user_text: str, base_url: str, temperature: float = 0.1) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": temperature,
        "stream": False,
    }
    data = _post(base_url, key, "/chat/completions", payload)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        sys.stderr.write(f"响应解析失败，原始返回：{json.dumps(data, ensure_ascii=False)}\n")
        sys.exit(1)


def parse_model_output(raw: str) -> dict:
    """从模型输出中安全解析 JSON（兼容被代码块包裹的情况）"""
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:]
        txt = txt.strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return {"_raw": raw, "_parse_error": "模型输出不是合法 JSON"}


def main():
    parser = argparse.ArgumentParser(description="大模型投标文件解析测试（SCNet / 本地 vLLM 通用）")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="模型名（用 --list-models 查真实 id）")
    parser.add_argument("--file", default=None, help="招标文件片段文件路径（.md/.txt）")
    parser.add_argument("--list-models", action="store_true", help="仅列出可用模型后退出")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL（本地部署用 http://localhost:8000/v1）")
    parser.add_argument("--api-key", default=None, help="直接指定 Key（不推荐，优先环境变量/.env；本地可填 EMPTY）")
    args = parser.parse_args()

    key = get_api_key(args.api_key)
    base_url = args.base_url

    if args.list_models:
        list_models(key, base_url)
        return

    # 读取测试文本
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            sys.stderr.write(f"文件不存在：{args.file}\n")
            sys.exit(1)
    else:
        text = "（内置最小示例）某服务项目预算100万，报价超预算废标，技术分40分含服务方案20分。"

    print(f"→ 使用模型：{args.model}")
    print(f"→ Base URL：{base_url}")
    print(f"→ 输入文本长度：{len(text)} 字符")
    print("→ 调用中……\n")

    raw = chat(key, args.model, text, base_url, args.temperature)
    result = parse_model_output(raw)

    print("=" * 60)
    print("模型输出（结构化）：")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("=" * 60)

    scored = len(result.get("评分标准", []))
    voided = len(result.get("废标条款", []))
    tech = len(result.get("技术需求", []))
    print(f"\n校验：评分标准 {scored} 项 | 废标条款 {voided} 项 | 技术需求 {tech} 项")
    if scored and voided and tech:
        print("✅ 基本通过：模型能提取三类关键信息，可接入标书自动化流程。")
    else:
        print("⚠️ 部分缺失：建议换模型或调整 prompt 后重试。")


if __name__ == "__main__":
    main()
