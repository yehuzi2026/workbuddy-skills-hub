#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自我进化 · 通用 LLM 客户端（零三方依赖）
================================================================
仅用 Python 标准库（urllib）实现 OpenAI 兼容的 /chat/completions 调用。
适配任意 OpenAI 兼容端点：SCNet、vLLM、OpenAI、本地部署……

- base_url：形如 https://api.scnet.cn/api/llm/v1 （不带末尾 /chat/completions）
- api_key：优先参数 > 环境变量（SELF_IMPROVE_API_KEY / OPENAI_API_KEY / SCNET_API_KEY）
- 返回：模型输出的纯文本 content（字符串）。出错抛 RuntimeError，由调用方兜底降级。
"""
import json
import urllib.request
import urllib.error
import os


def get_api_key(preferred=None):
    """解析 API Key：参数 > 环境变量（按优先级）。"""
    if preferred:
        return preferred
    for env in ("SELF_IMPROVE_API_KEY", "OPENAI_API_KEY", "SCNET_API_KEY"):
        v = os.environ.get(env)
        if v:
            return v
    raise RuntimeError("未提供 api_key，且环境变量 SELF_IMPROVE_API_KEY / OPENAI_API_KEY / SCNET_API_KEY 均未设置")


def call_llm(messages, model="glm-4-9b-chat", base_url=None, api_key=None, timeout=120):
    """
    调用 OpenAI 兼容端点，返回助手文本。
    messages: [{"role":"system"/"user"/"assistant", "content": "..."}, ...]
    """
    if base_url is None:
        base_url = os.environ.get("SELF_IMPROVE_BASE_URL", "https://api.scnet.cn/api/llm/v1")
    base_url = base_url.rstrip("/")
    url = base_url + "/chat/completions"
    key = get_api_key(api_key)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError("LLM HTTP %s: %s" % (e.code, e.read().decode("utf-8", "ignore")[:300]))
    except urllib.error.URLError as e:
        raise RuntimeError("LLM 网络错误: %s" % e.reason)
    try:
        obj = json.loads(body)
        return obj["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise RuntimeError("LLM 返回解析失败: %s" % e)


def extract_json(text):
    """从模型文本中尽量鲁棒地抽取 JSON（容忍 ```json 围栏 / 前后废话）。"""
    if text is None:
        return None
    s = text.strip()
    # 去代码围栏
    if "```" in s:
        import re
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        if m:
            s = m.group(1).strip()
    # 截取首个 { 到末个 }
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start:end + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    print("llm_client 自检（无 Key 时应当抛错而非静默成功）：")
    try:
        print(call_llm([{"role": "user", "content": "ping"}]))
    except RuntimeError as e:
        print("  -> 预期错误：", e)
