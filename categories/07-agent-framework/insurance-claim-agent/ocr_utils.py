#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定损照片 OCR 识别模块

识别策略（优先级）：
1. 本地 RapidOCR（离线 ONNX 推理）—— 首选。纯本地运行，**符合 SCNet 容器内网出网限制**，
   不依赖任何外部 API，是 SCNet 部署时的正确选择。
2. 云端视觉兜底（智谱 GLM-4V，api.bigmodel.cn）—— 仅当本地未装 RapidOCR 且本机有外网
   + 已配置 ZHIPU_API_KEY 时可用。⚠️ SCNet 纯内网部署时不可用（出网限制）。

接口：
  ocr_image(image, prefer="local") -> (text, engine)
    image: 文件路径 / bytes / base64 字符串（或 "data:image/...;base64,..." 前缀）
    返回 (识别文本, 引擎名)；全部失败返回 ("", "none")，不抛异常（不阻塞主分析流程）。
"""
import base64
import os
import sys
import json
import urllib.request


def _to_bytes(image):
    """统一转换为 bytes。支持文件路径 / bytes / base64。"""
    if isinstance(image, bytes):
        return image
    if isinstance(image, str):
        if os.path.isfile(image):
            with open(image, "rb") as f:
                return f.read()
        s = image
        if s.startswith("data:") and "," in s:
            s = s.split(",", 1)[1]
        try:
            return base64.b64decode(s)
        except Exception:
            return b""
    return b""


def _ocr_rapidocr(image_bytes):
    """本地 RapidOCR。未安装或出错返回 None（触发降级）。"""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return None
    try:
        import cv2
        import numpy as np
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        engine = RapidOCR()
        result, _ = engine(img)
        if not result:
            return ""
        texts = [line[1] for line in result]
        return "\n".join(texts)
    except Exception:
        return None


def _ocr_zhipu(image_bytes):
    """云端视觉兜底（智谱 GLM-4V）。需 ZHIPU_API_KEY + 外网。"""
    api_key = os.environ.get("ZHIPU_API_KEY")
    if not api_key:
        return None
    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        prompt = ("请识别这张车险定损/事故现场照片中的全部文字信息"
                  "（车牌号、损伤部位、维修项目、金额、单据字段、印章等），逐行列出，不要解释。")
        payload = {
            "model": "glm-4v-flash",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
                ],
            }],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def ocr_image(image, prefer="local"):
    """
    识别定损照片文字。
    image: 文件路径 / bytes / base64 字符串
    prefer: "local"(默认, 优先 RapidOCR) 或 "cloud"(优先智谱)
    返回 (text, engine)：engine ∈ {"rapidocr","zhipu","none"}
    """
    image_bytes = _to_bytes(image)
    if not image_bytes:
        return ("", "none")

    if prefer == "cloud":
        text = _ocr_zhipu(image_bytes)
        if text is not None:
            return (text, "zhipu")
        text = _ocr_rapidocr(image_bytes)
        if text is not None:
            return (text, "rapidocr")
        return ("", "none")

    # 默认优先本地
    text = _ocr_rapidocr(image_bytes)
    if text is not None:
        return (text, "rapidocr")
    text = _ocr_zhipu(image_bytes)
    if text is not None:
        return (text, "zhipu")
    return ("", "none")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        text, engine = ocr_image(sys.argv[1])
        print(f"[engine] {engine}")
        print(text or "（未识别到文字 / 引擎不可用）")
