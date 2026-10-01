#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自我进化 · 通用经验库（领域无关）
================================================================
任何垂直 Agent（合同审查 / 工单分派 / 理赔初审 / 投标作战……）共用同一套
「经验沉淀 → 人工在环闸门 → 生效原则/案例」的持久化层。

四张表：
1. experiences   : 在线交互（每次主任务 + 后续人工评分/纠正）。EvolveR「在线交互」阶段产物。
2. pending_assets: 自动生成的待审资产（新原则 / 新案例 / 通用资产），人工闸门前一律 pending。
3. principles     : 已生效经验原则（status='active' 后才注入 prompt 附录）。
4. custom_cases  : 已生效自增长案例（active=1 后才供匹配器使用）。

安全红线（对应方案1「验证闸门 / 人工审阅」）：
- 任何「自动生成」的资产都必须经人工 approve 才生效，绝不静默写入生效区。
- 不修改种子案例库（领域自带），自增长案例独立存表。
- 本文件零三方依赖，仅用标准库 sqlite3 / json / os / datetime。
"""
import os
import sqlite3
import json
from datetime import datetime

# 允许通过环境变量覆盖 DB 路径；默认放在调用方进程工作目录下的 agent_self_improve.db
DB_PATH = os.environ.get(
    "SELF_IMPROVE_DB",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent_self_improve.db"),
)


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    conn = _conn()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            task_input TEXT,
            task_output TEXT,
            human_rating INTEGER,
            human_correction TEXT,
            reflected INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS pending_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            kind TEXT,
            content TEXT,
            source_ids TEXT,
            status TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS principles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            text TEXT,
            source_ids TEXT,
            status TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS custom_cases (
            id TEXT PRIMARY KEY,
            ts TEXT,
            data TEXT,
            source_ids TEXT,
            active INTEGER DEFAULT 1
        );
        """
    )
    conn.commit()
    conn.close()


# ---------- 在线交互记录（EvolveR: online interaction） ----------

def record_experience(task_input, task_output, human_rating=None, human_correction=None):
    """捕获一次在线交互。返回 experience id。"""
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO experiences (ts, task_input, task_output, human_rating, human_correction, reflected) "
        "VALUES (?,?,?,?,?,0)",
        (
            _now(),
            json.dumps(task_input, ensure_ascii=False),
            json.dumps(task_output, ensure_ascii=False),
            human_rating,
            human_correction,
        ),
    )
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def update_experience(eid, human_rating=None, human_correction=None):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    if human_rating is not None:
        cur.execute("UPDATE experiences SET human_rating=? WHERE id=?", (human_rating, eid))
    if human_correction is not None:
        cur.execute("UPDATE experiences SET human_correction=? WHERE id=?", (human_correction, eid))
    conn.commit()
    conn.close()
    return True


def list_experiences(limit=50, reflected=None):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    if reflected is None:
        cur.execute("SELECT * FROM experiences ORDER BY id DESC LIMIT ?", (limit,))
    else:
        cur.execute(
            "SELECT * FROM experiences WHERE reflected=? ORDER BY id DESC LIMIT ?",
            (1 if reflected else 0, limit),
        )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def mark_reflected(ids):
    if not ids:
        return
    init_db()
    conn = _conn()
    cur = conn.cursor()
    for i in ids:
        cur.execute("UPDATE experiences SET reflected=1 WHERE id=?", (i,))
    conn.commit()
    conn.close()


# ---------- 待审资产闸门（方案1: 验证闸门 / 人工审阅） ----------

def add_pending(kind, content, source_ids):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO pending_assets (ts, kind, content, source_ids, status) VALUES (?,?,?,?,'pending')",
        (
            _now(),
            kind,
            content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            ",".join(str(i) for i in source_ids),
        ),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def list_pending():
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending_assets WHERE status='pending' ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def approve_asset(pid):
    """人工批准：把待审资产移入生效区（principles.active / custom_cases.active）。"""
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending_assets WHERE id=?", (pid,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    kind = row["kind"]
    content = row["content"]
    src = row["source_ids"]
    if kind == "principle":
        cur.execute(
            "INSERT OR REPLACE INTO principles (ts, text, source_ids, status) VALUES (?,?,?,'active')",
            (_now(), content, src),
        )
    elif kind == "case":
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            conn.close()
            return False
        cid = data.get("id") or ("N" + datetime.now().strftime("%Y%m%d%H%M%S"))
        data["id"] = cid
        cur.execute(
            "INSERT OR REPLACE INTO custom_cases (id, ts, data, source_ids, active) VALUES (?,?,?,?,1)",
            (cid, _now(), json.dumps(data, ensure_ascii=False), src),
        )
    cur.execute("UPDATE pending_assets SET status='approved' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return True


def reject_asset(pid):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE pending_assets SET status='rejected' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return True


# ---------- 生效区读取（注入 prompt / 案例匹配） ----------

def active_principles():
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM principles WHERE status='active' ORDER BY id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def active_custom_cases():
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM custom_cases WHERE active=1 ORDER BY id")
    rows = [json.loads(r["data"]) for r in cur.fetchall()]
    conn.close()
    return rows


if __name__ == "__main__":
    init_db()
    print("自我进化经验库初始化完成：", DB_PATH)
