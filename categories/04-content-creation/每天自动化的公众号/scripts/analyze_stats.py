#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_stats.py — 公众号每日数据复盘分析（通用版）

读取 数据/raw/YYYY-MM-DD.json（由 fetch_stats.js 采集），输出 数据/analysis_YYYY-MM-DD.json。
北极星指标：涨粉
  - P1 冷启动（<500 粉）：北极星 = 净增粉丝数
  - P2 变现（>=500 粉）：北极星 = 收益额 / 单粉产出

用法：
  python analyze_stats.py [--raw-dir 数据/raw] [--out-dir 数据]

raw JSON 预期结构（至少含 homeStats；articles 可选）：
  {
    "homeStats": {"total_user":1,"yesterday_read":0,"yesterday_new_follow":0,
                  "yesterday_share":0,"original_count":0,"need_realname":true,"scrapedFrom":"home"},
    "articles": [ {"date":"2026-08-06","title":"...","read":0,"share":0,"like":0,
                   "collect":0,"add_user":0,"topic_type":"节气时令","content_type":"流量"} ]
  }
"""

import os
import sys
import json
import glob
import datetime
import argparse

# content_type 语义 = 流量 / 立场（立场内容当前阶段暂缓，见战略），与是否原创无关。
FIELDS = ["date", "title", "msgid", "read", "share", "like", "collect",
          "add_user", "add_rate", "topic_type", "content_type", "is_original",
          "rating", "note"]


def rate(add_user, avg_add, read, avg_read):
    """按涨粉（非阅读）评级。"""
    # 无效流量：阅读高但涨粉≈0
    if avg_read > 0 and read >= avg_read and add_user == 0:
        return "⚠️无效流量"
    if avg_add <= 0:
        if add_user >= 5:
            return "🔥爆款"
        if add_user > 0:
            return "✅良好"
        return "⚪待评" if read == 0 else "❌扑街"
    r = add_user / float(avg_add)
    if r >= 3:
        return "🔥爆款"
    if r >= 1:
        return "✅良好"
    if add_user > 0:
        return "⚪平稳"
    return "❌扑街"


def parse_users(raw):
    """优先 homeStats（DOM 提取，最可靠），回退 userAnalysis。"""
    home = raw.get("homeStats") or {}
    if home.get("total_user") is not None:
        return {
            "cumulate_user": home.get("total_user", 0) or 0,
            "new_user": home.get("yesterday_new_follow", 0) or 0,
            "cancel_user": 0,
            "need_realname": bool(home.get("need_realname", False)),
        }
    ua = raw.get("userAnalysis", {}) or {}
    summary = ua.get("user_summary", {}) or {}
    return {
        "cumulate_user": int(summary.get("cumulate_user", 0) or 0),
        "new_user": int(summary.get("new_user", 0) or 0),
        "cancel_user": int(summary.get("cancel_user", 0) or 0),
        "need_realname": False,
    }


def parse_articles(raw):
    arts = raw.get("articles") or []
    out = []
    for a in arts:
        try:
            read = int(a.get("read", 0) or 0)
            share = int(a.get("share", 0) or 0)
            like = int(a.get("like", 0) or 0)
            collect = int(a.get("collect", 0) or 0)
            add_user = int(a.get("add_user", 0) or 0)
        except (TypeError, ValueError):
            read = share = like = collect = add_user = 0
        out.append({
            "date": a.get("date", ""),
            "title": a.get("title", ""),
            "msgid": a.get("msgid", ""),
            "read": read,
            "share": share,
            "like": like,
            "collect": collect,
            "add_user": add_user,
            "topic_type": a.get("topic_type", ""),
            "content_type": a.get("content_type", "流量"),
            "is_original": bool(a.get("is_original", False)),
        })
    return out


def analyze(raw):
    users = parse_users(raw)
    arts = parse_articles(raw)
    n = len(arts)

    total_add = sum(a["add_user"] for a in arts)
    total_read = sum(a["read"] for a in arts)
    avg_add = (total_add / n) if n else 0.0
    avg_read = (total_read / n) if n else 0.0

    # 逐篇评级 + 涨粉率
    for a in arts:
        a["add_rate"] = round(a["add_user"] / a["read"], 4) if a["read"] else 0.0
        a["rating"] = rate(a["add_user"], avg_add, a["read"], avg_read)

    # 按内容属性分组
    by_content_type = {}
    for a in arts:
        ct = a["content_type"] or "未标注"
        d = by_content_type.setdefault(ct, {"count": 0, "add": 0, "read": 0})
        d["count"] += 1
        d["add"] += a["add_user"]
        d["read"] += a["read"]

    # 无效流量选题（阅读≥篇均但涨粉=0）
    wasted = [a["topic_type"] for a in arts
              if avg_read > 0 and a["read"] >= avg_read and a["add_user"] == 0 and a["topic_type"]]

    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stage": "P1冷启动" if users.get("cumulate_user", 0) < 500 else "P2变现",
        "north_star": "净增粉丝数",
        "sample_size": n,
        "total_add_user": total_add,
        "avg_add_user": round(avg_add, 2),
        "account_add_rate": round(total_add / users["cumulate_user"], 4) if users["cumulate_user"] else 0.0,
        "avg_read": round(avg_read, 2),
        "users": users,
        "by_content_type": by_content_type,
        "wasted_traffic_topics": wasted,
        "articles": arts,
        "need_realname": users.get("need_realname", False),
        "note": "样本<10 篇时只记录不下结论；未实名验证时收益恒为 0。" if n < 10 else "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="数据/raw")
    ap.add_argument("--out-dir", default="数据")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.raw_dir, "*.json")))
    if not files:
        print(json.dumps({"ok": False, "error": "no raw json found in " + args.raw_dir},
                         ensure_ascii=False))
        return 1

    latest = files[-1]
    with open(latest, "r", encoding="utf-8") as f:
        raw = json.load(f)

    result = analyze(raw)
    result["source_file"] = os.path.basename(latest)

    os.makedirs(args.out_dir, exist_ok=True)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    out_path = os.path.join(args.out_dir, f"analysis_{today}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "ok": True,
        "source": result["source_file"],
        "stage": result["stage"],
        "north_star": result["north_star"],
        "sample_size": result["sample_size"],
        "total_add_user": result["total_add_user"],
        "need_realname": result["need_realname"],
        "analysis": out_path,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
