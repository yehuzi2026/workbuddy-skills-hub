# -*- coding: utf-8 -*-
"""工程造价审计AI助手 · 全工具冒烟自检（真实覆盖每个脚本，含门禁误伤/漏放回归）。

覆盖：
  1) calc_engine.py --selftest          计算引擎断言（含边界与 fail-closed）
  2) staleness_check.py --days 3650     法规时效巡检（宽限期）
  3) authority_search.py "工程量偏差"    离线条文检索必须命中
  4) authority_search.py "不存在的词xyz" 库外必须未命中并给出降级提示
  5) gate.py emit --file（合规稿）        必须 PASS（退出码 0）
  6) gate.py emit --file（含日期稿）      必须 PASS（回归：日期不得被判成编造数字）
  7) gate.py emit --file（无出处数字稿）  必须 ERROR 拦截（退出码 1）
  8) gate.py emit --file（模糊+数字稿）   必须 ERROR 拦截（退出码 1）
  9) gate.py emit --file（引用+来源稿）   必须 PASS
 10) ingest.py 读 csv / build_rates 生成费率文件
 11) deliverable.py 生成 9 类交付物并逐份过门禁（含审计底稿 / 审计实施方案 / 资料索取清单 / 问题台账 / 争议台账）
 12) reconcile.py 对量差异分析（量差 / 价差 / 漏项 / 增项四项闭合校验）
  13) project_template.py 生成整套审计项目档案（六卷 + 项目索引）并逐份过门禁；模板导出必须为纯 UTF-8（--save-template）
 14) issue_pair.py 问题定性 → 条款依据配对（命中 / 库外降级）
 15) project_template.py --portfolio 多项目总台账（扫描项目信息.json 汇总）
 16) content_check.py --quick 全包完整性
用法：python e2e_smoke_test.py（共 54 项断言）
退出码：0 = 全部通过。
"""
import os, sys, shutil, subprocess, json

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
GATE = os.path.join(HERE, "references", "search", "gate.py")
TMP = os.path.join(HERE, "_smoke_tmp")   # 放在包内，避免系统临时目录权限/清理策略干扰
if os.path.isdir(TMP):
    shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)

results = []


def _io():
    for _name in ("stdout", "stderr"):
        try:
            getattr(sys, _name).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def run(label, args, expect_rc=0, cwd=HERE):
    r = subprocess.run([PY, *args], cwd=cwd, capture_output=True)
    out = (r.stdout or b"").decode("utf-8", "replace")
    err = (r.stderr or b"").decode("utf-8", "replace")
    ok = (expect_rc is None) or (r.returncode == expect_rc)
    results.append((label, ok, r.returncode, expect_rc))
    print("[%s] %s（退出码 %s，期望 %s）" % ("PASS" if ok else "FAIL", label, r.returncode, expect_rc))
    if not ok:
        print("    stdout:", out.strip()[:300])
        print("    stderr:", err.strip()[:300])
    return out, err


def write(name, text):
    p = os.path.join(TMP, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def main():
    _io()
    ok_all = True

    run("1 calc_engine --selftest", ["calc_engine.py", "--selftest"])
    run("2 staleness_check（宽限 10 年）", ["staleness_check.py", "--days", "3650"])
    run("3 authority_search 命中", ["references/search/authority_search.py", "工程量偏差"])
    run("4 authority_search 库外", ["references/search/authority_search.py", "zzz不存在词"],
        expect_rc=1)

    p_ok = write("ok.md", "依据 GB/T 50500-2024 第9.6.2条，工程量偏差超15%时调价；"
                          "数据来源：送审资料与 calc_engine.py 实算。")
    run("5 gate 合规稿 PASS", [GATE, "emit", "--file", p_ok])
    p_date = write("date.md", "承包方于 2026年9月 提交索赔意向书。")
    run("6 gate 日期稿 PASS（回归）", [GATE, "emit", "--file", p_date])
    p_bad = write("bad.md", "本次审核结论：审减额 120 万元，主要原因是工程量重复计算。")
    run("7 gate 无出处数字 拦截", [GATE, "emit", "--file", p_bad], expect_rc=1)
    p_fuzzy = write("fuzzy.md", "本项目造价约 1000 元每平米。")
    run("8 gate 模糊+数字 拦截", [GATE, "emit", "--file", p_fuzzy], expect_rc=1)
    p_src = write("src.md", "综合单价 381.5 元/m³（数据来源：local_rates.json 毕节市2026第3期，"
                            "依据 GB/T 50500-2024）。")
    run("9 gate 引用+来源 PASS", [GATE, "emit", "--file", p_src])

    csv_path = os.path.join(TMP, "rates.csv")
    with open(csv_path, "w", encoding="utf-8-sig") as f:
        f.write("名称,单价\nC30商品混凝土 元/m³,485\nHRB400钢筋Φ20内 元/t,3880\n")
    run("10a ingest 读 csv", ["ingest.py", csv_path])
    rates_out = os.path.join(TMP, "local_rates.json")
    run("10b ingest --build-rates", ["ingest.py", "--build-rates", csv_path,
                                     "--kind", "materials", "--region", "测试地区",
                                     "--period", "2026第3期", "--source", "测试造价站",
                                     "--out", rates_out])
    run("10c 引擎引用生成的 local_rates（仅材料价）",
        ["calc_engine.py", "--func", "compose_price_from_rates",
         "--materials", "C30商品混凝土:2.5", "--rates_file", rates_out])
    run("10d 缺人工单价时 fail-closed 报错",
        ["calc_engine.py", "--func", "compose_price_from_rates",
         "--materials", "C30商品混凝土:2.5", "--labor_days", "1",
         "--rates_file", rates_out], expect_rc=2)

    _hf = os.path.join(TMP, "导出件.csv")
    with open(_hf, "w", encoding="utf-8") as _f:
        _f.write("项目,金额" + chr(10) + "土方,100" + chr(10) + "混凝土,200" + chr(10))
    out, err = run("10e ingest --hash 登记校验值", ["ingest.py", "--hash", _hf])
    try:
        _sha = json.loads(out).get("SHA-256", "")
        _md5 = json.loads(out).get("MD5", "")
    except Exception:
        _sha, _md5 = "", ""
    good = (len(_sha) == 64) and (len(_md5) == 32)
    results.append(("10e 文件指纹 SHA-256 / MD5 生成", good, _sha[:12] or "解析失败", "64 / 32 位"))
    print("[%s] 10e 文件指纹 SHA-256 / MD5 生成" % ("PASS" if good else "FAIL"))
    run("10f ingest --hash --expect 一致（文件未改动）",
        ["ingest.py", "--hash", _hf, "--expect", _sha])
    run("10g ingest --hash --expect 不一致 fail-closed 拦截",
        ["ingest.py", "--hash", _hf, "--expect", "deadbeef"], expect_rc=1)

    run("11 deliverable 生成交付物", ["deliverable.py"])
    demo_md = os.path.join(HERE, "_demo_out", "结算审核报告.md")
    if not os.path.exists(demo_md):
        results.append(("11b 交付物文件已生成", False, "缺失", "存在"))
        print("[FAIL] 11b 未找到交付物 %s" % demo_md)
    else:
        out, err = run("11b 交付物过门禁（check）", [GATE, "check", "--file", demo_md], expect_rc=0)
        try:
            lvl = json.loads(out).get("level", "?")
        except Exception:
            lvl = "解析失败"
        good = lvl in ("PASS", "WARN")
        results.append(("11b 交付物门禁等级可接受", good, lvl, "PASS/WARN"))
        print("[%s] 11b 交付物门禁等级：%s" % ("PASS" if good else "FAIL", lvl))

    p_conv = write("conv.md", "合同约定 3% 的风险幅度，约定时效 28 天，超期即触发协商程序。"
                             "（数据来源：合同专用条款）")
    run("12 gate 合同约定+数字 不再误伤（回归）", [GATE, "emit", "--file", p_conv])

    p_amt = write("amount.md", "依据 GB 50500-2013 第 9.6.2 条，本工程审减额 600 万元。")
    run("13 gate 金额只标条文、无来源 拦截（新规则）",
        [GATE, "emit", "--file", p_amt], expect_rc=1)

    p_amt2 = write("amount2.md",
                   "依据 GB 50500-2013 第 9.6.2 条，审减额 = 12000 - 10900 = 1100 万元。")
    run("14 gate 金额附计算式 放行", [GATE, "emit", "--file", p_amt2])

    for _name in ("结算审核报告.md", "造价审计报告.md", "索赔分析报告.md", "造价指标分析报告.md",
                  "审计底稿说明.md", "审计实施方案说明.md", "资料索取清单说明.md",
                  "问题整改台账说明.md", "争议事项台账说明.md"):
        _fp = os.path.join(HERE, "_demo_out", _name)
        if not os.path.exists(_fp):
            results.append(("15 交付物已生成 " + _name, False, "缺失", "存在"))
            print("[FAIL] 15 未找到交付物 %s" % _fp)
            continue
        out, err = run("15 交付物过门禁 " + _name, [GATE, "check", "--file", _fp], expect_rc=0)
        try:
            lvl = json.loads(out).get("level", "?")
        except Exception:
            lvl = "解析失败"
        good = lvl in ("PASS", "WARN")
        results.append(("15 交付物门禁等级可接受 " + _name, good, lvl, "PASS/WARN"))
        print("[%s] 15 交付物门禁等级 %s：%s" % ("PASS" if good else "FAIL", _name, lvl))

    # 16 对量工具 reconcile.py：送审 vs 审定两版数据逐项比对
    left = os.path.join(TMP, "送审.csv")
    right = os.path.join(TMP, "审定.csv")
    with open(left, "w", encoding="utf-8-sig") as f:
        f.write("项目名称,工程量,综合单价\n土方开挖,1000,50\n混凝土C30,200,500\n钢筋,50,4000\n")
    with open(right, "w", encoding="utf-8-sig") as f:
        f.write("项目名称,工程量,综合单价\n土方开挖,900,50\n混凝土C30,200,470\n钢筋,50,4000\n"
                "防水工程,100,80\n")
    rec_out = os.path.join(TMP, "_reconcile")
    out, err = run("16a reconcile 对量分析", ["reconcile.py", "--left", left, "--right", right,
                                              "--key", "项目名称", "--qty", "工程量",
                                              "--price", "综合单价", "--out", rec_out,
                                              "--source", "冒烟自检构造的两版测试数据"])
    good = ("OK（量差+价差+漏项+增项 = 总差额）" in out)
    results.append(("16a 对量差额四项闭合校验", good, "见输出", "OK"))
    print("[%s] 16a 对量差额四项闭合校验" % ("PASS" if good else "FAIL"))
    rec_md = os.path.join(rec_out, "对量差异分析.md")
    if not os.path.exists(rec_md):
        results.append(("16b 对量报告已生成", False, "缺失", "存在"))
        print("[FAIL] 16b 未找到对量报告 %s" % rec_md)
    else:
        out, err = run("16b 对量报告过门禁", [GATE, "check", "--file", rec_md], expect_rc=0)
        try:
            lvl = json.loads(out).get("level", "?")
        except Exception:
            lvl = "解析失败"
        good = lvl in ("PASS", "WARN")
        results.append(("16b 对量报告门禁等级可接受", good, lvl, "PASS/WARN"))
        print("[%s] 16b 对量报告门禁等级：%s" % ("PASS" if good else "FAIL", lvl))

    # 17 项目成套模板（project_template.py）：一条命令生成整套审计项目档案
    proj_out = os.path.join(TMP, "_project")
    out, err = run("17a project_template --demo", ["project_template.py", "--demo", "--out", proj_out])
    good = (("门禁自检：全部放行" in out) and os.path.isfile(os.path.join(proj_out, "00_项目索引.md"))
            and ("文件 30 份" in out))
    results.append(("17a 成套档案生成且全部门禁放行", good, "见输出", "30 份全部放行"))
    print("[%s] 17a 成套档案生成且全部门禁放行" % ("PASS" if good else "FAIL"))
    for _dir, _name in (("01_审前调查与立项", "审前调查表.md"),
                        ("02_审计实施方案", "审计实施方案.md"),
                        ("04_审计底稿与证据", "现场取证记录单.md"),
                        ("04_审计底稿与证据", "抽样见证记录.md"),
                        ("04_审计底稿与证据", "电子数据取数说明.md"),
                        ("04_审计底稿与证据", "三级复核意见记录表.md"),
                        ("04_审计底稿与证据", "证据附件页码索引.md"),
                        ("04_审计底稿与证据", "审计日记与工作记录.md"),
                        ("01_审前调查与立项", "外聘人员与回避记录.md"),
                        ("05_问题与争议", "整改回访记录.md"),
                        ("06_报告与归档", "征求意见与沟通记录.md"),
                        ("06_报告与归档", "期后事项与追溯调整记录.md"),
                        ("06_报告与归档", "卷内目录与归档说明.md")):
        _fp = os.path.join(proj_out, _dir, _name)
        if not os.path.isfile(_fp):
            results.append(("17b 档案文件已生成 " + _name, False, "缺失", "存在"))
            print("[FAIL] 17b 缺失 %s" % _fp)
            continue
        out, err = run("17b 档案文件过门禁 " + _name, [GATE, "check", "--file", _fp], expect_rc=0)
        try:
            lvl = json.loads(out).get("level", "?")
        except Exception:
            lvl = "解析失败"
        good = lvl in ("PASS", "WARN")
        results.append(("17b 档案文件门禁等级 " + _name, good, lvl, "PASS/WARN"))
        print("[%s] 17b 档案文件门禁等级 %s：%s" % ("PASS" if good else "FAIL", _name, lvl))
    out, err = run("17c project_template --print-template", ["project_template.py", "--print-template"])
    good = ("项目名称" in out) and ("检查范围明细" in out)
    results.append(("17c 项目信息模板字段完整", good, "见输出", "含项目名称与检查范围明细"))
    print("[%s] 17c 项目信息模板字段完整" % ("PASS" if good else "FAIL"))

    tpl = os.path.join(TMP, "项目信息.json")
    run("17d project_template --save-template（UTF-8 导出）",
        ["project_template.py", "--save-template", tpl])
    tpl_ok, tpl_note = False, "文件未生成"
    if os.path.isfile(tpl):
        raw = open(tpl, "rb").read()
        if raw[:3] == b"\xef\xbb\xbf" or raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            tpl_note = "带了 BOM（应为纯 UTF-8）"
        else:
            try:
                d = json.loads(raw.decode("utf-8"))
                tpl_ok = ("\u9879\u76ee\u540d\u79f0" in d) and ("\u68c0\u67e5\u8303\u56f4\u660e\u7ec6" in d) and len(d) >= 30
                tpl_note = "字段 %d 个、无 BOM" % len(d)
            except Exception as exc:
                tpl_note = "解析失败：%s" % exc
    results.append(("17d 模板导出为纯 UTF-8 且字段完整", tpl_ok, tpl_note, "无 BOM + 字段完整"))
    print("[%s] 17d 模板导出为纯 UTF-8 且字段完整（%s）" % ("PASS" if tpl_ok else "FAIL", tpl_note))

    out, err = run("17e issue_pair 定性命中", ["issue_pair.py", "地下车库土方重复计量，多计 320 万元"])
    good = ("建议依据" in out) and ("数据来源" in out) and ("GB 50500-2013" in out)
    results.append(("17e 问题定性→条款配对（含条款与来源）", good, "见输出", "含建议依据 / 条款 / 数据来源"))
    print("[%s] 17e 问题定性→条款配对（含条款与来源）" % ("PASS" if good else "FAIL"))
    run("17f issue_pair 未命中（库外）", ["issue_pair.py", "土地手续不全涉及面积 12 亩"], expect_rc=1)
    pf = os.path.join(TMP, "portfolio")
    for _n, _sub, _fin in (("甲项目", 5000, 4500), ("乙项目", 3000, 3100)):
        _d = os.path.join(pf, _n)
        os.makedirs(_d, exist_ok=True)
        with open(os.path.join(_d, "项目信息.json"), "w", encoding="utf-8") as _f:
            _f.write(json.dumps({"项目名称": _n, "项目编号": _n + "-01", "审计类型": "竣工结算审计",
                                 "委托单位": "示例单位", "审计期间": "2025-01 至 2026-01",
                                 "送审价": _sub, "审定价": _fin, "数据来源": "示例数据（非真实项目）",
                                 "问题清单": [{"问题描述": "示例问题", "状态": "未整改"}], "争议清单": []},
                                ensure_ascii=False))
    _pf_out = os.path.join(TMP, "pf_out")
    out, err = run("17g 多项目总台账", ["project_template.py", "--portfolio", pf, "--out", _pf_out])
    good = (("项目数 2" in out) and ("门禁自检：PASS" in out)
            and os.path.isfile(os.path.join(_pf_out, "审计项目总台账.md")))
    results.append(("17g 多项目总台账生成且门禁放行", good, "见输出", "2 个项目 + 门禁 PASS"))
    print("[%s] 17g 多项目总台账生成且门禁放行" % ("PASS" if good else "FAIL"))

    run("18 content_check --quick（全包完整性）", ["content_check.py", "--quick"])

    print()
    bad = [r for r in results if not r[1]]
    print("汇总: %s（%d/%d 项通过）" % ("ALL PASS ✅" if not bad else "FAILED ❌",
                                  len(results) - len(bad), len(results)))
    for label, _, got, exp in bad:
        print("  - 未通过：%s（得到 %s，期望 %s）" % (label, got, exp))
    shutil.rmtree(TMP, ignore_errors=True)   # 自检临时目录不留残渣
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
