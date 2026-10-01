# 保险理赔 / 核保自动化 Agent —— 生产镜像
# 适用：任意支持 Docker 的 Linux / Windows 服务器（推荐 VPS / 云主机）
FROM python:3.11-slim

WORKDIR /app

# RapidOCR 依赖系统级图形库（opencv）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 尽力预下载 RapidOCR 的 ONNX 模型（首次实例化即下载）。
# 若构建机无外网则跳过，运行时首次 OCR 会自动下载（需运行时外网）。
RUN python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()" || echo "OCR 模型预下载跳过（运行时首次会下载）"

ENV PORT=8000
EXPOSE 8000

# 用 gunicorn 多 worker 更稳；单 worker 也可。--timeout 放宽给模型推理留时间。
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --timeout 300"]
