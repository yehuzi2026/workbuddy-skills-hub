# -*- coding: utf-8 -*-
"""统一输出门禁（工程造价审计AI助手 · 唯一 sanctioned 输出漏斗）。

用法（推荐用 --file，避免 Windows 管道把中文变成 ???）：
  python references/search/gate.py emit --file 草稿.md        # 强制漏斗：PASS 才释放
  python references/search/gate.py check --file 草稿.md       # 只校验，输出 JSON
  python references/search/gate.py selfcheck 报告1.md 报告2.md # 扫已生成文件（可多个）
  python references/search/gate.py log --limit 20             # 查看门禁留痕
  echo "..." | python references/search/gate.py emit          # 管道模式（须确保编码 UTF-8）

退出码：0 = 通过/已释放（含 WARN）  1 = 已拦截/未通过  2 = 引擎内部错误（失败闭合，禁止放行）

三级判定：
  ERROR 硬拦截：① 无出处的具体数值（未查库即给数）② "模糊词+数字"组合（大概1000万）
                ③ 金额数值只标条文、无数据来源/计算式（条文只能证明"规则"，不能证明"本项目金额"）
                ④ 输入编码损坏（管道把中文变成 ???，无法判定 → 一律拦截）
  WARN  提示  ：① 价格/费率类数字未声明数据来源 ② 有数字但未见 calc_engine.py 实算证据
                ③ 泛用模糊措辞+数字（可能/应该/大致 与数字同句），建议改为确定表述
  PASS   ：可正常输出

铁律：未查权威条款库（references/standards/规范数据库.json）就给具体数字 = 编造，一律拦截。
"""
import sys, os, re, json, hashlib, datetime, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "gate_log.jsonl")


def _setup_io():
    """统一 IO 编码：中文环境下重定向或管道输出不再乱码/崩溃。"""
    for _name in ("stdin", "stdout", "stderr"):
        try:
            getattr(sys, _name).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_io()

# ---------------------------------------------------------------------------
# 规则库
# ---------------------------------------------------------------------------
# 强模糊：必须紧邻数字才判定为"编造风险"（如 "约1000万" "1000万左右"）
# 强模糊：模糊词必须"紧贴"数字才算编造信号（避免「合同约定 3%」「约定时效 28 天」被误伤）
HARD_FUZZY = re.compile(
    r"(?:大概|大约|估计|大致|差不多|接近|近乎|约)\s*(?:为|计|是|有|在|达|到)?\s*\d"
    r"|\d\s*(?:为|计|是|有|在|达|到)?\s*(?:左右|上下|上下浮动|差不多|大概|大约|估计)"
)
# 弱模糊：泛用措辞，提示改写（不拦截，避免把正常风险表述一刀切）
SOFT_FUZZY = ["可能", "应该", "估计", "大概", "大致", "通常", "一般来说", "基本可以", "应该可以"]

# 条文/规范引用特征（出现即视为"该片段有出处"）
CITED = re.compile(
    r"(GB\s*/?\s*T?\s*\d{3,5}(?:\s*[-—]\s*\d{2,4})?"     # GB 50500 / GB/T 50500-2024
    r"|JGJ\s*\d+|CJJ\s*\d+|DB\s*[J52]\d*|JTG\s*\w*\d+"
    r"|第\s*\d+(?:\.\d+)*\s*[条章节款项]"                  # 第9.6.2条 / 第11.1条
    r"|〔\s*\d{4}\s*〕\s*\d+\s*号"                          # 财建〔2004〕369号
    r"|主席令第?[一二三四五六七八九十\d]+号|国务院\s*\d+\s*号令|\d+\s*号令"
    r"|清单计价(标准|规范)|计价管理办法|价款结算暂行办法|质量保证金管理办法"
    r"|示范文本|司法解释|审计法|基本建设财务规则|造价咨询规范|造价鉴定规范)"
)

# 不可作为"数字"判定的模式（先剔除）
DATE_PAT = re.compile(r"\d{4}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?)?"
                      r"|\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}"
                      r"|\d{4}\s*[-/.]\s*\d{1,2}"
                      r"|第\s*\d+\s*[条章节款项]")
# 与经济结论相关的"数字+单位"
NUM = re.compile(r"(?<![\d.])\d+(?:\.\d+)?\s*(?:%|％|万元|亿元|元|万\s*(?:㎡|m²|平方米|m³|m3|立方米)"
                 r"|㎡|平方米|m²|m³|m3|kg|吨|t\b|天|工日|台班"
                 r"|小时|h\b|层|倍|mm|cm|米|km|kN|MPa|kPa|kV|人)")

# 片段级豁免：示例/假设/库外降级语境
EXEMPT = re.compile(r"(示例|练习|演示|假设|假定|例如|比如|本题|该题|仅供|模拟|草稿|待核|待确认|"
                    r"超出权威库|经验估算|经验判断|建议查阅规范|仅供参考|以最新官方|以现行有效|"
                    r"参考值|非官方|占位|请替换|待填|口径示例)")

PRICE_TERMS = re.compile(r"组价|综合单价|费率|信息价|材料价|人工单价|机械台班|管理费|利润率|"
                         r"税金|规费|单方(指标|造价|成本)|含税|除税|价格")

# 金额口径：条文只能证明"计价规则"，不能证明"本项目的金额"，故金额须另有来源或计算式
MONEY_UNIT = "元"

# 计算式特征：等式，或字面出现的乘/加以号（如 12000−10900=1100、7400×3%）视为已展示推算过程
DERIVATION = re.compile(r"[=＝]|(?:\d|\))\s*[×*＋+]\s*(?:\d|\()")

# 项目事实数据来源标记：此类片段中的数字来自用户资料，不属于"无出处编造"
DATA_PROV = re.compile(r"(用户提供|用户给定|用户口径|据送审|送审资料|报送(资料|文件|价|工程量)|据合同|合同约定|"
                       r"据图纸|竣工图|施工图|现场记录|现场签证|签证单|计量(单|记录|凭证)|台账|投标报价|"
                       r"认价单|监理(记录|确认)|结算书|据甲方|甲方提供)")

SOURCE_DECL = re.compile(r"数据来源|当地公布|local_rates|信息价|最新公布|以最新|现行有效版本|"
                         r"造价站|造价管理|定额|用户提供|calc_engine\.py|已调用|工具调用|工具输出|实算")

CALC_EVIDENCE = re.compile(r"calc_engine\.py|python\s+\S+\.py|已调用|工具调用|工具输出|"
                           r"实算结果|引擎计算|运行结果|执行\s*calc|运行\s*calc")

def split_segments(text):
    """按行与句末标点切分，便于"逐片段"判断出处，避免一句话的引用豁免整篇。"""
    segs = []
    for line in text.splitlines():
        for part in re.split(r"(?<=[。；;！!？?])", line):
            part = part.strip()
            if part:
                segs.append(part)
    return segs


def _strip_refs(seg):
    """剔除日期/条款号等非结论性数字，避免把 2026年9月 当成编造数字。"""
    return DATE_PAT.sub(" ", seg)


def scan(text, lenient=False):
    errors, warns = [], []
    if not text or not text.strip():
        return {"pass": True, "level": "PASS", "warnings": [],
                "note": "空内容，无可校验对象"}

    # —— 编码损坏检测（管道把中文变成 ??? 时，任何校验都不可信，必须拦截）——
    qmarks = text.count("?")
    if ("\ufffd" in text or re.search(r"\?{3,}", text)
            or (qmarks >= 4 and qmarks / max(1, len(text)) > 0.12)):
        errors.append({"level": "ERROR", "type": "encoding",
                       "msg": "输入存在明显编码损坏（中文变成 ? 或替换字符），门禁无法校验，一律拦截。"
                              "请改用：python references/search/gate.py emit --file <草稿文件>，"
                              "或先执行 chcp 65001 并设置 $OutputEncoding 为 UTF-8。"})

    # —— 逐片段：无出处的具体数字 ——
    global_cited = bool(CITED.search(text))
    bad, bad_money = [], []
    for seg in split_segments(text):
        body = _strip_refs(seg)
        nums = NUM.findall(body)
        if not nums:
            continue
        # 来源类豁免：能说明"这个数字是怎么来的"（区别于"规则依据"）
        prov = (bool(EXEMPT.search(seg)) or bool(CALC_EVIDENCE.search(seg))
                or bool(SOURCE_DECL.search(seg)) or bool(DATA_PROV.search(seg))
                or bool(DERIVATION.search(body)))
        covered = prov or bool(CITED.search(seg)) or (lenient and global_cited)
        if not covered:
            bad.append((seg, nums))
        elif not prov and any(MONEY_UNIT in n for n in nums):
            bad_money.append((seg, [n for n in nums if MONEY_UNIT in n]))
    if bad:
        sample = "；".join("%s（%s）" % (s[:40], ",".join(ns[:3])) for s, ns in bad[:3])
        errors.append({"level": "ERROR", "type": "uncited_number",
                       "msg": "共 %d 个片段出现具体数值但本片段无条文出处、无数据来源、未见计算工具调用：%s。"
                              "未查库即给数字=编造；须先跑 "
                              "python references/search/authority_search.py \"<关键词>\" 并附条文号，"
                              "或标注『数据来源：local_rates.json / 当地公布信息价』，"
                              "或明确标注『以下为无规范出处的经验估算，仅供参考』。"
                              % (len(bad), sample)})

    if bad_money:
        sample = "；".join("%s（%s）" % (s[:40], ",".join(ns[:3])) for s, ns in bad_money[:3])
        errors.append({"level": "ERROR", "type": "amount_without_source",
                       "msg": "共 %d 个片段出现金额数值（元/万元/亿元）但只标了条文、没有数据来源或计算式：%s。"
                              "条文只能证明计价『规则』，不能证明『本项目的金额』；金额须至少具备其一："
                              "① 数据来源（送审资料/合同/签证单/计量台账/local_rates.json/当地公布信息价）；"
                              "② 实算证据与计算式（如 python calc_engine.py --func audit_reduction …，"
                              "或 12000-10900=1100 万元）；"
                              "③ 显式标注为经验估算并写明『仅供参考，不作为审查依据』。"
                              % (len(bad_money), sample)})

    # —— 模糊措辞 ——
    m = HARD_FUZZY.search(text)
    if m:
        ctx = text[max(0, m.start() - 12): m.end() + 12].replace("\n", " ")
        errors.append({"level": "ERROR", "type": "fuzzy_number",
                       "msg": "出现『模糊措辞+数字』组合，上下文：「…%s…」，属典型编造信号，禁止输出。"
                              "须给出确定数值（并附实算证据）或删除该数字。" % ctx})
    soft = set()
    for _seg in split_segments(text):
        if NUM.search(_strip_refs(_seg)):
            soft.update(w for w in SOFT_FUZZY if w in _seg)
    soft = sorted(soft)
    if soft:
        warns.append({"level": "WARN", "type": "fuzzy_wording",
                      "msg": "出现泛用模糊措辞 %s 且同句含数值；结论性表述建议改为确定表述，"
                             "风险提示类表述可保留但须写明触发条件。" % "、".join(soft)})

    # —— 价格/费率类数字须声明来源 ——
    has_num = bool(NUM.search(_strip_refs(text)))
    if has_num and PRICE_TERMS.search(text) and not SOURCE_DECL.search(text):
        warns.append({"level": "WARN", "type": "price_without_source",
                      "msg": "输出含价格/费率数据但未见『数据来源』声明，请标注"
                             "『数据来源：当地公布信息价 / local_rates.json』；"
                             "未标注的仅供参照，不得直接作为结算定案/审定价依据。"})
    # —— 有数字但无实算证据 ——
    if has_num and not CALC_EVIDENCE.search(text) and not SOURCE_DECL.search(text):
        warns.append({"level": "WARN", "type": "no_calc_evidence",
                      "msg": "输出含具体数值但未展示计算工具(calc_engine.py)调用命令与输出，"
                             "疑似未实算即给数。须附调用证据或明确标注数据来源，否则结论不可采信。"})

    level = "ERROR" if errors else ("WARN" if warns else "PASS")
    total = len(errors) + len(warns)
    return {"pass": not errors, "level": level, "warnings": errors + warns,
            "统计": {"ERROR": len(errors), "WARN": len(warns), "合计": total}}


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
def _team_default():
    try:
        return os.path.basename(os.path.dirname(os.path.dirname(HERE)))
    except Exception:
        return "cost-audit-team"


def _log(team, mode, level, action, reason, snippet):
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "team": team, "mode": mode, "level": level, "action": action, "reason": reason,
           "draft_sha1": hashlib.sha1(snippet.encode("utf-8", "ignore")).hexdigest()[:12]}
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


def _emit(team, text, lenient=False):
    res = scan(text, lenient)
    if res["level"] == "ERROR":
        _log(team, "emit", "ERROR", "BLOCKED",
             "; ".join(w.get("msg", "") for w in res["warnings"]), text)
        sys.stderr.write("🚫 [门禁拦截] 该内容未通过输出门禁，禁止输出。\n")
        for w in res["warnings"]:
            sys.stderr.write("  - [%s] %s\n" % (w.get("level"), w.get("msg", "")))
        sys.stderr.write("\n合规替代（三选一）：\n")
        sys.stderr.write('  ① 查条文号后重出：python references/search/authority_search.py "<关键词>"\n')
        sys.stderr.write('  ② 补数据来源：python calc_engine.py --func ... --rates_file references/data/local_rates.json\n')
        sys.stderr.write('  ③ 显式降级：标注「以下为无规范出处的经验估算，仅供参考，不作为设计/审查依据」\n')
        return 1
    for w in res["warnings"]:
        if w.get("level") == "WARN":
            sys.stderr.write("⚠️ [门禁提醒] %s\n" % w.get("msg", ""))
    _log(team, "emit", res["level"], "RELEASED", "", text)
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _check(team, text, lenient=False):
    res = scan(text, lenient)
    if lenient:
        res["lenient"] = True
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 1 if res["level"] == "ERROR" else 0


def _selfcheck(team, paths, lenient=False):
    worst = 0
    for path in paths:
        if not os.path.exists(path):
            sys.stderr.write("selfcheck: 文件不存在 %s\n" % path)
            worst = max(worst, 2)
            continue
        text = open(path, encoding="utf-8", errors="ignore").read()
        res = scan(text, lenient)
        print(json.dumps({"file": path, "level": res["level"], "warnings": res["warnings"]},
                         ensure_ascii=False, indent=2))
        _log(team, "selfcheck", res["level"], "SCANNED",
             "; ".join(w.get("msg", "") for w in res["warnings"]), text[:500])
        if res["level"] == "ERROR":
            worst = max(worst, 1)
    return worst


def _log_view(limit):
    if not os.path.exists(LOG):
        print("尚无门禁留痕（%s 不存在）" % LOG)
        return 0
    rows = []
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    for r in rows[-limit:]:
        print("%s  %-5s %-9s %-9s %s" % (r.get("ts"), r.get("level"), r.get("mode"),
                                         r.get("action"), r.get("draft_sha1")))
    print("共 %d 条留痕，显示最后 %d 条。" % (len(rows), min(limit, len(rows))))
    return 0


def main():
    ap = argparse.ArgumentParser(description="统一输出门禁（工程造价审计AI助手）")
    ap.add_argument("mode", choices=["emit", "check", "selfcheck", "log"])
    ap.add_argument("target", nargs="*", help="selfcheck 模式的待扫文件（可多个）")
    ap.add_argument("--file", default=None, help="emit/check 模式的草稿文件（强烈推荐，避免管道乱码）")
    ap.add_argument("--team", default=None, help="团队标识（默认取目录名）")
    ap.add_argument("--lenient", action="store_true",
                    help="宽松模式：文中任一处有规范引用即覆盖全文数字（默认按片段严格判定）")
    ap.add_argument("--limit", type=int, default=20, help="log 模式显示条数")
    args = ap.parse_args()
    team = args.team or _team_default()

    if args.mode == "log":
        return _log_view(args.limit)
    if args.mode == "selfcheck":
        targets = list(args.target or [])
        if args.file:
            targets.append(args.file)
        if not targets:
            sys.stderr.write("selfcheck 需要文件参数：gate.py selfcheck <文件> [文件2 ...]\n")
            return 2
        return _selfcheck(team, targets, args.lenient)

    if args.file:
        if not os.path.exists(args.file):
            sys.stderr.write("找不到草稿文件：%s\n" % args.file)
            return 2
        text = open(args.file, encoding="utf-8", errors="ignore").read()
    else:
        text = sys.stdin.read()
        if (not text.strip()) and not sys.stdin.isatty():
            sys.stderr.write("⚠ 未收到任何内容（管道为空或编码异常）。建议改用 "
                             "gate.py %s --file <草稿文件>\n" % args.mode)
            return 2
    if args.mode == "emit":
        return _emit(team, text, args.lenient)
    return _check(team, text, args.lenient)


if __name__ == "__main__":
    sys.exit(main())
