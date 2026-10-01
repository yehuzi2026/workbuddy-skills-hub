# -*- coding: utf-8 -*-
"""离线权威检索：在本团 references/ 内检索条款/知识，优先于凭记忆作答。

用法：
  python references/search/authority_search.py "工程量偏差"
  python references/search/authority_search.py "材料价格风险幅度"    # 自然语句也能命中（分词打分）
  python references/search/authority_search.py --json "物价调差"
  python references/search/authority_search.py --all            # 列出全部条款

匹配方式：全词命中优先；否则按 2~5 字片段打分（忽略空格），达到最低分即视为命中并排序输出，
避免"库里有、只是问法不同"被误判为库外。

退出码：0 = 命中；1 = 未命中（库外，须显式降级并标注）；2 = 内部错误。
"""
import sys, os, json, re, glob, argparse, io

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # references/


def _setup_io():
    for _name in ("stdin", "stdout", "stderr"):
        try:
            getattr(sys, _name).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_io()


def _load_clauses():
    db = os.path.join(BASE, "standards", "规范数据库.json")
    if not os.path.isfile(db):
        return []
    try:
        data = json.load(open(db, encoding="utf-8"))
    except Exception as e:
        sys.stderr.write("规范数据库解析失败：%s\n" % e)
        return []
    clauses = data.get("clauses", []) if isinstance(data, dict) else []
    if not clauses and isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                clauses = v
    return [c for c in clauses if isinstance(c, dict)]


def _fmt_clause(c):
    bits = ["[%s]" % c.get("group", "")]
    if c.get("clause"):
        bits.append(" %s" % c["clause"])
    if c.get("std_ref"):
        bits.append("（%s）" % c["std_ref"])
    head = "".join(bits)
    tail = []
    if c.get("verification"):
        tail.append(str(c["verification"]))
    if c.get("validity"):
        tail.append(str(c["validity"]))
    if c.get("applies_to"):
        tail.append(str(c["applies_to"]))
    return "%s %s%s" % (head, c.get("content", ""),
                        ("  ｜ " + " / ".join(tail)) if tail else "")


def _tokens(q):
    """把自然语言关键词拆成可匹配片段：全词 + 按连接符切分 + 2~5 字 n-gram。"""
    q = (q or "").strip().lower()
    if not q:
        return set()
    parts = [p for p in re.split(r"[\s,，、;；:：/\\|（）()【】\[\]《》\"'“”‘’]+", q) if p]
    toks = set(p for p in parts if len(p) >= 2)
    core = "".join(parts)
    for n in (2, 3, 4, 5):
        for i in range(0, max(0, len(core) - n + 1)):
            toks.add(core[i:i + n])
    return toks


MIN_SCORE = 4   # 至少一个 3 字片段，或四个 2 字片段；低于此分不认为是命中


def _score(q, toks, blob):
    """命中打分：全词命中封顶；否则累加命中片段的 (len-1)^2（越长越可信）。"""
    if not q or not blob:
        return 0
    if q in blob:
        return 10000
    return sum((len(t) - 1) ** 2 for t in toks if t in blob)


def _compact(s):
    return re.sub(r"\s+", "", s or "")


def search(query, top=10, max_per_source=4):
    q = (query or "").strip().lower()
    toks = _tokens(q)
    scored = []

    for c in _load_clauses():
        blob = " ".join(str(c.get(k, "")) for k in
                        ("topic", "content", "clause", "group", "std_ref", "note", "applies_to")).lower()
        s = max(_score(q, toks, blob), _score(q, toks, _compact(blob)))
        topic = str(c.get("topic", "")).lower()
        if q and (q in topic or _compact(q) in _compact(topic)):
            s += 20000            # 命中条目标题者优先，避免被正文里顺带提到的条目盖过
        if s >= MIN_SCORE:
            scored.append((s, "规范数据库", _fmt_clause(c)))

    for f in sorted(glob.glob(os.path.join(BASE, "knowledge", "*.md"))):
        name = os.path.basename(f)
        lines = []
        for line in io.open(f, encoding="utf-8").read().splitlines():
            line = line.strip()
            if len(line) <= 4:
                continue
            s = max(_score(q, toks, line.lower()), _score(q, toks, _compact(line).lower()))
            if s >= MIN_SCORE:
                lines.append((s, line[:240]))
        lines.sort(key=lambda x: -x[0])
        for s, seg in lines[:max_per_source]:
            scored.append((s, name, seg))

    for f in [os.path.join(BASE, "regulatory_register.md"),
              os.path.join(BASE, "sources.md")]:
        if not os.path.isfile(f):
            continue
        name = os.path.basename(f)
        lines = []
        for line in io.open(f, encoding="utf-8").read().splitlines():
            line = line.strip()
            if len(line) <= 4:
                continue
            s = max(_score(q, toks, line.lower()), _score(q, toks, _compact(line).lower()))
            if s >= MIN_SCORE:
                lines.append((s, line[:240]))
        lines.sort(key=lambda x: -x[0])
        for s, seg in lines[:max_per_source]:
            scored.append((s, name, seg))

    # 规范库优先（等分时），再按分数降序
    scored.sort(key=lambda x: (0 if x[1] == "规范数据库" else 1, -x[0]))
    return [(src_, seg) for _s, src_, seg in scored[:top]]


def main():
    ap = argparse.ArgumentParser(description="本团离线权威检索（规范数据库 + 知识库 + 法规注册表）")
    ap.add_argument("query", nargs="*", help="关键词，如：工程量偏差")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出（便于程序消费）")
    ap.add_argument("--all", action="store_true", help="列出库内全部条款")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    if args.all:
        hits = [("规范数据库", _fmt_clause(c)) for c in _load_clauses()]
    else:
        q = " ".join(args.query).strip()
        if not q:
            ap.print_help()
            return 2
        hits = search(q, args.top)

    if args.json:
        print(json.dumps({"query": " ".join(args.query), "count": len(hits),
                          "hits": [{"source": s, "text": t} for s, t in hits]},
                         ensure_ascii=False, indent=2))
    else:
        if not hits:
            print("【⚠ 超出本团权威库】库内未覆盖关键词「%s」（已按分词打分匹配仍无结果）。" % " ".join(args.query))
            print("处理要求：必须显式降级——在输出中标注「⚠ 超出本团权威库，以下为经验判断，"
                  "建议查阅规范[编号]，仅供参考」，严禁假装权威或凭记忆杜撰条款/数字。")
        for src, seg in hits:
            print("【%s】%s" % (src, seg))
        if hits:
            print("\n（共 %d 条；引用时须带 std_ref/clause 版本信息，并核实现行有效）" % len(hits))
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
