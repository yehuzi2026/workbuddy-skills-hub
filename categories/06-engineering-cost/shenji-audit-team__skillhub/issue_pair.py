# -*- coding: utf-8 -*-
"""问题定性与依据配对：把「问题定性」接到可核查的条款依据上。

为什么需要它：审计发现最难回答的问题是「凭什么这么定性、依据是什么」。
本工具把 问题描述 / 问题定性 与 规范数据库（31 条）做规则匹配，输出：
  ① 命中的定性类别与命中理由；② 推荐依据（std_ref + clause + 效力 + 适用条件 + 要点）；
  ③ 常见处理思路与证据要求；④ 明确的「须人工复核、条款号须核验」声明。

设计原则：
  - 只给「建议依据」，不下结论、不替代审计判断；未命中时如实说未命中，并转向 authority_search.py；
  - 「推荐依据」引用规范数据库条目的 topic，两者必须同源（content_check.py 会校验，漂移即报错）；
  - 输出自带数据来源，便于直接粘进底稿 / 报告的引用段。

用法：
  python issue_pair.py "地下车库土方重复计量，多计 320 万元"
  python issue_pair.py --定性 "多计·工程量"
  python issue_pair.py --list            # 列出全部定性类别与关键词
  python issue_pair.py "..." --json      # 机器可读输出
退出码：0 = 命中定性映射；1 = 未命中（须改用 authority_search.py 或人工定性）；2 = 数据或参数错误。
免责：本映射为审计实务经验整理，条款号与表述 ⚠️ 待核验，正式出具意见前必须核对官方原文。
"""
import os, sys, io, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_REL = "references/data/问题定性与依据映射.json"
STD_REL = "references/standards/规范数据库.json"
MAP = os.path.join(HERE, *MAP_REL.split("/"))
STD = os.path.join(HERE, *STD_REL.split("/"))
SEARCH = os.path.join(HERE, "references", "search", "authority_search.py")
LF = chr(10)


def _setup_io():
    for _n in ("stdin", "stdout", "stderr"):
        try:
            getattr(sys, _n).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _fail(msg, code=2):
    print(json.dumps({"错误": msg}, ensure_ascii=False))
    return code


def _load(path, what):
    if not os.path.isfile(path):
        raise IOError("找不到%s：%s" % (what, path))
    return json.loads(io.open(path, "rb").read().decode("utf-8-sig"))


def load_data():
    return _load(MAP, "问题定性与依据映射"), _load(STD, "规范数据库")


def topic_index(db):
    idx = {}
    for c in (db.get("clauses") or []):
        t = c.get("topic")
        if t:
            idx[t] = c
    return idx


def check_mapping(m, db):
    """映射引用的 topic 必须都存在于规范数据库，否则视为漂移。返回不一致清单。"""
    idx = topic_index(db)
    bad = []
    for e in (m.get("mappings") or []):
        for t in (e.get("推荐依据") or []):
            if t not in idx:
                bad.append("%s → %s" % (e.get("定性"), t))
    return bad


def _ding_bonus(given, ding):
    """用户给定「定性」与映射条目的契合度：完全一致 > 大类/子类包含 > 无关。"""
    if not given or not ding:
        return 0
    if given == ding:
        return 100
    for p in [ding] + ding.split("·"):
        if p and p in given:
            return 40
    for p in given.split("·"):
        if p and p in ding:
            return 30
    return 0


def _score(entry, q, given=""):
    """打分：具体关键词（如「重复计量」「暂列金额」）优先于大类词（如「多计」）。"""
    ding = entry.get("定性", "") or ""
    head = ding.split("·")[0] if "·" in ding else ding
    hits = [k for k in (entry.get("关键词") or []) if k in q]
    sc = 0
    for k in hits:
        sc += 3 if k == head else 10
    sub = ding.split("·")[-1] if "·" in ding else ""
    if sub and sub in q:
        sc += 20
    return sc + _ding_bonus(given, ding), hits


def pair(query, dingxing="", mapping=None, db=None):
    """规则匹配：返回命中定性、理由、建议依据与处理/证据要求。不做结论。

    query  = 问题描述（主匹配文本）；dingxing = 用户已填的定性（作为加权，不替代描述）。
    """
    m = mapping if mapping is not None else load_data()[0]
    d = db if db is not None else load_data()[1]
    q = (query or "").strip() or (dingxing or "").strip()
    given = (dingxing or "").strip()
    idx = topic_index(d)
    best, best_sc, best_hits = None, 0, []
    for e in (m.get("mappings") or []):
        sc, hits = _score(e, q, given)
        if sc > best_sc:
            best, best_sc, best_hits = e, sc, hits
    if not best:
        return {"matched": False, "查询": q, "依据": []}
    return {
        "matched": True,
        "查询": q,
        "定性": best.get("定性"),
        "命中关键词": best_hits,
        "已填定性": given,
        "匹配得分": best_sc,
        "依据": [idx[t] for t in (best.get("推荐依据") or []) if t in idx],
        "常见处理": best.get("常见处理"),
        "证据要求": best.get("证据要求"),
        "映射免责": (m.get("_metadata") or {}).get("disclaimer", ""),
    }


def render_text(r):
    out = ["== 问题定性与依据配对 ==", "输入：%s" % r.get("查询", "")]
    if not r.get("matched"):
        out.append("结果：**未命中**定性映射（规则库未命中 ≠ 无依据）。")
        out.append("下一步：`python references/search/authority_search.py \"关键词\"` 检索条文，"
                   "或按合同专用条款 / 委托要求补充依据（数据来源：%s）。" % STD_REL)
        return LF.join(out)
    hits = r.get("命中关键词") or []
    out.append("命中定性：**%s**（规则命中：%s；定性须由审计人员最终确认）"
               % (r.get("定性"), "、".join(hits) if hits else "按定性关键词精确匹配"))
    out.append("")
    out.append("【建议依据】（须人工复核；⚠️ 条款号待核验，正式出具前必须核对官方原文）")
    for i, c in enumerate(r.get("依据") or [], 1):
        mark = "⚠️ 条款号待核验" if (c.get("verification") or "").startswith("⚠") else "✅ 已核验"
        out.append("%d）%s｜%s｜%s（数据来源：%s 条目「%s」，效力：%s，%s）"
                   % (i, c.get("clause", ""), c.get("topic", ""), c.get("content", ""),
                      STD_REL, c.get("topic", ""), c.get("validity", "（待填）"), mark))
        if c.get("applies_to"):
            out.append("　　适用条件：%s" % c.get("applies_to"))
        if c.get("note"):
            out.append("　　提示：%s" % c.get("note"))
    out.append("")
    out.append("【常见处理】%s" % (r.get("常见处理") or "（待填）"))
    out.append("【证据要求】%s" % (r.get("证据要求") or "（待填）"))
    out.append("")
    out.append("【口径声明】本结果为「建议依据」，用于定向核查，不构成审计结论；"
               "审计发现须做到「事实 + 条款 + 证据」三件齐备（数据来源：%s 的核验声明）。"
               % STD_REL)
    if r.get("映射免责"):
        out.append("【免责】%s" % r.get("映射免责"))
    return LF.join(out)


def list_all(m):
    rows = ["== 定性类别与关键词（共 %d 类）==" % len(m.get("mappings") or [])]
    for e in (m.get("mappings") or []):
        rows.append("- %s：%s" % (e.get("定性"), "、".join(e.get("关键词") or [])))
    rows.append("")
    rows.append("用法：python issue_pair.py --定性 \"多计·工程量\"（数据来源：%s）" % MAP_REL)
    return LF.join(rows)


def main(argv=None):
    _setup_io()
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    if as_json:
        args.remove("--json")
    try:
        m, d = load_data()
    except Exception as exc:
        return _fail("数据读取失败：%s" % exc)
    bad = check_mapping(m, d)
    if bad:
        return _fail("映射与规范数据库不一致（模板漂移，须修复后再用）：%s" % "；".join(bad))
    if "--list" in args:
        args.remove("--list")
        print(json.dumps({"定性类别": [e.get("定性") for e in (m.get("mappings") or [])],
                          "数据来源": MAP_REL}, ensure_ascii=False, indent=2) if as_json else list_all(m))
        return 0
    dingxing, query = "", ""
    if "--定性" in args:
        i = args.index("--定性")
        if i + 1 >= len(args):
            return _fail("--定性 需要跟一个定性类别，例如 --定性 \"多计·工程量\"")
        dingxing = args[i + 1]
        del args[i:i + 2]
    if args:
        query = " ".join(args)
    if not query and not dingxing:
        print(list_all(m))
        return _fail("请提供问题描述或 --定性 参数")
    r = pair(query, dingxing, m, d)
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(render_text(r))
    if r.get("matched"):
        return 0
    if not as_json and os.path.isfile(SEARCH):
        print("")
        print("---- 自动转向条文检索（authority_search.py）----")
        p = subprocess.run([sys.executable, SEARCH, (query or dingxing)],
                           cwd=HERE, capture_output=True)
        print((p.stdout or b"").decode("utf-8", "replace").strip())
    return 1


if __name__ == "__main__":
    sys.exit(main())