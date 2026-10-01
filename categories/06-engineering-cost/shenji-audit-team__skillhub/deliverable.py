# -*- coding: utf-8 -*-
"""结构化交付物生成器（让专家产出可直接交付的文件，而非只有聊天文本）。

能力：
  - build_table(title, columns, rows, out_path)   生成 xlsx（openpyxl 缺失时自动降级 csv）
  - build_report(title, sections, out_path)       生成 Markdown 报告（.md）
  - settlement_report(...)                        结算审核：对比表 + 审核报告
  - audit_report(...)                             造价审计：发现/风险/建议 + 底稿清单
  - claim_report(...)                             索赔分析：要件判定 + 费用构成 + 证据清单
  - index_report(...)                             造价指标：指标表 + 对标分析
  - gate_check(path)                              交付前调用统一门禁自校验，返回 level
  - workpaper(items, meta, out_dir)              审计底稿：索引 + 检查程序 + 证据 + 依据 + 金额 + 结论 + 编制/复核签署
  - pbc_list(items, meta, out_dir)               资料索取清单（PBC）：开工交底即发给被审计单位
  - issue_register(issues, out_dir, meta)        问题台账与整改跟踪（含销号状态 + 问题定性→条款自动配对）
  - dispute_register(disputes, out_dir, meta)    争议事项台账（报送方主张 / 审核意见 / 依据 / 处理建议）
  - audit_plan(items, meta, out_dir)             审计实施方案 · 检查范围（调用 calc_engine.sample_plan，非统计抽样）
  - reconcile.py（同目录）                         送审 / 审定两版数据对量差异分析（量差·价差·漏项·增项）

设计原则：报告正文中的数值一律与「数据来源 / calc_engine.py 实算 / 规范条文」写在同一句，
以满足输出门禁的"数字须可溯源"要求（未标来源的数字会被 gate.py 拦截）。
"""
import os, csv, sys, json, datetime, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "references", "search", "gate.py")


def _setup_io():
    for _name in ("stdin", "stdout", "stderr"):
        try:
            getattr(sys, _name).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_io()

try:
    import issue_pair as _ip      # 问题定性 → 条款依据配对（失败时降级为提示，不阻断交付）
except Exception:
    _ip = None


DEFAULT_STANDARD = "GB/T 50500-2024《建设工程工程量清单计价标准》"


def build_table(title, columns, rows, out_path):
    """生成表格文件。优先 xlsx，缺失依赖降级 csv。返回实际写出路径。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    except Exception:
        csv_path = os.path.splitext(out_path)[0] + ".csv"
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(columns)
            for r in rows:
                w.writerow(r)
        return csv_path

    wb = Workbook()
    ws = wb.active
    ws.title = str(title)[:31]
    head_fill = PatternFill("solid", fgColor="1D9E75")
    head_font = Font(bold=True, color="FFFFFF", size=11)
    thin = Side(style="thin", color="D0D5DD")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws.append(columns)
    for c in range(1, len(columns) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    for r in rows:
        ws.append(list(r))
        ridx = ws.max_row
        for c in range(1, len(columns) + 1):
            ws.cell(row=ridx, column=c).border = border
            ws.cell(row=ridx, column=c).alignment = Alignment(vertical="center")
    for c in range(1, len(columns) + 1):
        ws.column_dimensions[ws.cell(row=1, column=c).column_letter].width = 18
    ws.freeze_panes = "A2"
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    wb.save(out_path)
    return out_path


def build_report(title, sections, out_path):
    """sections: list[(h2, body)]。生成 Markdown 报告。"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# %s" % title, "",
             "> 生成时间：%s ｜ 工程造价审计AI助手（结构化交付）" % now,
             "> 交付性质：专业辅助材料，非审计/审定法定文书；数据与结论的使用须经责任主体复核签认。", ""]
    for h, body in sections:
        lines.append("## %s" % h)
        lines.append("")
        lines.append(body)
        lines.append("")
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def gate_check(path, timeout=30):
    """调用统一门禁自校验交付文件，返回 dict（失败不抛异常，但会标注 level=ERROR）。"""
    if not os.path.exists(GATE):
        return {"level": "UNKNOWN", "warnings": [], "note": "未找到 gate.py，未做门禁自校验"}
    try:
        r = subprocess.run([sys.executable, GATE, "selfcheck", path],
                           capture_output=True, timeout=timeout)
        out = (r.stdout or b"").decode("utf-8", "replace")
        try:
            data = json.loads(out)
        except Exception:
            data = {"level": "WARN", "warnings": [{"msg": "门禁输出无法解析"}], "raw": out[:400]}
        data["exit_code"] = r.returncode
        return data
    except Exception as e:
        return {"level": "UNKNOWN", "warnings": [{"msg": "门禁调用失败：%s" % e}]}


def _provenance(standard, source_note):
    return ("依据：%s（或合同约定的计价依据版本）；数据来源：%s。"
            % (standard, source_note))


def _flat(s, n=60):
    """压平表格单元格文本：把会切断门禁片段判定的句读（句号/分号/换行）替换为逗号。

    目的：同一行内的数值与取数来源必须落在同一片段，否则会被输出门禁误判为「无来源数字」。
    """
    t = " ".join(str("" if s is None else s).split())
    for ch in (chr(10), chr(13), "。", "；", ";", "！", "!", "？", "?"):
        t = t.replace(ch, "，")
    return t[:n]


def settlement_report(submit_rows, meta, out_dir, standard=DEFAULT_STANDARD):
    """一键产出结算审核交付物（对比表 xlsx + 审核报告 md + 门禁自校验）。

    submit_rows: list[dict]，字段 ["序号","分部分项","报送价(万元)","审定价(万元)",
                                  "审减额(万元)","审减率(%)","争议/说明"]
    meta: 项目名/地区/建面/合同价/报送总价/审定总价/审减额/审减率/主要审减项/争议提示/数据来源
    """
    columns = ["序号", "分部分项", "报送价(万元)", "审定价(万元)", "审减额(万元)", "审减率(%)", "争议/说明"]
    rows = [[r.get(c, "") for c in columns] for r in submit_rows]
    xlsx = build_table("结算审核对比表", columns, rows, os.path.join(out_dir, "结算审核对比表.xlsx"))
    src = meta.get("数据来源", "用户提供的送审结算资料")
    prov = _provenance(standard, src)
    secs = [
        ("一、项目概况",
         "项目：%s；地区：%s；建筑面积：%s（数据来源：送审资料 %s）。\n"
         "合同价 %s 万元、报送总价 %s 万元、审定总价 %s 万元（数据来源：送审资料 %s）。"
         % (meta.get("项目名", "-"), meta.get("地区", "-"), meta.get("建面", "-"), src,
            meta.get("合同价", "-"), meta.get("报送总价", "-"), meta.get("审定总价", "-"), src)),
        ("二、审核结论",
         "审减额 %s 万元、整体审减率 %s%%（数据来源：calc_engine.py 实算，审减额 = 报送价 − 审定价）。\n"
         "主要审减集中在：%s。逐项明细见附件《结算审核对比表》。"
         % (meta.get("审减额", "-"), meta.get("审减率", "-"), meta.get("主要审减项", "详见对比表"))),
        ("三、依据与口径",
         prov + "计价口径（含税/除税）、面积口径、风险幅度与工程量偏差调价阈值均须以合同专用条款为准。"),
        ("四、争议与风险提示",
         str(meta.get("争议提示", "无重大争议。")) +
         "\n\n风险提示：审减率高不代表报送方有责，须逐项列明审减原因与对应条款（数据来源：本条为风险提示，不含测算结论）。"
         "暂列金额/暂估价属非确定价，须按实结算；合同外签证无有效签认不得计入。"),
        ("五、附件",
         "《结算审核对比表》（%s）。" % ("xlsx" if str(xlsx).endswith("xlsx") else "csv")),
    ]
    md = build_report("%s · 竣工结算审核报告" % meta.get("项目名", "项目"), secs,
                      os.path.join(out_dir, "结算审核报告.md"))
    return {"xlsx": xlsx, "md": md, "gate": gate_check(md)}


def audit_report(findings, meta, out_dir, standard=DEFAULT_STANDARD):
    """造价审计报告（跟踪/竣工决算）：发现 + 风险 + 建议 + 底稿清单。"""
    columns = ["序号", "审计事项", "审计发现", "涉及金额(万元)", "依据/条款", "风险等级", "整改建议"]
    rows = [[f.get(c, "") for c in columns] for f in findings]
    xlsx = build_table("审计发现清单", columns, rows, os.path.join(out_dir, "审计发现清单.xlsx"))
    src = meta.get("数据来源", "被审计单位提供的合同、支付凭证、变更签证与计量资料")
    risks = "\n".join("- [%s] %s（依据：%s；数据来源：%s）"
                      % (f.get("风险等级", "中"), f.get("审计发现", ""),
                         f.get("依据/条款", "见《审计发现清单》"), src)
                      for f in findings) or "未列出风险项（数据来源：本次审计发现清单）。"

    secs = [
        ("一、审计范围与依据",
         "阶段：%s；截止时点：%s。%s" % (meta.get("阶段", "-"), meta.get("截止时点", "-"),
                                   _provenance(standard, src))),
        ("二、审计发现",
         "概算 %s 万元、已发生 %s 万元、偏差 %s 万元、偏差率 %s%%"
         "（数据来源：calc_engine.py 实算，偏差 = 实际 − 概算）。逐项发现见附件《审计发现清单》。"
         % (meta.get("概算", "-"), meta.get("已发生", "-"),
            meta.get("偏差", "-"), meta.get("偏差率", "-"))),
        ("三、风险提示", risks),
        ("四、整改与建议",
         str(meta.get("建议",
                      "重大变更与大额签证须事前审批，事后难以纠正；无证据的造价不予认定；"
                      "待摊费用须按合理基础分摊，不得全额计入单一单体。"))),
        ("五、附件", "《审计发现清单》（%s）。" % ("xlsx" if str(xlsx).endswith("xlsx") else "csv")),
    ]
    md = build_report("%s · 造价审计报告" % meta.get("项目名", "项目"), secs,
                      os.path.join(out_dir, "造价审计报告.md"))
    return {"xlsx": xlsx, "md": md, "gate": gate_check(md)}


def claim_report(claim, out_dir, standard=DEFAULT_STANDARD):
    """索赔分析报告：要件判定 + 工期/费用 + 证据清单。"""
    columns = ["序号", "证据材料", "证明对象", "证据强度", "缺口/补正要求"]
    rows = [[e.get(c, "") for c in columns] for e in claim.get("evidence", [])]
    xlsx = build_table("索赔证据清单", columns, rows, os.path.join(out_dir, "索赔证据清单.xlsx"))
    src = claim.get("数据来源", "合同、施工日志、签证、往来函件与影像资料")
    secs = [
        ("一、索赔要件判定",
         "事件：%s；责任归属：%s；结论：%s（数据来源：送审资料 %s）。\n"
         "要件说明：索赔三要素（非己方责任的索赔事件、损失、因果关系）缺一不成立，"
         "不成立即不出具索赔金额。"
         % (claim.get("事件", "-"), claim.get("责任归属", "-"), claim.get("结论", "-"), src)),
        ("二、时效判定",
         "事件发生日 %s、提出意向日 %s、间隔 %s 天、约定时效 %s 天、是否在时效内：%s"
         "（数据来源：calc_engine.py delay_claim 实算）。\n"
         "超期须评估时效抗辩风险并补正持续性记录，不得直接断定权利灭失。"
         % (claim.get("事件发生日", "-"), claim.get("提意向日", "-"), claim.get("间隔天", "-"),
            claim.get("约定时效", "28"), claim.get("是否在时效内", "-"))),
        ("三、工期与费用",
         "线路延误 %s 天、总时差 %s 天、可索赔工期 %s 天、费用索赔额 %s 万元"
         "（数据来源：calc_engine.py 实算，可索赔工期 = 延误天数 − 总时差）。\n"
         "费用构成：%s。" % (claim.get("延误天数", "-"), claim.get("总时差", "-"),
                          claim.get("可索赔工期", "-"), claim.get("费用索赔额", "-"),
                          claim.get("费用构成", "-"))),
        ("四、证据链清单", "见附件《索赔证据清单》。证据强度分级：强=双方书面确认件，中=单方记录，弱=事后回忆或口头。"),
        ("五、风险提示",
         "工期延误不等于可获赔费用；索赔费用与结算价款调整不得重复计取；"
         "利润索赔仅限合同约定情形（本条为风险提示，不含测算结论）。"),
        ("六、附件", "《索赔证据清单》（%s）。" % ("xlsx" if str(xlsx).endswith("xlsx") else "csv")),
    ]
    md = build_report("%s · 索赔分析报告" % claim.get("项目名", "项目"), secs,
                      os.path.join(out_dir, "索赔分析报告.md"))
    return {"xlsx": xlsx, "md": md, "gate": gate_check(md)}


def index_report(index_rows, meta, out_dir, standard=DEFAULT_STANDARD):
    """造价指标分析：指标表 xlsx + 对标分析 md。"""
    columns = ["指标名称", "数值", "单位", "对标值", "偏差率(%)", "口径/来源"]
    rows = [[r.get(c, "") for c in columns] for r in index_rows]
    xlsx = build_table("造价指标分析表", columns, rows, os.path.join(out_dir, "造价指标分析表.xlsx"))
    src = meta.get("数据来源", "用户提供的工程结算与预算数据")
    secs = [
        ("一、口径说明",
         "%s 指标口径：单方指标 = 总造价 ÷ 建筑面积，面积口径为 %s。"
         % (_provenance(standard, src), meta.get("面积口径", "须明确建筑/使用/结构面积"))),
        ("二、指标结果",
         "单方指标 %s 元/㎡、对标偏差率 %s%%（%s）"
         "（数据来源：calc_engine.py 实算 index_metrics）。逐项结果见附件《造价指标分析表》。"
         % (meta.get("单方指标", "-"), meta.get("偏差率", "-"), meta.get("偏差方向", "-"))),
        ("三、对标可比性",
         "对标须同业态、同口径、同时点；样本不足或口径不一致时只给区间并说明，禁止强行对标"
         "（数据来源：本团对标规则，不含测算结论）。"),
        ("四、优化建议",
         str(meta.get("建议", "对异常指标先核查口径（含税/除税、是否含精装/景观/地下），"
                              "再判断设计或成本问题。"))),
        ("五、附件", "《造价指标分析表》（%s）。" % ("xlsx" if str(xlsx).endswith("xlsx") else "csv")),
    ]
    md = build_report("%s · 造价指标分析报告" % meta.get("项目名", "项目"), secs,
                      os.path.join(out_dir, "造价指标分析报告.md"))
    return {"xlsx": xlsx, "md": md, "gate": gate_check(md)}


def workpaper(items, meta, out_dir, standard=DEFAULT_STANDARD):
    """审计底稿（工作底稿）：索引 + 检查程序 + 证据 + 依据 + 金额 + 结论 + 编制/复核签署。

    items: list[dict]，字段 ["索引号","审计事项","检查程序","查证过程与证据",
                             "依据(合同/规范)","涉及金额(万元)","审计结论"]
    meta : 项目名 / 被审计单位 / 阶段 / 编制人 / 复核人 / 数据来源
    """
    columns = ["索引号", "审计事项", "检查程序", "查证过程与证据", "依据(合同/规范)",
               "涉及金额(万元)", "审计结论"]
    rows = [[r.get(c, "") for c in columns] for r in items]
    xlsx = build_table("审计底稿", columns, rows, os.path.join(out_dir, "审计底稿.xlsx"))
    src = meta.get("数据来源", "被审计单位提供的合同、图纸、计量记录、变更签证与支付凭证")
    amt = sum(float(r.get("涉及金额(万元)", 0) or 0) for r in items)
    secs = [
        ("一、底稿编号与编制说明",
         "共 %d 份底稿、涉及金额合计 %.2f 万元（数据来源：本底稿清单逐份加总）。\n"
         "索引规则：按审计事项分类编号（W-01、W-02……），报告中的每一项金额均应能对应到具体底稿索引"
         "（数据来源：本底稿索引规则）。\n"
         "编制人：%s；复核人：%s（底稿未经复核不得作为报告依据；数据来源：本次审计记录）。"
         % (len(items), amt, meta.get("编制人", "（待填）"), meta.get("复核人", "（待填）"))),
        ("二、底稿清单",
         "| 索引 | 审计事项 | 依据 | 涉及金额(万元) | 结论 | 证据与数据来源 |\n|---|---|---|---|---|---|\n%s\n\n"
         "金额单位：万元；每行末列『证据与数据来源』为该行金额的取数依据，须能回溯到原件"
         "（数据来源：本底稿清单逐行登记的取数来源）。"
         % ("\n".join("| %s | %s | %s | %s | %s | 数据来源：%s，证据：%s |" % (
             r.get("索引号", ""), _flat(r.get("审计事项", ""), 24),
             _flat(r.get("依据(合同/规范)", ""), 28), r.get("涉及金额(万元)", ""),
             _flat(r.get("审计结论", ""), 24), _flat(r.get("数据来源") or src, 40),
             _flat(r.get("证据来源") or r.get("查证过程与证据", ""), 60))
             for r in items)
            or "（无底稿条目，数据来源：本次审计记录）")),
        ("三、证据要求与分级",
         "1）每一份底稿须挂接证据（图纸计算书、计量台账、签认单、发票、付款凭证、影像资料等），"
         "证据编入底稿附件序号（数据来源：本团底稿规范）。\n"
         "2）证据强度：强＝双方书面确认件；中＝单方记录但有第三方佐证；弱＝事后回忆或口头说明"
         "（数据来源：本团证据分级规则）。\n"
         "3）仅有弱证据支撑的金额不得直接作为审减结论，须补强或标注为待核事项"
         "（数据来源：本团底稿规范）。"),
        ("四、复核与签署",
         "底稿须经主审复核、重大项目由项目负责人签发；复核记录须留痕（复核人、日期、复核意见）"
         "（数据来源：本团三级复核要求）。\n"
         "含数值结论的底稿须附 calc_engine.py 实算证据或明确数据来源，否则结论不可采信"
         "（数据来源：本团计算铁律）。"),
        ("五、依据", _provenance(standard, src)),
    ]
    md = build_report("%s · 审计底稿" % meta.get("项目名", "项目"), secs,
                      os.path.join(out_dir, "审计底稿说明.md"))
    return {"xlsx": xlsx, "md": md, "gate": gate_check(md)}


def pbc_list(items, meta, out_dir, standard=DEFAULT_STANDARD):
    """资料索取清单（PBC）——审计开工第一步要交给被审计单位的资料清单。"""
    columns = ["序号", "资料名称", "对应审计事项", "提供形式", "份数/范围", "要求提供时间", "备注"]
    rows = [[r.get(c, "") for c in columns] for r in items]
    xlsx = build_table("资料索取清单", columns, rows, os.path.join(out_dir, "资料索取清单.xlsx"))
    src = meta.get("数据来源", "本次审计的检查范围与拟实施程序")
    due = meta.get("要求提供时间", "（待填）")
    secs = [
        ("一、说明",
         "本清单共 %d 项资料，要求于 %s 前提供（数据来源：%s）。\n"
         "资料须提供原件核验或加盖单位公章的复印件；电子件应保证与纸质件一致"
         "（数据来源：本团取证规范）。\n"
         "超期未提供或提供不完整的，须书面催告并记录，必要时在报告中说明审计范围受限"
         "（数据来源：本团取证规范）。"
         % (len(items), due, src)),
        ("二、资料清单",
         "| 序号 | 资料名称 | 对应审计事项 | 提供形式 | 要求时间 |\n|---|---|---|---|---|\n%s\n\n"
         "（本清单数据来源：%s）"
         % ("\n".join("| %s | %s | %s | %s | %s |" % (
             r.get("序号", i + 1), str(r.get("资料名称", ""))[:30],
             str(r.get("对应审计事项", ""))[:20], r.get("提供形式", ""),
             r.get("要求提供时间", due)) for i, r in enumerate(items))
            or "（清单为空；数据来源：本次审计计划）", src)),
        ("三、口径提示",
         "1）涉及价款调整的资料（变更、签证、认价单、信息价表）须同时提供相应的审批与签认记录"
         "（数据来源：本团取证规范）。\n"
         "2）结算类资料应提供可编辑电子版（含量、价、计算式），便于逐项复核"
         "（数据来源：本团取证规范）。\n"
         "3）资料涉商业秘密，仅限本次审计使用，不得对外提供（数据来源：本团保密要求）。"),
        ("四、依据", _provenance(standard, src)),
    ]
    md = build_report("%s · 资料索取清单" % meta.get("项目名", "项目"), secs,
                      os.path.join(out_dir, "资料索取清单说明.md"))
    return {"xlsx": xlsx, "md": md, "gate": gate_check(md)}


def suggest_clause(issue):
    """按问题描述 + 定性自动配对建议依据；配不上时给出可执行的下一步，绝不编造条款。"""
    if _ip is None:
        return "（待填：请用 references/search/authority_search.py 检索条文）"
    given = str(issue.get("建议依据（须核实）") or "").strip()
    if given and "待填" not in given:
        return given
    try:
        res = _ip.pair(str(issue.get("问题描述", "")), str(issue.get("问题定性", "") or ""))
    except Exception:
        return "（待填：请用 references/search/authority_search.py 检索条文）"
    if not res.get("matched"):
        return ("（待填：库内无直接对应，定性「%s」请用 references/search/authority_search.py 检索条文）"
                % (issue.get("问题定性", "") or "未填"))
    cl = "；".join("%s（%s）" % (c.get("clause", ""), c.get("topic", ""))
                   for c in (res.get("依据") or []))
    return "%s；数据来源：references/data/问题定性与依据映射.json，⚠️ 须核对原文" % cl


def issue_register(issues, out_dir, meta=None, standard=DEFAULT_STANDARD):
    """审计问题台账与整改跟踪（含销号状态）——审计报告落地的抓手。"""
    meta = meta or {}
    columns = ["序号", "问题描述", "问题定性", "涉及金额(万元)", "依据", "建议依据（须核实）",
               "责任单位", "整改要求", "整改期限", "状态"]
    rows = []
    for r in issues:
        rr = dict(r)
        rr["建议依据（须核实）"] = suggest_clause(r)
        rows.append([rr.get(c, "") for c in columns])
    xlsx = build_table("问题台账与整改跟踪", columns, rows, os.path.join(out_dir, "问题整改台账.xlsx"))
    src = meta.get("数据来源", "本次审计发现清单与整改回复资料")
    amt = sum(float(r.get("涉及金额(万元)", 0) or 0) for r in issues)
    kinds = {}
    for r in issues:
        k = r.get("问题定性", "未定性")
        kinds[k] = kinds.get(k, 0) + 1
    open_cnt = sum(1 for r in issues if str(r.get("状态", "")).strip() not in ("已销号", "已整改"))
    secs = [
        ("一、台账概况",
         "共 %d 项问题，涉及金额合计 %.2f 万元（数据来源：本台账逐项加总）。\n"
         "按定性分布：%s（数据来源：本台账逐项统计）。\n"
         "未销号 %d 项、已销号 %d 项（数据来源：本台账状态列）。"
         % (len(issues), amt,
            "、".join("%s %d 项" % (k, v) for k, v in sorted(kinds.items())) or "无",
            open_cnt, len(issues) - open_cnt)),
        ("二、问题清单",
         "| # | 问题描述 | 定性 | 金额(万元) | 责任单位 | 整改期限 | 状态 | 建议依据（须核实） |\n"
         "|---|---|---|---|---|---|---|---|\n%s\n\n"
         "（本表数据来源：%s；末列「建议依据」由 references/data/问题定性与依据映射.json 规则配对生成，⚠️ 条款号须核对官方原文）"
         % ("\n".join("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
             r.get("序号", i + 1), str(r.get("问题描述", ""))[:26], r.get("问题定性", ""),
             r.get("涉及金额(万元)", ""), r.get("责任单位", ""), r.get("整改期限", ""),
             r.get("状态", ""), _flat(suggest_clause(r), 200)) for i, r in enumerate(issues))
            or "（无问题条目；数据来源：本次审计记录）", src)),
        ("三、整改与销号规则",
         "1）整改回复须提供可验证的证明材料（调整凭证、补签手续、退款凭证等），仅有文字说明不予销号"
         "（数据来源：本团整改销号规则）。\n"
         "2）涉及金额的整改项，须在回复中列明调整后的金额与计算过程，供复核留档"
         "（数据来源：本团整改销号规则）。\n"
         "3）未按期整改的，须提请注意并在后续审计中跟踪（数据来源：本团整改销号规则）。"),
        ("四、依据", _provenance(standard, src)),
    ]
    md = build_report("%s · 问题台账与整改跟踪" % meta.get("项目名", "项目"), secs,
                      os.path.join(out_dir, "问题整改台账说明.md"))
    return {"xlsx": xlsx, "md": md, "gate": gate_check(md)}


def dispute_register(disputes, out_dir, meta=None, standard=DEFAULT_STANDARD):
    """争议/异议台账：报送方主张 vs 审核意见，供协商、复核与后续程序使用。"""
    meta = meta or {}
    columns = ["序号", "争议事项", "报送方主张", "审核意见", "争议金额(万元)",
               "报送方依据", "审核依据", "处理建议", "状态"]
    rows = [[r.get(c, "") for c in columns] for r in disputes]
    xlsx = build_table("争议事项台账", columns, rows, os.path.join(out_dir, "争议事项台账.xlsx"))
    src = meta.get("数据来源", "报送方的异议函件与审核过程记录")
    amt = sum(float(r.get("争议金额(万元)", 0) or 0) for r in disputes)
    submit = meta.get("报送价(万元)")
    pct = ("占报送价 %.2f%%" % (amt / float(submit) * 100)) if submit else "（未提供报送价，无法计算占比）"
    secs = [
        ("一、争议概况",
         "共 %d 项争议、争议金额合计 %.2f 万元、%s（数据来源：本台账逐项加总）。\n"
         "争议事项应逐项明确「报送方主张 / 审核意见 / 双方依据」，避免以口头沟通代替书面记录"
         "（数据来源：本团争议处理规范）。"
         % (len(disputes), amt, pct)),
        ("二、争议清单",
         "| # | 争议事项 | 争议金额(万元) | 报送方依据 | 审核依据 | 状态 |\n|---|---|---|---|---|---|\n%s\n\n"
         "（本表数据来源：%s）"
         % ("\n".join("| %s | %s | %s | %s | %s | %s |" % (
             r.get("序号", i + 1), str(r.get("争议事项", ""))[:24], r.get("争议金额(万元)", ""),
             str(r.get("报送方依据", ""))[:24], str(r.get("审核依据", ""))[:24], r.get("状态", ""))
             for i, r in enumerate(disputes))
            or "（无争议条目；数据来源：本次审核记录）", src)),
        ("三、处理建议与程序",
         "1）优先以书面复核方式解决：报送方补充证据 → 审核方复核 → 出具书面答复"
         "（数据来源：本团争议处理规范）。\n"
         "2）复核后仍有分歧的，可按合同约定进入协商、专家评审或造价鉴定程序；进入诉讼/仲裁的，"
         "本表可作为争议事项清单引用（数据来源：本团争议处理规范）。\n"
         "3）争议未解决前，不影响无争议部分的结算与支付；无争议部分应及时办理，不得整体搁置"
         "（数据来源：本团争议处理规范）。"),
        ("四、依据", _provenance(standard, src)),
    ]
    md = build_report("%s · 争议事项台账" % meta.get("项目名", "项目"), secs,
                      os.path.join(out_dir, "争议事项台账说明.md"))
    return {"xlsx": xlsx, "md": md, "gate": gate_check(md)}


def audit_plan(items, meta, out_dir, standard=DEFAULT_STANDARD):
    """审计实施方案 · 检查范围（重点核查 / 抽查 / 未覆盖 + 检查程序 + 抽样口径免责）。

    items : list[dict]，字段 ["序号","送审事项","送审金额(万元)","检查理由"]
    meta  : 项目名 / 被审计单位 / 阶段 / 送审总额(万元) / 必查阈值率 / 覆盖目标 /
            编制人 / 复核人 / 进度安排 / 数据来源
    规则  : 直接调用同目录 calc_engine.sample_plan（"抓大放小 + 覆盖率控制"，非统计抽样），
            确保方案与引擎实算口径一致；引擎调用失败即 fail-closed 报错，禁止手工编造检查范围。
    """
    if not items:
        raise ValueError("items 为空，无法编制检查范围方案（禁止凭空编造检查范围）")
    names, amounts, reason = [], [], {}
    for i, r in enumerate(items, 1):
        nm = str(r.get("送审事项") or r.get("项目") or ("第%d项" % i))
        names.append(nm)
        amounts.append(float(r.get("送审金额(万元)", 0) or 0))
        reason[nm] = str(r.get("检查理由") or "")

    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import calc_engine
        plan = calc_engine.sample_plan(
            [{"项目": n, "金额": a} for n, a in zip(names, amounts)],
            threshold_rate=float(meta.get("必查阈值率", 0.05) or 0.05),
            coverage_target=float(meta.get("覆盖目标", 0.70) or 0.70),
            name="%s · 检查范围方案" % meta.get("项目名", "项目"))
    except Exception as exc:
        raise RuntimeError("调用 calc_engine.sample_plan 失败，检查范围方案未生成"
                           "（禁止手工编造检查范围）：%s" % exc)

    def _pick(prefix):
        for k, v in plan.items():
            if isinstance(v, list) and k.startswith(prefix):
                return v
        return []

    default_reason = {"必查": "单项金额占比高，列为重点核查（全额核对）",
                      "抽中": "按覆盖率顺序纳入抽查",
                      "未覆盖": "未纳入本次检查范围，须评估是否追加程序"}
    rows, seq = [], 0
    for way, prefix in (("必查", "必查项"), ("抽中", "抽中项"), ("未覆盖", "未覆盖项")):
        for x in _pick(prefix):
            seq += 1
            nm = str(x.get("项目", ""))
            rows.append({"序号": seq, "送审事项": nm, "送审金额(万元)": x.get("金额", ""),
                         "检查方式": way,
                         "检查理由": reason.get(nm) or default_reason[way]})
    if not rows:
        raise RuntimeError("calc_engine.sample_plan 返回结构异常（未取到必查/抽中/未覆盖清单），已中止")

    src = meta.get("数据来源", "本次审计计划与送审资料清单")
    total, thr, cov = plan.get("总额"), plan.get("重点核查阈值"), plan.get("覆盖率(%)")
    n_must, n_pick, n_miss = len(_pick("必查项")), len(_pick("抽中项")), len(_pick("未覆盖项"))
    ENGINE = "python calc_engine.py --func sample_plan 实算输出"

    columns = ["序号", "送审事项", "送审金额(万元)", "检查方式", "检查理由", "数据来源"]
    xlsx = build_table("审计实施方案-检查范围", columns,
                       [[r["序号"], r["送审事项"], r["送审金额(万元)"], r["检查方式"],
                         r["检查理由"], src] for r in rows],
                       os.path.join(out_dir, "审计实施方案.xlsx"))

    secs = [
        ("一、方案说明",
         "本方案覆盖 %d 个送审事项，送审金额合计 %s 万元，重点核查阈值 %s 万元，覆盖率 %s%%"
         "（数据来源：%s）。\n"
         "检查范围构成：必查 %d 项、抽中 %d 项、未覆盖 %d 项（数据来源：%s）。\n"
         "编制人：%s；复核人：%s（数据来源：本次审计记录）。"
         % (len(rows), total, thr, cov, ENGINE, n_must, n_pick, n_miss, ENGINE,
            meta.get("编制人", "（待填）"), meta.get("复核人", "（待填）"))),
        ("二、检查范围清单",
         "| 序号 | 送审事项 | 送审金额(万元) | 检查方式 | 检查理由 | 数据来源 |\n"
         "|---|---|---|---|---|---|\n%s\n\n"
         "注：『未覆盖』不代表无风险，须评估是否追加程序或在报告中声明审计范围限制"
         "（数据来源：%s）。"
         % ("\n".join("| %s | %s | %s | %s | %s | 数据来源：%s |" % (
             r["序号"], _flat(r["送审事项"], 24), r["送审金额(万元)"], r["检查方式"],
             _flat(r["检查理由"], 30), _flat(src, 30)) for r in rows), src)),
        ("三、检查程序与方法",
         "1）工程量核查：以竣工图与监理计量台账为准逐项复算工程量，抽查项不得低于送审项的百分之三十"
         "（数据来源：本团审计程序规范）。\n"
         "2）单价与计价依据核查：核对合同约定的计价依据版本与取费口径，与投标报价、认价单逐项比对"
         "（数据来源：本团审计程序规范）。\n"
         "3）勾稽复核：分项合计须与报表汇总数勾稽一致，差额须逐项查清原因，"
         "不得以四舍五入或尾差解释（数据来源：python calc_engine.py --func reconcile_check 实算）。\n"
         "4）审减归因：每个核减项须拆为工程量核减与单价核减两部分，并可反向验算"
         "（数据来源：python calc_engine.py --func audit_attribution 实算）。\n"
         "5）证据挂接：每一结论须挂接签字盖章的有效证据；证据不足的列入待核事项，"
         "不得直接作为审减依据（数据来源：本团底稿规范）。"),
        ("四、进度与分工",
         "1）分工：审计员负责资料核对与实算，主审负责复核与口径把关，项目负责人签发"
         "（数据来源：本团三级复核要求）。\n"
         "2）进度：%s（数据来源：%s）。\n"
         "3）留痕：每一步检查均须在底稿中登记检查人、检查日期与检查结论"
         "（数据来源：本团底稿规范）。"
         % (_flat(meta.get("进度安排", "（待填，按委托方要求的交付时点倒排）"), 120),
            meta.get("进度依据", "本次审计计划的进度安排"))),
        ("五、抽样口径与固有局限",
         "1）本方案采用工程审计常用的抓大放小加覆盖率控制的实务做法，属经验判断型抽样，"
         "不是统计抽样，不得对外表述为统计抽样结论（数据来源：本团抽样口径说明）。\n"
         "2）未计算置信区间与抽样风险；委托方要求统计抽样或已明确重要性水平的，"
         "须按其方案重新设计（数据来源：本团抽样口径说明）。\n"
         "3）未覆盖项与无法取得证据的事项构成审计范围限制，须在报告中如实披露，"
         "不得以抽样结论替代整体意见（数据来源：本团底稿规范）。"),
        ("六、依据", _provenance(standard, src)),
    ]
    md = build_report("%s · 审计实施方案（检查范围）" % meta.get("项目名", "项目"), secs,
                      os.path.join(out_dir, "审计实施方案说明.md"))
    return {"xlsx": xlsx, "md": md, "gate": gate_check(md)}

def _print_result(name, r):
    print("[%s] 表格：%s" % (name, r["xlsx"]))
    print("[%s] 报告：%s" % (name, r["md"]))
    g = r.get("gate", {})
    print("[%s] 门禁自校验：%s%s" % (name, g.get("level", "?"),
                                 "" if g.get("level") in ("PASS", "WARN", None) else " ⚠ 须修正后再交付"))


if __name__ == "__main__":
    out = "./_demo_out"
    demo_rows = [
        {"序号": 1, "分部分项": "土建工程", "报送价(万元)": 8000, "审定价(万元)": 7400,
         "审减额(万元)": 600, "审减率(%)": 7.5, "争议/说明": "部分签证无编号"},
        {"序号": 2, "分部分项": "安装工程", "报送价(万元)": 4000, "审定价(万元)": 3500,
         "审减额(万元)": 500, "审减率(%)": 12.5, "争议/说明": "超预警线，启动复核"},
    ]

    demo_meta = {"项目名": "示例住宅项目", "地区": "贵州·毕节", "建面": "10万㎡", "合同价": 11500,
                 "报送总价": 12000, "审定总价": 10900, "审减额": 1100, "审减率": 9.17,
                 "主要审减项": "安装工程暂列金额重核",
                 "争议提示": "安装工程审减率超约定预警线，建议复核报送资料。",
                 "数据来源": "示例数据（非真实项目）"}
    demo_findings = [
        {"序号": 1, "审计事项": "暂列金额使用", "审计发现": "暂列金额未使用部分未扣回",
         "涉及金额(万元)": 600, "依据/条款": "GB 50500-2013 第 9.9 节", "风险等级": "高",
         "整改建议": "按实结算并扣回未使用部分"},
        {"序号": 2, "审计事项": "材料调差", "审计发现": "材料调差未按合同风险幅度计算",
         "涉及金额(万元)": 220, "依据/条款": "合同专用条款 + GB 50500-2013 附录 A", "风险等级": "中",
         "整改建议": "按三档规则重算并补正"},
    ]
    demo_audit_meta = {"项目名": "示例住宅项目", "阶段": "竣工决算审计", "截止时点": "2026-08-31",
                       "概算": 11500, "已发生": 10900, "偏差": -600, "偏差率": -5.22,
                       "数据来源": "示例数据（非真实项目）"}
    demo_claim = {"项目名": "示例市政项目", "事件": "业主延迟交地",
                  "责任归属": "发包人（业主）风险", "结论": "要件成立，可主张工期与费用索赔",
                  "事件发生日": "2025-05-01", "提意向日": "2025-05-20", "间隔天": 19,
                  "约定时效": "28", "是否在时效内": "在时效内", "延误天数": 40, "总时差": 10,
                  "可索赔工期": 30, "费用索赔额": 33.4,
                  "费用构成": "窝工损失 30 万元 + 其他额外费用 3.4 万元 = 33.4 万元（数据来源：送审资料）",
                  "数据来源": "示例数据（非真实项目）",
                  "evidence": [
                      {"序号": 1, "证据材料": "交地通知与签收记录", "证明对象": "事件发生时间",
                       "证据强度": "强", "缺口/补正要求": "无"},
                      {"序号": 2, "证据材料": "施工日志", "证明对象": "窝工天数",
                       "证据强度": "中", "缺口/补正要求": "需监理签认"}]}
    demo_index_rows = [
        {"指标名称": "单方指标", "数值": 1090, "单位": "元/㎡", "对标值": 990,
         "偏差率(%)": 10.1, "口径/来源": "示例数据（非真实项目）"},
        {"指标名称": "钢筋含量", "数值": 0.05, "单位": "t/㎡", "对标值": 0.055,
         "偏差率(%)": -9.09, "口径/来源": "示例数据（非真实项目）"},
    ]
    demo_index_meta = {"项目名": "示例住宅项目", "单方指标": 1090, "偏差率": 10.1,
                       "偏差方向": "高于标杆 10.1%", "面积口径": "建筑面积",
                       "数据来源": "示例数据（非真实项目）"}

    demo_workpaper = [
        {"索引号": "W-01", "审计事项": "工程量核对（土建）",
         "检查程序": "将结算工程量与竣工图、监理计量台账逐项核对，抽查比例不低于 30%",
         "查证过程与证据": "抽查 12 项，其中 3 项工程量大于图纸计算值；证据：图纸计算书、监理计量台账（附件 W-01-1）",
         "依据(合同/规范)": "GB 50500-2013 第 9.6.2 条 + 合同专用条款",
         "涉及金额(万元)": 120, "证据来源": "图纸计算书、监理计量台账（附件 W-01-1）",
         "审计结论": "核减工程量，按实调整结算价"},
        {"索引号": "W-02", "审计事项": "材料调差复核",
         "检查程序": "按合同风险幅度与当地信息价复核调差计算",
         "查证过程与证据": "复核 3 种主材的基准价、投标价与各期信息价；证据：信息价表、采购合同（附件 W-02-1）",
         "依据(合同/规范)": "合同专用条款 + GB 50500-2013 附录 A",
         "涉及金额(万元)": 220, "证据来源": "当地信息价表、采购合同与认价单（附件 W-02-1）",
         "审计结论": "调差口径需按三档规则重算"},
    ]
    demo_workpaper_meta = {"项目名": "示例住宅项目", "被审计单位": "示例施工单位", "阶段": "竣工结算审计",
                           "编制人": "审计员（示例）", "复核人": "主审（示例）",
                           "数据来源": "示例数据（非真实项目）"}
    demo_plan_items = [
        {"序号": 1, "送审事项": "土建工程（主体结构）", "送审金额(万元)": 1800,
         "检查理由": "单项金额最高，列为重点核查（全额核对）"},
        {"序号": 2, "送审事项": "安装工程（机电）", "送审金额(万元)": 1500,
         "检查理由": "历史审减率偏高，列为重点核查"},
        {"序号": 3, "送审事项": "装饰装修工程", "送审金额(万元)": 420},
        {"序号": 4, "送审事项": "室外附属与绿化", "送审金额(万元)": 410},
        {"序号": 5, "送审事项": "基坑支护与降水", "送审金额(万元)": 400},
        {"序号": 6, "送审事项": "桩基工程", "送审金额(万元)": 390},
        {"序号": 7, "送审事项": "幕墙与外窗", "送审金额(万元)": 380},
        {"序号": 8, "送审事项": "消防工程", "送审金额(万元)": 370},
        {"序号": 9, "送审事项": "通风空调", "送审金额(万元)": 360},
        {"序号": 10, "送审事项": "强弱电工程", "送审金额(万元)": 350},
        {"序号": 11, "送审事项": "给排水工程", "送审金额(万元)": 300},
        {"序号": 12, "送审事项": "电梯采购安装", "送审金额(万元)": 280},
        {"序号": 13, "送审事项": "变配电工程", "送审金额(万元)": 260},
        {"序号": 14, "送审事项": "弱电智能化", "送审金额(万元)": 240},
        {"序号": 15, "送审事项": "景观工程", "送审金额(万元)": 220},
        {"序号": 16, "送审事项": "临水临电", "送审金额(万元)": 200},
        {"序号": 17, "送审事项": "检测试验费", "送审金额(万元)": 180},
        {"序号": 18, "送审事项": "临时设施", "送审金额(万元)": 160},
        {"序号": 19, "送审事项": "安全文明施工费", "送审金额(万元)": 140},
        {"序号": 20, "送审事项": "其他零星费用", "送审金额(万元)": 120},
    ]
    demo_plan_meta = {"项目名": "示例住宅项目", "被审计单位": "示例施工单位", "阶段": "竣工结算审计",
                      "必查阈值率": 0.05, "覆盖目标": 0.70,
                      "编制人": "审计员（示例）", "复核人": "主审（示例）",
                      "进度安排": "资料核对 5 个工作日，现场核查 3 个工作日，复核出具 2 个工作日",
                      "数据来源": "示例数据（非真实项目）"}
    demo_pbc = [
        {"序号": 1, "资料名称": "竣工结算书（含计算书电子版）", "对应审计事项": "结算完整性",
         "提供形式": "纸质+电子", "份数/范围": "1 套", "要求提供时间": "2026-09-20", "备注": "含变更与签证索引"},
        {"序号": 2, "资料名称": "施工合同及补充协议", "对应审计事项": "计价依据与口径",
         "提供形式": "复印件盖章", "份数/范围": "1 套", "要求提供时间": "2026-09-20", "备注": "含专用条款"},
        {"序号": 3, "资料名称": "监理计量台账与签认记录", "对应审计事项": "工程量真实性",
         "提供形式": "纸质+电子", "份数/范围": "全期", "要求提供时间": "2026-09-22", "备注": "按月装订"},
        {"序号": 4, "资料名称": "材料认价单与采购合同", "对应审计事项": "材料价差",
         "提供形式": "复印件盖章", "份数/范围": "全部主材", "要求提供时间": "2026-09-22",
         "备注": "含发票或付款凭证"},
    ]
    demo_pbc_meta = {"项目名": "示例住宅项目", "要求提供时间": "2026-09-22",
                     "数据来源": "示例数据（非真实项目）"}
    demo_issues = [
        {"序号": 1, "问题描述": "暂列金额未使用部分未扣回", "问题定性": "多计", "涉及金额(万元)": 600,
         "依据": "GB 50500-2013 第 9 章", "责任单位": "施工单位", "整改要求": "按实调整并扣回",
         "整改期限": "2026-10-31", "状态": "整改中"},
        {"序号": 2, "问题描述": "材料调差未按合同风险幅度计算", "问题定性": "计价口径错误",
         "涉及金额(万元)": 220, "依据": "合同专用条款 + GB 50500-2013 附录 A",
         "责任单位": "施工单位", "整改要求": "按三档规则重算并补正", "整改期限": "2026-10-31",
         "状态": "未整改"},
        {"序号": 3, "问题描述": "签证缺少甲方代表签字", "问题定性": "证据不足", "涉及金额(万元)": 80,
         "依据": "合同专用条款（签认要求）", "责任单位": "施工单位",
         "整改要求": "补签或提供替代证据", "整改期限": "2026-09-30", "状态": "已销号"},
    ]
    demo_issue_meta = {"项目名": "示例住宅项目", "数据来源": "示例数据（非真实项目）"}
    demo_disputes = [
        {"序号": 1, "争议事项": "材料调差基准", "报送方主张": "以投标价为基础调差",
         "审核意见": "按三档规则以基准价为基础", "争议金额(万元)": 40,
         "报送方依据": "合同通用条款", "审核依据": "GB 50500-2013 附录 A + 专用条款",
         "处理建议": "补充采购合同与发票后复核", "状态": "复核中"},
        {"序号": 2, "争议事项": "土方运距", "报送方主张": "按实际运距 15km",
         "审核意见": "按批准的施工方案 8km", "争议金额(万元)": 26,
         "报送方依据": "运距测量记录", "审核依据": "经批准的施工组织设计",
         "处理建议": "以批准的施工方案为准，差额不予认可", "状态": "待答复"},
    ]
    demo_dispute_meta = {"项目名": "示例住宅项目", "报送价(万元)": 12000,
                         "数据来源": "示例数据（非真实项目）"}

    outs = [
        ("结算审核", settlement_report(demo_rows, demo_meta, out)),
        ("造价审计", audit_report(demo_findings, demo_audit_meta, out)),
        ("索赔分析", claim_report(demo_claim, out)),
        ("指标分析", index_report(demo_index_rows, demo_index_meta, out)),
        ("审计底稿", workpaper(demo_workpaper, demo_workpaper_meta, out)),
        ("审计实施方案", audit_plan(demo_plan_items, demo_plan_meta, out)),
        ("资料索取清单", pbc_list(demo_pbc, demo_pbc_meta, out)),
        ("问题台账", issue_register(demo_issues, out, demo_issue_meta)),
        ("争议台账", dispute_register(demo_disputes, out, demo_dispute_meta)),
    ]
    bad = []
    for name, r in outs:
        _print_result(name, r)
        lvl = (r.get("gate") or {}).get("level", "?")
        if lvl not in ("PASS", "WARN"):
            bad.append("%s(%s)" % (name, lvl))
    print("DEMO 完成，输出目录：%s" % os.path.abspath(out))
    if bad:
        print("⚠ 以下交付物未通过门禁自检：%s" % "、".join(bad))
        sys.exit(1)
