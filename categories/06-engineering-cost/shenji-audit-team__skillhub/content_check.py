# -*- coding: utf-8 -*-
"""内容自检：全包完整性 + 文档/代码/配置一致性 + 题库答案可复现（专家级交付前最后一道自检）。

用途：防止"说明文档写得天花乱坠、代码里根本没有"这类漂移——文档引用的函数/脚本必须真实存在，plugin.json 的角色与工具必须真实存在，单代理 SKILL 必须与 agent 定义同源，知识库索引必须收录全部文件。

用法：
  python content_check.py           # 全量检查（含题库逐题复算）
  python content_check.py --quick   # 只查完整性，跳过逐题复算

退出码：0 = 全部通过；1 = 发现问题（详见输出）。
"""
import io, os, sys, json, re, shlex, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
# 跳过临时/输出目录：以 "_" 开头的一律视为生成物或暂存（工具默认输出目录 ./_项目档案 就在包内），
# 否则用户一跑生成命令，本检查就会把生成物当包内容而误报。
SKIP_DIRS = {".git", ".svn", ".hg", ".idea", ".vscode", "node_modules", "__pycache__"}


def _skipped(name):
    """目录级过滤：暂存/生成目录跳过（工具默认输出 ./_项目档案 就在包内）；
    .codebuddy-plugin 是真实包内容，必须照常校验，所以不能一刀切跳过 "." 开头的目录。"""
    return name in SKIP_DIRS or name.startswith("_")


def _skipped_file(name):
    """文件级过滤：只跳过隐藏文件；_meta.json 等带下划线的包内文件必须照常校验。"""
    return name.startswith(".")


LF = chr(10)          # 供章节解析使用（避免源码里出现转义反斜杠）


def iter_files():
    for dirpath, dirnames, filenames in os.walk(HERE):
        dirnames[:] = [d for d in dirnames if not _skipped(d)]
        for fn in filenames:
            if _skipped_file(fn):
                continue
            if fn.lower().endswith((".py", ".json", ".md", ".jsonl", ".csv")):
                yield os.path.join(dirpath, fn)


def check_integrity():
    problems, counts = [], {"py": 0, "json": 0, "md": 0}
    for fp in iter_files():
        rel = os.path.relpath(fp, HERE)
        raw = open(fp, "rb").read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            problems.append("非 UTF-8 编码：%s（%s）" % (rel, e))
            continue
        if text.startswith("\ufeff"):
            problems.append("含 BOM（部分工具会误读）：%s" % rel)
        if "\ufffd" in text:
            problems.append("含替换字符，编码已损坏：%s" % rel)
        if re.search(r"\?{4,}", text):
            problems.append("疑似中文变问号的乱码：%s" % rel)
        if fp.endswith(".py"):
            counts["py"] += 1
            try:
                compile(text, fp, "exec")
            except SyntaxError as e:
                problems.append("Python 语法错误：%s（%s）" % (rel, e))
        elif fp.endswith(".json"):
            counts["json"] += 1
            try:
                json.loads(text)
            except Exception as e:
                problems.append("JSON 非法：%s（%s）" % (rel, e))
        elif fp.endswith(".md"):
            counts["md"] += 1
            if len(text.strip()) < 40:
                problems.append("内容过短，疑似被截断：%s" % rel)
    return counts, problems


def _norm(o):
    if isinstance(o, dict):
        return {k: _norm(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_norm(v) for v in o]
    if isinstance(o, float):
        return round(o, 4)
    return o


def check_answers():
    """题库计算题：现场跑 command，与 answer 字段逐字比对（保证"可复现"不是空话）。"""
    qf = os.path.join(HERE, "question_bank", "questions.json")
    if not os.path.isfile(qf):
        return 0, ["未找到 question_bank/questions.json"]
    data = json.load(io.open(qf, encoding="utf-8"))
    checked, bad = 0, []
    for item in data.get("questions", []):
        cmd, ans = item.get("command"), item.get("answer")
        if not cmd or not ans or item.get("qtype") != "计算":
            continue
        parts = shlex.split(cmd.strip())
        if len(parts) < 2 or parts[1] != "calc_engine.py":
            continue
        checked += 1
        p = subprocess.run([PY] + parts[1:], cwd=HERE, capture_output=True)
        if p.returncode != 0:
            bad.append("第 %s 题：命令执行失败（rc=%s）" % (item.get("id"), p.returncode))
            continue
        try:
            live = _norm(json.loads(p.stdout.decode("utf-8", "ignore")))
            want = _norm(json.loads(ans))
        except Exception as e:
            bad.append("第 %s 题：答案无法解析（%s）" % (item.get("id"), e))
            continue
        if live != want:
            keys = sorted(set(list(live.keys()) + list(want.keys())))
            diff = [k for k in keys if live.get(k) != want.get(k)]
            bad.append("第 %s 题：与现场实算不一致（字段：%s）" % (item.get("id"), "、".join(diff)))
    return checked, bad


def _md_files():
    for fp in iter_files():
        if fp.endswith(".md"):
            yield fp


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
           "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15}
_PAIRS = ["audit-settlement", "audit-auditor", "audit-claim", "audit-pricer", "audit-index"]


def check_consistency():
    """文档 ↔ 代码 ↔ 配置 一致性：文档引用的函数/脚本/清单必须真实存在。"""
    problems = []
    eng = io.open(os.path.join(HERE, "calc_engine.py"), encoding="utf-8").read()
    fns = set(re.findall(r"(?m)^def\s+(\w+)", eng))
    dlv = set(re.findall(r"(?m)^def\s+(\w+)",
                         io.open(os.path.join(HERE, "deliverable.py"), encoding="utf-8").read()))
    dlv_names = ("workpaper|audit_plan|pbc_list|issue_register|dispute_register|"
                 "settlement_report|audit_report|claim_report|index_report")

    for fp in _md_files():
        rel = os.path.relpath(fp, HERE)
        text = io.open(fp, encoding="utf-8").read()
        for fn in sorted(set(re.findall(r"--func\s+([A-Za-z_]\w*)", text))):
            if fn not in fns:
                problems.append("%s：引用了引擎中不存在的函数 --func %s" % (rel, fn))
        for script in sorted(set(re.findall(r"python\s+([\w./\\-]+\.py)", text))):
            cand = script.replace("\\", "/").lstrip("./")
            cand2 = cand.split("/")[-1]
            if not (os.path.isfile(os.path.join(HERE, cand.replace("/", os.sep)))
                    or os.path.isfile(os.path.join(HERE, "references", "search", cand2))):
                problems.append("%s：引用了不存在的脚本 %s" % (rel, script))
        for fn in sorted(set(re.findall(r"\b(" + dlv_names + r")\s*\(", text))):
            if fn not in dlv:
                problems.append("%s：引用了 deliverable.py 中不存在的函数 %s()" % (rel, fn))

    # 知识库索引必须收录 knowledge 目录下全部文件
    kb_dir = os.path.join(HERE, "references", "knowledge")
    kb_idx = io.open(os.path.join(HERE, "references", "知识库使用说明.md"), encoding="utf-8").read()
    if os.path.isdir(kb_dir):
        for fn in sorted(os.listdir(kb_dir)):
            if fn.endswith(".md") and fn not in kb_idx:
                problems.append("references/知识库使用说明.md：未收录 %s" % fn)

    # plugin.json 的角色 / 工具清单必须与包内实际文件一致
    plug_p = os.path.join(HERE, ".codebuddy-plugin", "plugin.json")
    if os.path.isfile(plug_p):
        plug = json.load(io.open(plug_p, encoding="utf-8"))
        for a in plug.get("agents", []):
            rel = a[2:] if a.startswith("./") else a
            if not os.path.isfile(os.path.join(HERE, rel.replace("/", os.sep))):
                problems.append("plugin.json：agents 指向不存在的文件 %s" % a)
        for t in plug.get("tools", []):
            nm = t.get("name", "")
            if not (os.path.isfile(os.path.join(HERE, nm))
                    or os.path.isfile(os.path.join(HERE, "references", "search", nm))):
                problems.append("plugin.json：tools 指向不存在的脚本 %s" % nm)
        for m in plug.get("teamInfo", {}).get("memberAgents", []):
            for rel in ("agents/%s.md" % m, "skills/%s/SKILL.md" % m):
                if not os.path.isfile(os.path.join(HERE, rel.replace("/", os.sep))):
                    problems.append("plugin.json：成员 %s 缺少 %s" % (m, rel))

    # 两形态同源：skills/<角色>/SKILL.md 正文须与 agents/<角色>.md 逐字一致
    for k in _PAIRS:
        ap = os.path.join(HERE, "agents", k + ".md")
        sp = os.path.join(HERE, "skills", k, "SKILL.md")
        if not os.path.isfile(ap):
            problems.append("两形态同源：缺少 agents/%s.md" % k)
            continue
        if not os.path.isfile(sp):
            problems.append("两形态同源：缺少 skills/%s/SKILL.md" % k)
            continue
        a = io.open(ap, encoding="utf-8").read()
        body = a[a.index(LF + "# "):].lstrip(LF).strip()
        nums = [_CN_NUM.get(x, -1) for x in re.findall(r"(?m)^## ([一二三四五六七八九十]+)、", body)]
        if nums != list(range(1, len(nums) + 1)):
            problems.append("agents/%s.md：章节编号不连续或重复 %s" % (k, nums))
        sk = io.open(sp, encoding="utf-8").read()
        end_fm = sk.find(LF + "---" + LF)
        if not sk.startswith("---") or end_fm < 0:
            problems.append("skills/%s/SKILL.md：frontmatter 缺失或损坏" % k)
            continue
        rest = sk[end_fm + 5:]
        idx = rest.find("## %s、单代理直出" % {13: "十四", 14: "十五"}.get(len(nums), "十四"))
        if idx < 0:
            problems.append("skills/%s/SKILL.md：缺少「单代理直出」章节（章节数：%d）" % (k, len(nums)))
            continue
        if rest[:idx].strip() != body:
            problems.append("skills/%s/SKILL.md：正文与 agents/%s.md 不一致（两形态已漂移，请重跑派生脚本）" % (k, k))
    # 项目信息模板必须与 project_template.py 的 TEMPLATE 同源（模板漂移 = 用户拿到的字段与代码不符）
    tp = os.path.join(HERE, "templates", "项目信息表.template.json")
    if not os.path.isfile(tp):
        problems.append("缺少 templates/项目信息表.template.json（项目信息模板）")
    else:
        try:
            import project_template as _pt
            if json.load(io.open(tp, encoding="utf-8")) != _pt.TEMPLATE:
                problems.append("templates/项目信息表.template.json 与 project_template.py 的 TEMPLATE 不一致"
                                "（模板已漂移，请重新导出）")
        except Exception as exc:
            problems.append("templates/项目信息表.template.json 一致性校验失败：%s" % exc)
        # 反向：包内每个顶层工具脚本都必须登记在 plugin.json.tools（不能新增工具却不登记）
        listed = set(t.get("name", "") for t in plug.get("tools", []))
        for fn in sorted(os.listdir(HERE)):
            if fn.endswith(".py") and fn not in listed:
                problems.append("plugin.json：tools 未登记包内脚本 %s" % fn)
    # 问题定性与依据映射必须与规范数据库同源（引用不存在的条目 = 映射漂移）
    mp = os.path.join(HERE, "references", "data", "问题定性与依据映射.json")
    if not os.path.isfile(mp):
        problems.append("缺少 references/data/问题定性与依据映射.json（问题定性→依据映射）")
    else:
        try:
            import issue_pair as _ip
            _m = json.load(io.open(mp, encoding="utf-8"))
            _d = json.load(io.open(os.path.join(HERE, "references", "standards", "规范数据库.json"),
                                   encoding="utf-8"))
            for _b in _ip.check_mapping(_m, _d):
                problems.append("问题定性与依据映射.json：引用了规范数据库里不存在的条目 %s（映射漂移）" % _b)
        except Exception as exc:
            problems.append("问题定性与依据映射.json 一致性校验失败：%s" % exc)
    # 成套模板的构件必须真的接线（写了 doc_xxx 却没在 build_project 输出 = 用户拿不到该文件）
    try:
        pt_txt = io.open(os.path.join(HERE, "project_template.py"), encoding="utf-8").read()
        for fn in sorted(re.findall(r"(?m)^def ((?:doc|_placeholder)_\w+)", pt_txt)):
            if ("*%s(" % fn) not in pt_txt:
                problems.append("project_template.py：构件 %s() 未在 build_project 中输出"
                                "（函数写了但没接线，档案会缺这份文件）" % fn)
    except Exception as exc:
        problems.append("project_template.py 构件接线一致性校验失败：%s" % exc)
    # 成套档案文件数说明必须与实现同步（改实现不改说明 = 用户按旧数量核对会漏件）
    for rel in ("README.md", "SKILL.md", "使用示例.md", ".codebuddy-plugin/plugin.json"):
        try:
            _t = io.open(os.path.join(HERE, rel), encoding="utf-8").read()
        except Exception:
            continue
        if "30 份" not in _t:
            problems.append("%s：成套档案文件数说明未同步（当前实现为 30 份）" % rel)
    # 工具是角色的「手脚」：每个包内工具至少要被一份角色定义提到（否则角色根本不知道它能用）
    try:
        _agent_txt = ""
        _ad = os.path.join(HERE, "agents")
        for _fn in sorted(os.listdir(_ad)):
            if _fn.endswith(".md"):
                _agent_txt += io.open(os.path.join(_ad, _fn), encoding="utf-8").read()
        for fn in sorted(os.listdir(HERE)):
            if fn.endswith(".py") and fn not in _agent_txt:
                problems.append("agents/*.md：没有任何角色定义提到工具 %s"
                                "（角色定义未同步该工具，实际作业时用不上它）" % fn)
    except Exception as exc:
        problems.append("工具↔角色定义覆盖校验失败：%s" % exc)
    return problems


def main():
    quick = "--quick" in sys.argv
    print("== 全包完整性 ==")
    counts, problems = check_integrity()
    print("  扫描文件：py=%d  json=%d  md=%d" % (counts["py"], counts["json"], counts["md"]))
    print("== 文档/代码/配置一致性 ==")
    incon = check_consistency()
    print("  一致性问题：%d 项" % len(incon))
    checked, bad_ans = (0, []) if quick else check_answers()
    print("== 题库答案可复现 ==")
    print("  已复算计算题：%d 题%s" % (checked, "（已跳过）" if quick else ""))
    allp = problems + incon + bad_ans
    if allp:
        print("\n发现问题 %d 项：" % len(allp))
        for p in allp:
            print("  -", p)
        return 1
    print("\n全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())