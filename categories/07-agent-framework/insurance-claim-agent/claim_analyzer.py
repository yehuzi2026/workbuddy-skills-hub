#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保险理赔 / 核保自动化 Agent —— 核心分析模块

复用 SCNet 云端 OpenAI 兼容 API（与 scnet_tender_test.py 同一调用范式）：
- Base URL: https://api.scnet.cn/api/llm/v1
- 鉴权: Authorization: Bearer <SCNET_API_KEY>
- Key 仅从环境变量 / 同目录 .env 读取，绝不硬编码、不打印

本模块只负责：组装车险物损理赔/核保的结构化分析请求，调用模型，解析 JSON。
不涉及前端、不涉及部署。
"""
import os
import sys
import json
import urllib.request
import urllib.error

# SCNet 云端推理服务（OpenAI 兼容）。本地 vLLM 部署时覆盖 --base-url 即可。
SCNET_BASE_URL = "https://api.scnet.cn/api/llm/v1"

# 默认模型清单（供前端下拉与 --list-models 参考）
KNOWN_MODELS = [
    "glm-4-9b-chat",
    "deepseek-r1-distill-qwen-1.5b",
    "DeepSeek-V4-Flash",
]


def _load_env_file(path=".env"):
    """极简 .env 解析（不引入第三方依赖）。"""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def get_api_key():
    """优先环境变量，其次同目录 .env。缺失则抛 RuntimeError。"""
    _load_env_file()
    key = os.environ.get("SCNET_API_KEY")
    if not key:
        raise RuntimeError(
            "未配置 SCNET_API_KEY。请设置环境变量，或在项目根目录创建 .env 写入：SCNET_API_KEY=sk-xxxx"
        )
    return key


def _extract_json(text):
    """从模型返回里抠出第一个完整 JSON 对象。"""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                snippet = text[start : i + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    return None
    return None


def call_llm(messages, model, base_url=SCNET_BASE_URL, api_key=None, timeout=120):
    """调用 SCNet OpenAI 兼容 /chat/completions，返回模型文本。"""
    if api_key is None:
        api_key = get_api_key()
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"SCNet API HTTP {e.code}: {detail[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"SCNet API 连接失败: {e.reason}")
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"SCNet API 返回结构异常: {e}")


SYSTEM_PROMPT = """你是一名资深车险理赔与核保专家，精通《保险法》《机动车保险条款》、定损规范与反欺诈规则。
你的任务是根据投保人提交的理赔/核保材料，输出结构化专业分析。

严格要求：
1. 只返回 JSON，不要任何额外说明文字、不要 Markdown 代码块包裹。
2. 字段必须完整，缺失信息用"未提供"占位，不要编造数字。
3. 金额估算需给出区间与依据，参考市场维修行情，不要臆造精确值。
4. 拒赔/减责风险点必须引用对应条款逻辑（如酒驾、无证驾驶、逃逸、夸大损失、重复理赔、事故真实性存疑等）。
5. 欺诈评分 0-100，越高越可疑，并列出具体可疑信号。
6. 若提供了【定损照片 OCR 识别文字】或【历史相似案例参考】，必须在返回 JSON 中输出 'ocr_used'（布尔）与 'reference_cases' 字段（数组，每项含 case_id、title、similarity_reason、ref_loss），并说明本案与历史案例的异同；不得直接照搬历史金额，需结合本案实际。

JSON 结构：
{
  "summary": "一句话结论",
  "estimated_loss": {
    "amount_range": "估算损失金额区间(元)",
    "basis": "测算依据",
    "major_items": ["主要维修/更换项目及参考价"]
  },
  "material_check": {
    "complete": false,
    "missing": ["缺失材料"],
    "present": ["已提交材料"]
  },
  "reject_risk": {
    "level": "无/低/中/高",
    "reasons": ["拒赔或减责风险点"],
    "suggestions": ["处理建议"]
  },
  "liability_ratio": "责任比例建议(基于责任认定)",
  "fraud_score": "欺诈风险评分(0-100)",
  "fraud_signals": ["可疑信号"],
  "underwriting": {
    "risk_level": "核保风险等级(标体/次标体/拒保)",
    "rate_advice": "费率建议",
    "notes": ["核保提示"]
  },
  "ocr_used": false,
  "reference_cases": [{"case_id": "C001", "title": "案例标题", "similarity_reason": "相似点", "ref_loss": "历史定损区间"}]
}
"""


def get_active_principles_text():
    """返回经人工审核生效的经验原则文本（追加进 system prompt 附录）。
    任何自动生成的资产须经 approve 才进入此处 —— 杜绝静默生效 / 自漂移。"""
    try:
        from memory_store import active_principles
        ps = active_principles()
    except Exception:
        return ""
    if not ps:
        return ""
    lines = ["\n\n【历史经验原则（经人工审核生效，须优先遵循）】"]
    for i, p in enumerate(ps, 1):
        lines.append("%d. %s" % (i, p["text"]))
    return "\n".join(lines)


def _build_user_prompt(claim, ocr_text=None, matched_cases=None):
    lines = []
    lines.append("【事故描述】" + (claim.get("accident_desc") or "未提供"))
    lines.append("【车辆信息】" + (claim.get("vehicle_info") or "未提供"))
    lines.append("【物损描述/现场照片说明】" + (claim.get("damage_desc") or "未提供"))
    lines.append("【维修清单/定损单】" + (claim.get("repair_list") or "未提供"))
    lines.append("【保单信息】" + (claim.get("policy_info") or "未提供"))
    lines.append("【责任认定】" + (claim.get("liability") or "未提供"))
    if ocr_text and ocr_text.strip():
        lines.append("【定损照片 OCR 识别文字】\n" + ocr_text.strip())
    if matched_cases:
        lines.append("【历史相似案例参考】")
        for mc in matched_cases:
            c = mc.get("case") or mc
            reason = mc.get("reason", "")
            lines.append(
                f"- [{c.get('id', '')}] {c.get('title', '')}；定损：{c.get('estimated_loss', '')}；"
                f"结论：{c.get('conclusion', '')}（相似点：{reason}）"
            )
    lines.append(
        "\n请基于以上材料，按系统指令输出结构化 JSON 分析。"
        "若提供了历史相似案例参考，请参考其定损区间与方法，但须结合本案实际，不得直接照搬金额。"
    )
    return "\n".join(lines)


def analyze_claim(claim, model="glm-4-9b-chat", base_url=SCNET_BASE_URL, api_key=None,
                  ocr_text=None, matched_cases=None):
    """对外主入口：输入理赔材料 dict，返回结构化分析 dict。
    可选 ocr_text（定损照片 OCR 文字）与 matched_cases（历史相似案例）用于补强分析。
    system prompt 末尾会自动追加经人工审核生效的经验原则（自我净化产物）。"""
    system_content = SYSTEM_PROMPT + get_active_principles_text()
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": _build_user_prompt(claim, ocr_text, matched_cases)},
    ]
    raw = call_llm(messages, model, base_url=base_url, api_key=api_key)
    parsed = _extract_json(raw)
    if parsed is None:
        raise RuntimeError("模型未返回可解析的 JSON，原始内容前 200 字：" + raw[:200])
    return parsed


def list_models(base_url=SCNET_BASE_URL, api_key=None):
    """列出可用模型（不耗 Token）。"""
    if api_key is None:
        api_key = get_api_key()
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + api_key}, method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa
        return {"error": str(e), "known_models": KNOWN_MODELS}


if __name__ == "__main__":
    # 命令行快速验证
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--list-models", action="store_true")
    p.add_argument("--model", default="glm-4-9b-chat")
    p.add_argument("--file", help="理赔材料 JSON 文件路径")
    p.add_argument("--base-url", default=SCNET_BASE_URL)
    args = p.parse_args()

    try:
        key = get_api_key()
    except RuntimeError as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(1)

    if args.list_models:
        print(json.dumps(list_models(args.base_url, key), ensure_ascii=False, indent=2))
        sys.exit(0)

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            claim = json.load(f)
    else:
        claim = {
            "accident_desc": "示例：两车追尾，后车全责",
            "vehicle_info": "示例：大众朗逸 2020款 1.5L",
            "damage_desc": "示例：前保险杠破损、左大灯碎裂、引擎盖凹陷",
            "repair_list": "示例：更换前杠、左大灯、钣金喷漆",
            "policy_info": "示例：交强险+商业三者200万+车损险",
            "liability": "示例：后车全责",
        }

    try:
        result = analyze_claim(claim, args.model, args.base_url, key)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except RuntimeError as e:
        sys.stderr.write("分析失败: " + str(e) + "\n")
        sys.exit(1)
