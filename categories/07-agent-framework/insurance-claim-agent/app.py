#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保险理赔 / 核保自动化 Agent —— FastAPI 后端（v0.3.0，含自我净化/自进化）

部署：SCNet「模型部署 → Web 应用」或任意支持 Python 的容器。
- 必须设置环境变量 SCNET_API_KEY
- 启动：uvicorn app:app --host 0.0.0.0 --port 8000

接口：
  页面：
    GET  /                      前端页（含人工反馈 + 自我净化管理面板）
  核心分析：
    POST /api/analyze           受理赔材料（可选定损照片 base64）→ OCR+案例匹配+结构化分析
                                返回体含 experience_id（供反馈关联）
    GET  /api/models            列出可用模型
    GET  /api/cases             列出历史案例库摘要（含自增长案例）
  自我净化 / 人工在环闭环：
    POST /api/feedback          提交人工评分/纠正（反思净化的锚点），关联 experience_id
    POST /api/evolve            触发一轮蒸馏（提炼原则+新案例）→ 进入待审区
    GET  /api/pending           列出待审资产（原则/案例）
    POST /api/approve           人工批准某待审资产 → 生效
    POST /api/reject            人工拒绝某待审资产
    GET  /api/principles        列出已生效经验原则
    GET  /api/experiences       列出在线交互记录（审计用）
"""
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from claim_analyzer import (
    analyze_claim,
    get_api_key,
    list_models,
    SCNET_BASE_URL,
    KNOWN_MODELS,
)
from ocr_utils import ocr_image
from cases import match_cases, get_all_cases
from memory_store import (
    update_experience,
    list_pending,
    approve_asset,
    reject_asset,
    active_principles,
    list_experiences,
)
# 自我净化复用通用范式 agent-self-improve 的 SelfImprove 类（core 已复制进本目录）
from evolver import SelfImprove

# 经验库隔离到本项目：用独立 DB 文件，避免与其它 Agent 共用
import os as _os
if not _os.environ.get("SELF_IMPROVE_DB"):
    _os.environ["SELF_IMPROVE_DB"] = _os.path.join(_os.path.dirname(__file__), "experience.db")

# 领域参数集中在集成点（合同审查/工单分派等只需改这里）
SI = SelfImprove(
    domain_name="车险理赔初审",
    domain_hint="你是一名车险定损核赔专家，关注事故责任认定、定损合理性、拒赔风险、欺诈评分、核保建议。",
    case_schema_hint='案例字段：id/title/accident_type/accident_desc/vehicle_info/damage_desc/repair_list/liability/estimated_loss/reject_risk/conclusion',
    field_label="理赔",
)

app = FastAPI(title="保险理赔核保自动化 Agent", version="0.3.0")

_FIELDS = [
    "accident_desc",
    "vehicle_info",
    "damage_desc",
    "repair_list",
    "policy_info",
    "liability",
]


class ClaimRequest(BaseModel):
    accident_desc: str = ""
    vehicle_info: str = ""
    damage_desc: str = ""
    repair_list: str = ""
    policy_info: str = ""
    liability: str = ""
    model: str = "glm-4-9b-chat"
    image_base64: str = ""   # 定损照片 base64（可选）
    use_cases: bool = True   # 是否做历史案例匹配


class FeedbackRequest(BaseModel):
    experience_id: int
    rating: int = None        # 1-5
    correction: str = ""      # 人工纠正意见


class AssetRequest(BaseModel):
    id: int                   # pending_asset id


class EvolveRequest(BaseModel):
    model: str = "glm-4-9b-chat"


@app.get("/")
def index():
    path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    return FileResponse(path)


@app.get("/api/models")
def models():
    try:
        key = get_api_key()
        data = list_models(api_key=key)
        if "data" in data:
            return {"models": [m.get("id") for m in data["data"]]}
        return {"models": data.get("known_models", KNOWN_MODELS)}
    except RuntimeError:
        return {"models": KNOWN_MODELS}


@app.get("/api/cases")
def list_cases():
    cs = get_all_cases()
    return {"cases": [
        {
            "id": c.get("id"),
            "title": c.get("title"),
            "accident_type": c.get("accident_type", ""),
            "estimated_loss": c.get("estimated_loss", ""),
        }
        for c in cs
    ]}


def _build_query_text(claim, ocr_text):
    parts = [claim.get(k, "") or "" for k in _FIELDS]
    if ocr_text:
        parts.append("定损照片OCR：" + ocr_text)
    return "\n".join(p for p in parts if p.strip())


@app.post("/api/analyze")
def analyze(req: ClaimRequest):
    try:
        get_api_key()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    claim = {k: getattr(req, k) for k in _FIELDS}
    if not any(claim.values()) and not req.image_base64:
        raise HTTPException(status_code=400, detail="请至少填写一项理赔材料或上传定损照片。")

    # 1) OCR 定损照片（尽力而为，失败不阻塞主分析）
    ocr_text, ocr_engine = "", "none"
    if req.image_base64:
        try:
            ocr_text, ocr_engine = ocr_image(req.image_base64)
        except Exception:
            ocr_engine = "none"

    # 2) 历史案例匹配（含自增长案例；尽力而为）
    matched = []
    if req.use_cases:
        try:
            query = _build_query_text(claim, ocr_text)
            matched = match_cases(query, model=req.model)
        except Exception:
            matched = []

    # 3) 主分析
    try:
        result = analyze_claim(
            claim, req.model, base_url=SCNET_BASE_URL,
            ocr_text=ocr_text or None, matched_cases=matched or None,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # 4) 在线交互捕获（EvolveR: online interaction）→ 返回 experience_id 供反馈关联
    experience_id = SI.capture_online(claim, result)

    matched_view = [
        {
            "case_id": m.get("case_id"),
            "reason": m.get("reason", ""),
            "title": (m.get("case") or {}).get("title", ""),
            "estimated_loss": (m.get("case") or {}).get("estimated_loss", ""),
            "conclusion": (m.get("case") or {}).get("conclusion", ""),
        }
        for m in matched
    ]

    return JSONResponse(content={
        "analysis": result,
        "ocr_text": ocr_text,
        "ocr_engine": ocr_engine,
        "matched_cases": matched_view,
        "experience_id": experience_id,
    })


# ---------------- 自我净化 / 人工在环闭环 ----------------

@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    if req.rating is None and not req.correction.strip():
        raise HTTPException(status_code=400, detail="请至少提供评分或纠正意见。")
    ok = update_experience(req.experience_id, req.rating, req.correction)
    if not ok:
        raise HTTPException(status_code=404, detail="experience_id 不存在。")
    return {"ok": True, "experience_id": req.experience_id,
            "note": "反馈已记录，可作为下一轮蒸馏的纠正锚点。"}


@app.post("/api/evolve")
def evolve(req: EvolveRequest):
    """触发一轮 EvolveR 闭环：未反思经验 → 离线自蒸馏 → 提案入待审区。"""
    res = SI.run_evolve(model=req.model, base_url=SCNET_BASE_URL)
    if not res.get("evolved"):
        # 无 Key / 无经验 / LLM 出错：明确告知，不静默成功
        raise HTTPException(status_code=400, detail=res.get("reason", "蒸馏未执行"))
    return res


@app.get("/api/pending")
def pending():
    return {"pending": SI.list_pending()}


@app.post("/api/approve")
def approve(req: AssetRequest):
    ok = SI.approve(req.id)
    if not ok:
        raise HTTPException(status_code=404, detail="pending id 不存在。")
    return {"ok": True, "id": req.id, "note": "已批准并生效（原则注入 prompt / 案例并入匹配）。"}


@app.post("/api/reject")
def reject(req: AssetRequest):
    ok = SI.reject(req.id)
    if not ok:
        raise HTTPException(status_code=404, detail="pending id 不存在。")
    return {"ok": True, "id": req.id, "note": "已拒绝，未生效。"}


@app.get("/api/principles")
def principles():
    return {"principles": [
        {"id": p["id"], "text": p["text"], "source_ids": p["source_ids"]}
        for p in active_principles()
    ]}


@app.get("/api/experiences")
def experiences(limit: int = 50):
    return {"experiences": list_experiences(limit=limit)}
