# -*- coding: utf-8 -*-
"""
工程造价审计真实计算引擎（贴合清单计价与合同调价真实办法）。

依据：
  - 《建设工程工程量清单计价标准》GB/T 50500-2024（2025-09-01 施行）
  - 《建设工程工程量清单计价规范》GB 50500-2013（2024 版施行后废止，但**既有合同约定按 2013 版执行的仍从其约定**）
  - 《建设工程施工合同(示范文本)》GF-2017-0201 第 11.1 条 价格调整 / 第 19 条 索赔
  - 财政部、建设部《建设工程价款结算暂行办法》财建〔2004〕369号
  - 《建设工程质量保证金管理办法》建质〔2017〕138号（预留比例不高于结算总额 3%）

真实要点：
  1) 价格调整——调值公式法（价格指数法）：
       ΔP = P0 × (A + B1·Ft1/F01 + B2·Ft2/F02 + … − 1)
       A=定值权重(不调部分)，Bn=各可调因子变值权重，Ft=现行价格指数，F0=基准价格指数
       约定 A + ΣBn = 1；约定风险幅度时，默认按"幅度内不调、超出部分据实调整"处理。
  2) 价格调整——造价信息调整法（风险幅度法）：按 GB 50500 附录 A 的三档规则区分
       「投标价 < 基准价 / = 基准价 / > 基准价」，涨以基准价（或投标价）为基础、跌反之，
       超出风险幅度的部分据实调整（见 adjust_info 文档）。
  3) 工程量偏差调整：清单工程量偏差超过 ±15% 时，增加部分的单价调低、减少后剩余部分的单价调高
       （GB 50500-2013 第 9.6.2 条 / GB/T 50500-2024 对应条款）。
  4) 审减率预警：审减率 = 审减额 / 报送价。部分政府投资项目约定审减率超过 10% 时启动复核/扣减
       造价咨询费，故设默认预警线 10%（可由调用方传入合同约定值）。

单位与口径（务必对齐，否则会产生 1 万倍量级错误）：
  - 金额参数除特别说明外一律为"万元"；单价类参数为"元/计量单位"（如 元/m³、元/t）。
  - 引擎输出会用「口径说明」字段显式标注单位，调用方不得自行改名换单位。

边界与代码质量（调用方须注意）：
  - 调值公式法：基准指数 F0 不得为 0（否则除零）；权重 A+ΣBn 应≈1，引擎返回 consistency 提示。
  - 偏差/指标：分母为 0（预算=0、面积=0）会抛 ValueError，调用方须先校验输入。
  - 清单/结算合价：items 须为 "工程量:单价;..." 或 "数,数,..." 的合法格式，解析失败抛 ValueError。
  - 价格数据：材料价/人工单价/机械台班只从用户提供的 local_rates.json 读取，引擎内置库不含任何价格。

命令行示例：
  python calc_engine.py --func adjust_formula --p0 1000 --A 0.15 --pairs "0.25,110,100;0.30,105,100;0.30,108,100"
  python calc_engine.py --func adjust_info --current 3200 --base 3000 --bid 2950 --risk 5 --qty 1000
  python calc_engine.py --func qty_deviation --list_qty 1000 --actual_qty 1300 --unit_price 380 --over_factor 0.9
  python calc_engine.py --func audit_reduction --submit 1200 --approved 1080
  python calc_engine.py --func project_total --fbfx 800 --measures 150 --others 80 --gov_fee 40 --tax_rate 0.09
  python calc_engine.py --func compose_price --labor 100 --material 200 --machine 50 --manage_rate 0.05 --profit_rate 0.04
  python calc_engine.py --func compose_price_from_rates --materials "C30商品混凝土 元/m³:2.5;HRB400钢筋Φ20内 元/t:0.06" --labor_days 3 --rates_file references/data/local_rates.json
  python calc_engine.py --selftest
"""
import math, sys, json, argparse, os


def _setup_io():
    """统一 IO 编码：Windows 中文环境下重定向或管道输出含特殊字符时不再崩溃。"""
    for _name in ("stdin", "stdout", "stderr"):
        try:
            getattr(sys, _name).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_io()


def _f(x, n=3):
    return round(x, n)


def _parse_pairs(pairs):
    """解析 '权重,现行指数,基准指数;...' → list[(w, ft, f0)]，非法格式抛 ValueError。"""
    out = []
    for s in str(pairs).strip("[]").split(";"):
        s = s.strip()
        if not s:
            continue
        parts = [p.strip() for p in s.split(",")]
        if len(parts) != 3:
            raise ValueError("pairs 每项须为 '权重,现行指数,基准指数'，收到：%r" % s)
        try:
            w, ft, f0 = (float(p) for p in parts)
        except ValueError:
            raise ValueError("pairs 含非数字：%r" % s)
        out.append((w, ft, f0))
    if not out:
        raise ValueError("pairs 为空，无法计算调值公式")
    return out


# ---------------------------------------------------------------------------
# 价格调整
# ---------------------------------------------------------------------------
def _clamp_ratio(ratio, risk, mode):
    """按约定风险幅度处理指数比，返回 (有效指数比, 是否触发调整)。

    风险幅度（如 ±5%）的专业含义是"幅度内由承包人承担，超出部分据实调整"：
        mode="excess"（默认，通常约定）：指数比 1.20、幅度 5% → 只调 15%（有效比 1.15）
        mode="cap"   ：超过幅度即封顶在幅度边界（少数合同按此约定）
        mode="full"  ：一旦超过幅度，全部波动据实调整
    """
    if risk is None:
        return ratio, True
    r = risk / 100.0
    if mode == "cap":
        return (max(1 - r, min(1 + r, ratio)), ratio > 1 + r or ratio < 1 - r)
    if mode == "full":
        return ratio, (ratio > 1 + r or ratio < 1 - r)
    if ratio > 1:
        return ((1.0 + (ratio - 1.0 - r)) if ratio - 1.0 > r else 1.0), (ratio - 1.0) > r
    if ratio < 1:
        return ((1.0 - ((1.0 - ratio) - r)) if (1.0 - ratio) > r else 1.0), (1.0 - ratio) > r
    return 1.0, False


def adjust_formula(p0, A, pairs, risk=None, risk_mode="excess"):
    """调值公式法（价格指数法）。

    ΔP = P0 × (A + ΣBn·Ftn/F0n − 1)

    p0   : 当期已完成工程量金额（万元，不含调价/质保/预付款）
    A    : 定值权重（不调部分）
    pairs: 可调因子列表，每项 "权重,现行指数,基准指数"（权重之和应 = 1-A）
    risk : 约定风险幅度(%)；给出后按 risk_mode 处理（默认"幅度内不调、超出部分据实调整"）
    risk_mode: excess(默认) / cap / full，见 _clamp_ratio
    返回 调差金额ΔP、调整后金额、各因子贡献、权重一致性提示。
    """
    factors = []
    for w, ft, f0 in _parse_pairs(pairs):
        if f0 == 0:
            raise ValueError("基准指数 F0 不得为 0（权重=%s），否则除零" % w)
        if w < 0 or ft < 0:
            raise ValueError("权重/指数应为非负，收到 w=%s ft=%s" % (w, ft))
        raw = ft / f0
        eff, triggered = _clamp_ratio(raw, risk, risk_mode)
        factors.append({"权重": w, "指数比Ft/F0": _f(raw, 4),
                        "风险调整后指数比": _f(eff, 4),
                        "是否超出风险幅度": bool(triggered),
                        "贡献": _f(w * eff, 4)})
    sum_b = sum(f["权重"] for f in factors)
    inside = A + sum(f["权重"] * f["风险调整后指数比"] for f in factors)
    delta = p0 * (inside - 1)
    consistency = _f(A + sum_b, 3)
    return {"调差金额ΔP(万元)": _f(delta, 2), "调整后金额(万元)": _f(p0 + delta, 2),
            "定值权重A": A, "各因子": factors, "权重校验(A+ΣB)": consistency,
            "风险幅度(%)": risk,
            "风险幅度处理方式": (risk_mode if risk is not None else "未约定（全额调整）"),
            "权重一致性提示": "OK" if abs(consistency - 1.0) < 1e-3 else "A+ΣB≠1，结果可能失真"}


def adjust_info(current, base, bid, risk=5.0, qty=1.0):
    """造价信息调整法（风险幅度法），单材料。

    current: 施工期信息价(元/单位)；base: 基准价；bid: 投标报价；risk: 风险幅度(%)；qty: 工程量

    规则（GB 50500-2013 附录 A.2 / GB/T 50500-2024 对应条文，三档判断）：
      ① 投标价 < 基准价：涨价以【基准价】为基础超幅度调增；跌价以【投标报价】为基础超幅度调减；
      ② 投标价 > 基准价：跌价以【基准价】为基础超幅度调减；涨价以【投标报价】为基础超幅度调增；
      ③ 投标价 = 基准价：涨跌均以【基准价】为基础超幅度调整。
      超出部分据实调整，幅度内不调（结算单价=投标价）。
    返回 结算单价、调差单价/合价、是否调整、适用情形与触发上下限。
    """
    for name, v in (("施工期价", current), ("基准价", base), ("投标价", bid)):
        if v <= 0:
            raise ValueError("%s须为正数（价格口径），收到 %s" % (name, v))
    if risk < 0:
        raise ValueError("风险幅度不得为负，收到 %s" % risk)
    if qty < 0:
        raise ValueError("工程量不得为负，收到 %s" % qty)

    if bid < base:
        up_base, down_base = base, bid
        case = "投标价低于基准价（涨看基准价、跌看投标价）"
    elif bid > base:
        up_base, down_base = bid, base
        case = "投标价高于基准价（涨看投标价、跌看基准价）"
    else:
        up_base = down_base = base
        case = "投标价等于基准价（涨跌均看基准价）"

    up = up_base * (1 + risk / 100.0)
    down = down_base * (1 - risk / 100.0)
    if current > up:
        diff, settle, adj, direction = current - up, bid + (current - up), True, "调增"
    elif current < down:
        diff, settle, adj, direction = down - current, bid - (down - current), True, "调减"
    else:
        diff, settle, adj, direction = 0.0, bid, False, "不调"
    return {"基准价": _f(base, 2), "投标价": _f(bid, 2), "施工期价": _f(current, 2),
            "风险幅度(%)": risk, "适用情形": case,
            "调增判定上限": _f(up, 2), "调减判定下限": _f(down, 2),
            "结算单价": _f(settle, 2), "调差单价": _f(diff, 2),
            "调差方向": direction, "调差合价": _f(diff * qty, 2), "工程量": qty,
            "是否调整": adj,
            "口径说明": "单价为元/计量单位；调差合价与金额口径一致（如单价为元、工程量为单位数，则合价为元）"}

# ---------------------------------------------------------------------------
# 审计核心
# ---------------------------------------------------------------------------
def audit_reduction(submit, approved, warn_line=0.10):
    """审减额=报送-审定；审减率=审减额/报送。审减率 > warn_line（默认 10%）触发预警。

    warn_line 应由调用方按合同/委托约定传入（本团默认 10% 为常见政府投资项目约定），
    不得把默认值当成规范强制阈值。
    """
    if submit <= 0:
        raise ValueError("报送价须为正，收到 submit=%s" % submit)
    if approved < 0:
        raise ValueError("审定价不得为负，收到 approved=%s" % approved)
    if warn_line < 0:
        raise ValueError("预警线不得为负，收到 %s" % warn_line)
    cut = submit - approved
    rate = cut / submit
    over = rate > warn_line
    return {"报送价(万元)": submit, "审定价(万元)": approved, "审减额(万元)": _f(cut, 2),
            "审减率(%)": _f(rate * 100, 2), "超预警线": bool(over), "预警线(%)": warn_line * 100,
            "反向验算(万元)": _f(approved + cut, 2),
            "提示": ("审减率超过约定预警线，建议复核报送资料并说明审减明细与依据"
                     if over else ("审减率恰等于预警线，未超限，须在报告中明确表述"
                                   if abs(rate - warn_line) < 1e-9 else "未超预警线"))}


def audit_reduction_detail(submit, approved, details=None, warn_line=0.10):
    """审减明细分类汇总（量/价/费）＋ 反向验算，防止"只报审减率、不报审减明细"。

    details: {类别: 金额(万元)}，如 {"工程量核减": 60, "单价核减": 40, "取费核减": 20}
    """
    r = audit_reduction(submit, approved, warn_line)
    if details:
        total_detail = sum(details.values())
        r["审减明细(万元)"] = {k: _f(v, 2) for k, v in details.items()}
        r["明细合计(万元)"] = _f(total_detail, 2)
        r["明细与总额差(万元)"] = _f(r["审减额(万元)"] - total_detail, 2)
        r["明细校验"] = ("OK" if abs(total_detail - r["审减额(万元)"]) < 0.01
                         else "明细合计与审减额不一致，须逐项核对")
    else:
        r["审减明细(万元)"] = {}
        r["明细校验"] = "未提供明细：禁止仅以审减率下结论，须列审减明细致对应条款"
    return r


def list_total(items):
    """items: list[(工程量, 单价)]，返回清单合价。单位由调用方保证一致。"""
    if not items:
        raise ValueError("清单为空，无法计算合价")
    for q, p in items:
        if q < 0 or p < 0:
            raise ValueError("工程量/单价不得为负，收到 (%s, %s)" % (q, p))
    total = sum(q * p for q, p in items)
    return {"清单合价": _f(total, 2), "项数": len(items),
            "口径说明": "合价单位 = 单价单位 × 工程量单位（如 单价万元、量按单位，则合价为万元）"}


def claim_amount(days, daily_loss, extra_cost=0):
    """费用索赔额 = 有效延误天数 × 日损失 + 其他额外费用（万元）。"""
    if days < 0 or daily_loss < 0 or extra_cost < 0:
        raise ValueError("索赔天数/损失不得为负")
    return {"有效延误天数": days, "日损失(万元/天)": daily_loss, "额外费用(万元)": extra_cost,
            "索赔额(万元)": _f(days * daily_loss + extra_cost, 2)}


def variance(budget, actual):
    """偏差=实际-预算；偏差率=偏差/预算。预算为 0 抛 ValueError。"""
    if budget == 0:
        raise ValueError("预算为 0，无法计算偏差率")
    var = actual - budget
    return {"预算(万元)": budget, "实际(万元)": actual, "偏差(万元)": _f(var, 2),
            "偏差率(%)": _f(var / budget * 100, 2),
            "方向": "超支" if var > 0 else ("节约" if var < 0 else "持平")}


def settlement_total(items):
    """items: list[金额]，返回结算总价（万元）。注意：须确认是否已含规费税金。"""
    if not items:
        raise ValueError("结算明细为空，无法计算总价")
    for x in items:
        if x < 0:
            raise ValueError("结算金额不得为负，收到 %s" % x)
    return {"结算总价(万元)": _f(sum(items), 2), "项数": len(items),
            "提示": "须确认各项口径已含/未含规费税金，避免重复计取或漏计"}


def qty_deviation_adjust(list_qty, actual_qty, unit_price,
                         low=0.85, high=1.15, over_factor=0.9, under_factor=1.1):
    """工程量偏差 ±15% 时综合单价调整（GB 50500-2013 第 9.6.2 条／2024 版对应条款）。

    规则：工程量偏差 = (实际量 − 清单量)/清单量
      · 实际量 > 清单量 ×(1+15%)：清单量的 115% 部分按原单价，超出部分单价调低；
      · 实际量 < 清单量 ×(1−15%)：减少后剩余部分（即实际量）单价调高；
      · 幅度以内：不调价，按实际量×原单价。
    over_factor/under_factor 为调价系数（默认 0.9/1.1，**须按合同约定替换**，
    合同无约定时应与对方协商或按清单标准由发承包双方商定后填入）。
    金额一律按"单价 × 工程量"的原始口径返回元，同时给出万元。
    """
    if list_qty <= 0:
        raise ValueError("清单工程量须为正，收到 %s" % list_qty)
    if actual_qty < 0:
        raise ValueError("实际工程量不得为负，收到 %s" % actual_qty)
    if unit_price <= 0:
        raise ValueError("综合单价须为正，收到 %s" % unit_price)
    if not (0 < low < 1 < high):
        raise ValueError("阈值须满足 0<low<1<high，收到 low=%s high=%s" % (low, high))
    if over_factor <= 0 or under_factor <= 0:
        raise ValueError("调价系数须为正")

    dev = (actual_qty - list_qty) / list_qty
    base = actual_qty * unit_price
    if dev > (high - 1) + 1e-9:
        keep = list_qty * high
        extra = actual_qty - keep
        new_price = unit_price * over_factor
        adj = keep * unit_price + extra * new_price
        case = "工程量增加超过 %.0f%%，超出部分单价调低至原单价×%s" % ((high - 1) * 100, over_factor)
        eff_price = None
    elif dev < (low - 1) - 1e-9:
        keep, extra, new_price = actual_qty, 0.0, unit_price * under_factor
        adj = actual_qty * new_price
        case = "工程量减少超过 %.0f%%，剩余部分单价调高至原单价×%s" % ((1 - low) * 100, under_factor)
        eff_price = new_price
    else:
        keep, extra, new_price, eff_price = actual_qty, 0.0, unit_price, unit_price
        adj = base
        case = "偏差在 ±%.0f%% 以内，不调价（±阈值本身不调）" % ((high - 1) * 100)
    return {"清单工程量": list_qty, "实际工程量": actual_qty,
            "偏差率(%)": _f(dev * 100, 2), "是否调整单价": dev > (high - 1) + 1e-9 or dev < (low - 1) - 1e-9,
            "阈值": {"下限": low, "上限": high},
            "原合价(元)": _f(base, 2), "调整后合价(元)": _f(adj, 2),
            "调整后合价(万元)": _f(adj / 10000.0, 4),
            "增减额(元)": _f(adj - base, 2),
            "按原单价计价部分工程量": _f(keep, 2),
            "调价部分工程量": _f(extra, 2),
            "调价部分综合单价(元/单位)": _f(new_price, 2),
            "调整后综合单价(元/单位)": (_f(eff_price, 2) if eff_price is not None else "价量混合计价，见明细"),
            "适用规则": case}


def project_total(fbfx, measures=0.0, others=0.0, gov_fee=None,
                  gov_fee_rate=None, gov_fee_base=None, tax_rate=0.0, provisional=0.0):
    """单位工程造价汇总：分部分项 + 措施 + 其他 + 规费 + 税金（万元）。

    gov_fee      : 规费金额（万元）。给定时直接用；
    gov_fee_rate : 规费费率，配合 gov_fee_base（基数，万元，通常为人工费或人工费+机械费）计取；
    tax_rate     : 增值税率（如一般计税 0.09、简易计税 0.03）；
    provisional  : 其中"暂列金额/暂估价"等非确定价金额（万元），仅用于提示，不参与剔重计算。
    返回 税前造价、税金、总造价、构成占比与暂列金额提示。
    """
    for name, v in (("分部分项工程费", fbfx), ("措施项目费", measures), ("其他项目费", others),
                    ("暂列金额", provisional)):
        if v < 0:
            raise ValueError("%s不得为负，收到 %s" % (name, v))
    if tax_rate < 0:
        raise ValueError("税率不得为负，收到 %s" % tax_rate)
    if gov_fee is None:
        if gov_fee_rate is not None:
            if gov_fee_base is None:
                raise ValueError("给出规费费率时必须同时给出规费计取基数 gov_fee_base")
            gov_fee = gov_fee_base * gov_fee_rate
        else:
            gov_fee = 0.0
    if gov_fee < 0:
        raise ValueError("规费不得为负，收到 %s" % gov_fee)

    pre_tax = fbfx + measures + others + gov_fee
    tax = pre_tax * tax_rate
    total = pre_tax + tax
    certain = total - provisional
    share = lambda x: _f(x / total * 100, 2) if total else 0.0
    return {"分部分项工程费(万元)": _f(fbfx, 2), "措施项目费(万元)": _f(measures, 2),
            "其他项目费(万元)": _f(others, 2), "规费(万元)": _f(gov_fee, 2),
            "税前工程造价(万元)": _f(pre_tax, 2),
            "税金(%s%%)(万元)" % _f(tax_rate * 100, 1): _f(tax, 2),
            "工程造价合计(万元)": _f(total, 2),
            "其中暂列金额/暂估价(万元)": _f(provisional, 2),
            "剔除暂列金额后确定性造价(万元)": _f(certain, 2),
            "构成占比(%)": {"分部分项": share(fbfx), "措施": share(measures),
                            "其他": share(others), "规费": share(gov_fee), "税金": share(tax)},
            "提示": ("含暂列金额/暂估价 %s 万元，属非确定价，须按实结算，不得直接作为定案价"
                     % _f(provisional, 2)) if provisional > 0 else "未列暂列金额/暂估价"}


def prepayment_deduct(contract_amount, prepayment_rate, material_ratio,
                      cumulative_completed, already_deducted=0.0, deduction_point_ratio=None):
    """预付款与扣回（万元）。

    prepayment_rate   : 预付款比例（如 0.20=20%）
    material_ratio    : 主要材料及构件占比（用于起扣点与扣回比例，如 0.60）
    cumulative_completed: 截至目前累计已完成工程款（万元）
    deduction_point_ratio: 起扣点比例；不给则按 1 − 预付款比例/材料占比（常规公式）
    already_deducted  : 已扣回金额（万元，防止重复扣回）
    返回 预付款总额、起扣点、本次可扣回金额、剩余未扣回。
    """
    for name, v in (("合同价", contract_amount), ("累计完成", cumulative_completed),
                    ("已扣回", already_deducted)):
        if v < 0:
            raise ValueError("%s不得为负，收到 %s" % (name, v))
    if not (0 < prepayment_rate < 1):
        raise ValueError("预付款比例应在 0~1 之间，收到 %s" % prepayment_rate)
    if not (0 < material_ratio <= 1):
        raise ValueError("主要材料占比应在 0~1 之间，收到 %s" % material_ratio)
    if contract_amount <= 0:
        raise ValueError("合同价须为正，收到 %s" % contract_amount)
    prepay = contract_amount * prepayment_rate
    point_ratio = (deduction_point_ratio if deduction_point_ratio is not None
                   else 1 - prepayment_rate / material_ratio)
    if point_ratio < 0:
        point_ratio = 0.0
    point = contract_amount * point_ratio
    if cumulative_completed <= point:
        deduct = 0.0
    else:
        deduct = max(0.0, (cumulative_completed - point) * material_ratio - already_deducted)
    deduct = min(deduct, max(0.0, prepay - already_deducted))
    return {"预付款总额(万元)": _f(prepay, 2), "起扣点比例": _f(point_ratio, 4),
            "起扣点金额(万元)": _f(point, 2), "累计已完成(万元)": _f(cumulative_completed, 2),
            "已扣回(万元)": _f(already_deducted, 2), "本次应扣回(万元)": _f(deduct, 2),
            "扣回后剩余未扣(万元)": _f(max(0.0, prepay - already_deducted - deduct), 2),
            "提示": "起扣点公式与扣回基数须与合同专用条款一致，不一致时以合同为准"}


def retention_amount(settlement_amount, rate=0.03, contract_amount=None, cap_rate=0.03):
    """质量保证金（质保金）预留额（万元）。

    依据《建设工程质量保证金管理办法》建质〔2017〕138号：预留比例不得高于
    工程价款结算总额的 3%。缺陷责任期一般为 1 年，最长不超过 2 年。
    """
    if settlement_amount <= 0:
        raise ValueError("结算总额须为正，收到 %s" % settlement_amount)
    if rate < 0 or rate > cap_rate:
        raise ValueError("预留比例 %.4f 超过上限 %.4f（建质〔2017〕138号）" % (rate, cap_rate))
    amt = settlement_amount * rate
    return {"结算总额(万元)": _f(settlement_amount, 2), "预留比例": rate,
            "质量保证金(万元)": _f(amt, 2),
            "合法上限(万元)": _f(settlement_amount * cap_rate, 2),
            "提示": "预留比例不得高于结算总额 3%；缺陷责任期内可约定返还，缺陷责任期最长不超过 2 年"}


def late_payment_interest(amount, days, lpr=None, agreed_rate=None):
    """逾期付款利息（万元）；按 本金 × 年利率 × 天数/365 计。

    司法解释口径（建工司法解释(一)第二十六条）：有约定从约定；无约定按同期同类贷款利率
    或同期贷款市场报价利率（LPR）计息。引擎**不擅自**用 LPR 替换合同约定利率；
    约定利率明显偏低时只在"提示"中提醒，最终以双方确认或裁判认定为准。
    lpr/agreed_rate 均为年利率小数（如 0.031 表示 3.1%）。
    """
    if amount <= 0:
        raise ValueError("欠付金额须为正，收到 %s" % amount)
    if days < 0:
        raise ValueError("逾期天数不得为负，收到 %s" % days)
    if lpr is None and agreed_rate is None:
        raise ValueError("须给出约定利率 agreed_rate 或同期 LPR（不得由引擎虚构利率）")
    used, basis, note = None, "", ""
    if agreed_rate is not None:
        used = agreed_rate
        basis = "按合同约定利率计息（有约定从约定）"
        if lpr is not None and agreed_rate < lpr:
            note = ("⚠ 合同约定利率 %.4f%% 低于同期 LPR %.4f%%：本引擎不擅自替换约定利率，"
                    "如一方主张按 LPR 计息，须经双方确认或由裁判机构认定"
                    % (agreed_rate * 100, lpr * 100))
    else:
        used, basis = lpr, "无约定，按同期同类贷款利率或同期 LPR 计息"
    inter = amount * used * days / 365.0
    tip = "利率须以合同约定或起诉时公布的 1 年期 LPR 为准；本结果不得作为定案依据"
    if note:
        tip = note + "；" + tip
    return {"欠付本金(万元)": _f(amount, 2), "逾期天数": days,
            "采用年利率(%)": _f(used * 100, 4), "计息依据": basis,
            "逾期付款利息(万元)": _f(inter, 4),
            "提示": tip}

# ---------------------------------------------------------------------------
# 清单计价（清单准角色算力支撑）
# ---------------------------------------------------------------------------
def compose_price(labor, material, machine, manage_rate, profit_rate, risk_amp=0.0,
                  tax_rate=None, unit="元"):
    """综合单价组价：人 + 材 + 机 + 管理费 + 利润 + 风险（+ 税金）。

    labor/material/machine : 单位工程量的人材机金额，单位见 unit（默认"元"）
    manage_rate/profit_rate/risk_amp : 相对 (人+材+机) 计取的比率（如 0.05=5%）
    tax_rate : 可选（含税口径），给出时再加增值税
    unit     : 以上金额的计量单位（"元"或"万元"或"元/m³"等），**输出标签随之变化**，
               严禁把"元"的组价结果标成"万元"（会造成 1 万倍口径错误）。
    返回 各项金额与综合单价，并显式标注单位口径。
    """
    for name, v in (("人工", labor), ("材料", material), ("机械", machine)):
        if v < 0:
            raise ValueError("%s费不得为负，收到 %s" % (name, v))
    for name, v in (("管理费率", manage_rate), ("利润率", profit_rate), ("风险幅度", risk_amp)):
        if v < 0:
            raise ValueError("%s不得为负，收到 %s" % (name, v))
    if tax_rate is not None and tax_rate < 0:
        raise ValueError("税率不得为负，收到 %s" % tax_rate)
    base = labor + material + machine
    if base == 0:
        raise ValueError("(人工+材料+机械) 为 0，无法组价")
    manage = base * manage_rate
    profit = base * profit_rate
    risk = base * risk_amp
    subtotal = base + manage + profit + risk
    tax = subtotal * tax_rate if tax_rate is not None else 0.0
    tag = "/计量单位"
    return {"人工费(%s%s)" % (unit, tag): _f(labor, 4),
            "材料费(%s%s)" % (unit, tag): _f(material, 4),
            "机械费(%s%s)" % (unit, tag): _f(machine, 4),
            "管理费(%s%%)(%s%s)" % (_f(manage_rate * 100, 1), unit, tag): _f(manage, 4),
            "利润(%s%%)(%s%s)" % (_f(profit_rate * 100, 1), unit, tag): _f(profit, 4),
            "风险(%s%%)(%s%s)" % (_f(risk_amp * 100, 1), unit, tag): _f(risk, 4),
            "税前综合单价(%s%s)" % (unit, tag): _f(subtotal, 4),
            "税金(%s%%)(%s%s)" % (_f(tax_rate * 100, 1) if tax_rate is not None else 0, unit, tag): _f(tax, 4),
            "综合单价(%s%s)" % (unit, tag): _f(subtotal + tax, 4),
            "计量单位": unit,
            "口径说明": "综合单价单位 = %s/%s；含税综合单价%s" % (
                unit, "计量单位", "已计入增值税" if tax_rate is not None else "未计税金")}


def load_local_rates(path):
    """读取用户维护的当地价格/费率数据（references/data/local_rates.json）。

    返回 dict；文件不存在或非法 JSON 抛 ValueError（失败闭合，不静默用默认值）。
    """
    if not path:
        raise ValueError("未提供 local_rates 文件路径")
    if not os.path.exists(path):
        raise ValueError("local_rates 文件不存在：%s（请先用 ingest.py --build-rates 导入当地公布数据）" % path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError("local_rates 文件非法 JSON：%s" % e)
    if not isinstance(data, dict):
        raise ValueError("local_rates 顶层须为对象")
    return data


def _rates_source(rates):
    src = "当地公布数据：%s %s（来源：%s）" % (
        rates.get("region", "?"), rates.get("period", "?"), rates.get("source", "?"))
    is_example = bool(rates.get("is_example", False))
    if is_example:
        src = "⚠ 示例占位数据（非真实，禁止用于正式结论）：" + src
    return src, is_example


def compose_price_with_rates(labor, material, machine, rates_file,
                             manage_override=None, profit_override=None,
                             risk_override=None, tax_override=None, unit="元"):
    """综合单价组价，费率/税率自动取自 local_rates（当地公布数据）。

    *_override 为显式覆盖（优先于文件）；为 None 时取文件值，文件也无则用内置默认。
    返回 compose_price 结果 + 「数据来源」「是否示例数据」字段，强制可溯源。
    """
    rates = load_local_rates(rates_file)
    fr = rates.get("fee_rates", {}) or {}

    def _pick(rates_val, override, default):
        if override is not None:
            return override
        if rates_val is not None:
            return rates_val
        return default

    manage_rate = _pick(fr.get("manage_rate"), manage_override, 0.05)
    profit_rate = _pick(fr.get("profit_rate"), profit_override, 0.04)
    risk_amp = _pick(fr.get("risk_amp"), risk_override, 0.0)
    tax_rate = _pick(fr.get("tax_rate"), tax_override, None)
    r = compose_price(labor, material, machine, manage_rate, profit_rate, risk_amp, tax_rate, unit)
    src, is_example = _rates_source(rates)
    r["数据来源"] = src
    r["是否示例数据"] = is_example
    r["取费来源"] = {"manage_rate": manage_rate, "profit_rate": profit_rate,
                     "risk_amp": risk_amp, "tax_rate": tax_rate}
    return r


def _match_price(name, table):
    """在 rates 表中按 精确 → 包含 顺序匹配材料/机械名称，返回 (命中键, 价格) 或 (None, None)。"""
    if name in table:
        return name, table[name]
    for k, v in table.items():
        if name and (name in k or k in name):
            return k, v
    return None, None


def compose_price_from_rates(materials, rates_file, labor_days=0.0, machines=None,
                             manage_override=None, profit_override=None,
                             risk_override=None, tax_override=None,
                             strict=True, extra_prices=None):
    """按工程量清单用【当地公布的真实价格】组价（真正消费 local_rates 的材料/人工/机械价）。

    materials : {材料名: 用量}（用量按该材料的计价单位，如 m³、t）
    labor_days: 人工工日数（× local_rates.labor_rate）
    machines  : {机械名: 台班数}（× local_rates.machine_rates）
    strict    : True（默认）= 有材料/机械在库中匹配不到时抛错，避免漏算材料费把单价做低；
                False = 列入「未匹配」并不计入，输出会显著告警。
    extra_prices: {名称: 单价} 手工补充库中缺失的价格（须由用户提供，不得编造）
    返回 人材机明细、综合单价、数据来源、未匹配清单。
    """
    rates = load_local_rates(rates_file)
    mat_table = dict(rates.get("materials", {}) or {})
    mac_table = dict(rates.get("machine_rates", {}) or {})
    if extra_prices:
        mat_table.update(extra_prices)
    labor_rate = rates.get("labor_rate")
    if labor_days and not labor_rate:
        raise ValueError("local_rates 未提供 labor_rate（人工单价），无法计算人工费；请补充或改用 --labor 直接给人工费")

    details, missing = [], []
    material_cost = 0.0
    for name, qty in (materials or {}).items():
        if qty < 0:
            raise ValueError("材料用量不得为负：%s=%s" % (name, qty))
        key, price = _match_price(name, mat_table)
        if key is None:
            missing.append(name)
            continue
        sub = qty * price
        material_cost += sub
        details.append({"名称": name, "匹配键": key, "用量": qty, "单价": price, "小计": _f(sub, 4)})

    machine_cost = 0.0
    mac_details = []
    for name, qty in (machines or {}).items():
        if qty < 0:
            raise ValueError("机械台班不得为负：%s=%s" % (name, qty))
        key, price = _match_price(name, mac_table)
        if key is None:
            missing.append(name)
            continue
        sub = qty * price
        machine_cost += sub
        mac_details.append({"名称": name, "匹配键": key, "台班": qty, "台班单价": price, "小计": _f(sub, 4)})

    if missing and strict:
        raise ValueError("以下材料/机械未在 local_rates 中匹配到价格：%s。"
                         "请用 --extra-prices 补充真实价格，或提供更完整的当地信息价表；"
                         "严禁用推测价代替" % "、".join(missing))

    labor_cost = (labor_days or 0.0) * (labor_rate or 0.0)
    r = compose_price_with_rates(labor_cost, material_cost, machine_cost, rates_file,
                                 manage_override, profit_override, risk_override, tax_override)
    r["人材机明细"] = {"人工": {"工日": labor_days, "工日单价": labor_rate, "小计": _f(labor_cost, 4)},
                       "材料": details, "机械": mac_details}
    r["未匹配价格项"] = missing
    if missing:
        r["提示"] = ("⚠ 以下项未匹配到当地价格且未计入：%s，综合单价偏低，须补齐后再用"
                     % "、".join(missing))
    return r


# ---------------------------------------------------------------------------
# 索赔（索赔通角色算力支撑）
# ---------------------------------------------------------------------------
def _parse_date(s):
    import datetime
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError("无法解析日期（须 YYYY-MM-DD）：%s" % s)


def delay_extension(delay_days, total_float):
    """工期索赔天数：延误天数扣除该线路总时差后，超出部分才影响工期。

    关键线路（总时差为 0）延误全额可索赔；非关键线路在时差范围内不延长工期。
    """
    if delay_days < 0 or total_float < 0:
        raise ValueError("延误天数/总时差不得为负")
    eff = max(0.0, delay_days - total_float)
    return {"线路延误(天)": delay_days, "总时差(天)": total_float,
            "可索赔工期(天)": _f(eff, 2),
            "是否影响工期": eff > 0,
            "口径说明": "仅当该线路为关键线路或延误超过其总时差时才影响总工期；"
                    "多条线路同时延误须做网络计划分析，取对总工期影响最大者，不得简单相加"}


def delay_claim(event_date, claim_date, notice_days=28, delay_days=0,
                daily_loss=0.0, extra=0.0, extension_cap=None, event_end_date=None,
                total_float=0.0, final_report_days=28):
    """工期/费用索赔时序与金额计算。

    event_date     : 索赔事件发生日（知道或应当知道之日）
    claim_date     : 提出索赔意向日
    notice_days    : 约定时效（天），默认 28（GF-2017-0201 第19.1条）
    delay_days     : 实际延误天数（用于工期索赔）
    total_float    : 该线路总时差（天），用于扣减非关键线路时差
    daily_loss     : 每日损失（万元/天）
    extra          : 额外费用（万元）
    extension_cap  : 工期延长上限（天），超出部分不计
    event_end_date : 持续性事件影响结束日；给出后按第19.1条计算"最终索赔报告"截止日
    返回 时效判定、可索赔工期、费用索赔额、最终报告时限与证据要求提示。
    """
    ev = _parse_date(event_date)
    cl = _parse_date(claim_date)
    if cl < ev:
        raise ValueError("索赔提出日早于事件发生日，数据异常")
    if notice_days < 0 or delay_days < 0 or daily_loss < 0 or extra < 0 or total_float < 0:
        raise ValueError("时效/延误/损失/时差不得为负")
    gap = (cl - ev).days
    within = gap <= notice_days
    ext = delay_extension(delay_days, total_float)
    days = ext["可索赔工期(天)"]
    if extension_cap is not None:
        days = min(days, extension_cap)
    cost = days * daily_loss + extra
    out = {"事件发生日": event_date, "提出意向日": claim_date,
           "时效间隔(天)": gap, "约定时效(天)": notice_days, "是否在时效内": within,
           "超时效提示": ("" if within else
                        "已超 %d 天约定时效（间隔 %d 天），索赔权可能灭失；"
                        "须补正已持续提交的记录或说明合理原因，并评估时效抗辩风险" % (notice_days, gap)),
           "线路延误(天)": delay_days, "总时差(天)": total_float,
           "工期索赔(天)": _f(days, 2), "费用索赔额(万元)": _f(cost, 2),
           "费用构成(万元)": {"窝工/损失": _f(days * daily_loss, 2), "其他额外费用": _f(extra, 2)},
           "提示": "工期索赔与费用索赔须分别论证：可延长工期不等于可获赔费用；"
                 "索赔费用与结算价款调整不得重复计取"}
    if event_end_date:
        end = _parse_date(event_end_date)
        if end < ev:
            raise ValueError("影响结束日不得早于事件发生日")
        out["影响结束日"] = event_end_date
        out["最终索赔报告截止日"] = (end + __import__("datetime").timedelta(days=final_report_days)).isoformat()
        out["持续性事件提示"] = ("持续性影响事件：须按合理时间间隔提交延续索赔通知，"
                             "并在影响结束（%s）后 %d 天内提交最终索赔报告" % (event_end_date, final_report_days))
    return out


# ---------------------------------------------------------------------------
# 审计作业支持（审减归因 / 多期加权调差 / 勾稽校验 / 重点核查范围）
# ---------------------------------------------------------------------------
def audit_attribution(submit_qty, audited_qty, submit_price, audited_price, name=""):
    """审减额归因分解：把审减额精确拆成"工程量核减"与"单价核减"两部分。

    送审金额 = 送审量 × 送审单价；审定金额 = 审定量 × 审定单价。
        量差影响 = (送审量 − 审定量) × 送审单价
        价差影响 = (送审单价 − 审定单价) × 审定量
        量差影响 + 价差影响 ≡ 审减额（无交叉项残留，可反向验算）
    用途：审计报告必须写清"审减是因为多报量还是高报价"，本函数给出可复核的拆分。
    """
    for label, v in (("送审工程量", submit_qty), ("审定工程量", audited_qty),
                     ("送审综合单价", submit_price), ("审定综合单价", audited_price)):
        if v < 0:
            raise ValueError("%s不得为负，收到 %s" % (label, v))
    submit_amt = submit_qty * submit_price
    audited_amt = audited_qty * audited_price
    cut = submit_amt - audited_amt
    qty_part = (submit_qty - audited_qty) * submit_price
    price_part = (submit_price - audited_price) * audited_qty
    if abs((qty_part + price_part) - cut) > 1e-6:
        raise AssertionError("归因分解不自洽：%s vs %s" % (qty_part + price_part, cut))
    if abs(cut) < 1e-9:
        main, direction = "审减额为零（量价均无核减）", "无核减"
    elif cut < 0:
        main = "审增（审定金额高于送审金额）"
        direction = "审增 %.2f" % abs(cut)
        main = ("审增以工程量增加为主" if abs(qty_part) > abs(price_part)
                else "审增以单价调增为主")
    else:
        main = ("工程量核减为主" if abs(qty_part) > abs(price_part)
                else ("单价核减为主" if abs(price_part) > abs(qty_part) else "量差与价差各半"))
        direction = "审减 %.2f" % cut
    return {"项目": name or "（未命名清单项）",
            "送审工程量": submit_qty, "送审综合单价": _f(submit_price, 4),
            "审定工程量": audited_qty, "审定综合单价": _f(audited_price, 4),
            "送审金额(元)": _f(submit_amt, 2), "审定金额(元)": _f(audited_amt, 2),
            "审减额(元)": _f(cut, 2),
            "工程量核减影响(元)": _f(qty_part, 2), "单价核减影响(元)": _f(price_part, 2),
            "量差占总核减(%)": (_f(qty_part / cut * 100, 2) if abs(cut) > 1e-9 else None),
            "价差占总核减(%)": (_f(price_part / cut * 100, 2) if abs(cut) > 1e-9 else None),
            "归因结论": main, "方向": direction,
            "反向验算": "OK（量差影响 + 价差影响 = 审减额）",
            "口径说明": "金额按 单价 × 工程量 的原始口径返回元；单价须与工程量单位一致"}


def material_adjust_weighted(periods, base, bid, risk=5.0, name=""):
    """多期（按月/按期）用量加权材料调差——施工期跨多个信息价期次的实际结算口径。

    periods : [{"期次": "2026-03", "用量": 120, "信息价": 500}, ...]
    规则：每期按 adjust_info 的三档规则算出该期结算单价，再乘该期用量后汇总
          （单期口径请直接用 adjust_info）。
    返回：各期明细、合计用量、加权平均信息价、调差金额、适用情形。
    """
    if not periods:
        raise ValueError("periods 为空，无法计算多期调差（单期请用 adjust_info）")
    rows, total_qty, amt_current, base_amt, adj_amt = [], 0.0, 0.0, 0.0, 0.0
    case_used = None
    for i, p in enumerate(periods, 1):
        qty = float(p.get("用量", 0) or 0)
        cur = p.get("信息价")
        if cur is None:
            raise ValueError("第 %d 期缺『信息价』" % i)
        cur = float(cur)
        if qty < 0:
            raise ValueError("第 %d 期用量不得为负：%s" % (i, qty))
        one = adjust_info(cur, base, bid, risk, qty)
        case_used = one["适用情形"]
        total_qty += qty
        amt_current += qty * cur
        base_amt += qty * bid
        adj_amt += one["调差单价"] * qty
        rows.append({"期次": p.get("期次", "第%d期" % i), "用量": qty,
                     "信息价": _f(cur, 4), "结算单价": one["结算单价"],
                     "调差单价": one["调差单价"], "调差方向": one["调差方向"],
                     "调差金额": _f(one["调差单价"] * qty, 2)})
    if total_qty <= 0:
        raise ValueError("合计用量为 0，无法计算调差")
    return {"材料/项目": name or "（未命名材料）",
            "适用情形": case_used, "风险幅度(%)": risk,
            "基准价": _f(base, 4), "投标价": _f(bid, 4),
            "各期明细": rows,
            "合计用量": _f(total_qty, 4),
            "加权平均信息价": _f(amt_current / total_qty, 4),
            "按投标价计价金额": _f(base_amt, 2),
            "调差金额": _f(adj_amt, 2),
            "调整后金额": _f(base_amt + adj_amt, 2),
            "是否调整": abs(adj_amt) > 1e-9,
            "提示": "各期信息价须来自当地造价站公布的对应期次；用量须与计量台账一致，否则调差金额不成立"}


def reconcile_check(parts, total, tolerance=0.01, tolerance_rate=None, label="分项合计"):
    """勾稽校验：分项合计 与 报表汇总数 是否闭合（结算/审计底稿必做的第一道校验）。

    parts : [金额, ...] 或 {"分项名": 金额}
    total : 报表上的汇总数
    tolerance / tolerance_rate : 绝对允差 / 相对允差(%)，给 tolerance_rate 时按相对允差判定
    """
    if isinstance(parts, dict):
        items = [(str(k), float(v)) for k, v in parts.items()]
    else:
        items = [("第%d项" % (i + 1), float(v)) for i, v in enumerate(parts or [])]
    if not items:
        raise ValueError("parts 为空，无法勾稽")
    if tolerance < 0 or (tolerance_rate is not None and tolerance_rate < 0):
        raise ValueError("允差不得为负")
    s = sum(v for _, v in items)
    diff = s - total
    limit = (abs(total) * tolerance_rate / 100.0) if tolerance_rate is not None else tolerance
    ok = abs(diff) <= limit + 1e-9
    return {"校验对象": label, "分项数": len(items),
            "分项合计": _f(s, 4), "报表汇总数": _f(total, 4),
            "差额(合计−汇总)": _f(diff, 4),
            "差额率(%)": (_f(diff / total * 100, 2) if abs(total) > 1e-12 else None),
            "允差": _f(limit, 4),
            "勾稽结论": ("OK 勾稽一致" if ok else
                       "不一致：差额 %.4f 超出允差 %.4f，须逐项核对，不得以「四舍五入/尾差」解释"
                       % (diff, limit)),
            "分项明细": [{"分项": k, "金额": _f(v, 4)} for k, v in items],
            "提示": "汇总数应能由分项逐项加总复算；不一致时优先查漏项、重项、口径混用（含税/除税）"}


def sample_plan(items, threshold_rate=0.05, coverage_target=0.70, name=""):
    """检查范围方案：重点核查（大额必查）+ 覆盖率分层，输出必查/抽中/未覆盖清单。

    items : [{"项目": 名称, "金额": 金额}, ...]（同一口径，通常为送审或结算金额）
    规则：① 单项金额 ≥ 总额 × threshold_rate → 必查；
          ② 其余按金额从大到小累计，直至（必查+抽中）覆盖金额占比 ≥ coverage_target → 抽中；
          ③ 剩余为未覆盖，须评估是否追加程序或声明审计范围限制。
    说明：这是工程审计常用的“抓大放小 + 覆盖率控制”做法，**不是统计抽样**；
          如委托方要求统计抽样或明确的重要性水平，须另行按其方案设计。
    """
    if not items:
        raise ValueError("items 为空，无法制定检查范围")
    if not (0 <= threshold_rate < 1):
        raise ValueError("threshold_rate 须在 [0,1) 之间，收到 %s" % threshold_rate)
    if not (0 < coverage_target <= 1):
        raise ValueError("coverage_target 须在 (0,1] 之间，收到 %s" % coverage_target)
    rows = []
    for i, it in enumerate(items, 1):
        amt = float(it.get("金额", 0) or 0)
        if amt < 0:
            raise ValueError("金额不得为负：%s" % it.get("项目", i))
        rows.append({"项目": it.get("项目", "第%d项" % i), "金额": amt})
    total = sum(r["金额"] for r in rows)
    if total <= 0:
        raise ValueError("金额合计为 0，无法制定检查范围")
    thr = total * threshold_rate
    must = [r for r in rows if r["金额"] >= thr - 1e-9]
    rest = sorted([r for r in rows if r["金额"] < thr - 1e-9], key=lambda x: -x["金额"])
    covered = sum(r["金额"] for r in must)
    pick = []
    for r in rest:
        if covered / total >= coverage_target - 1e-9:
            break
        pick.append(r)
        covered += r["金额"]
    picked_keys = {(r["项目"], r["金额"]) for r in must + pick}
    missed = [r for r in rows if (r["项目"], r["金额"]) not in picked_keys]
    return {"方案名称": name or "检查范围方案",
            "总额": _f(total, 2), "项数": len(rows),
            "重点核查阈值": _f(thr, 4), "覆盖目标(%)": _f(coverage_target * 100, 2),
            "必查项（大额重点核查）": sorted(must, key=lambda x: -x["金额"]),
            "必查金额": _f(sum(r["金额"] for r in must), 2),
            "抽中项（覆盖率内）": pick,
            "抽中金额": _f(sum(r["金额"] for r in pick), 2),
            "覆盖率(%)": _f(covered / total * 100, 2),
            "未覆盖项": missed,
            "未覆盖金额": _f(sum(r["金额"] for r in missed), 2),
            "未覆盖占比(%)": _f(sum(r["金额"] for r in missed) / total * 100, 2),
            "提示": ("未覆盖项须评估是否追加程序，或在报告中声明检查范围限制；"
                    "本方案为“抓大放小+覆盖率控制”的工程审计常用做法，不是统计抽样")}


# ---------------------------------------------------------------------------
# 指标对标（指标衡角色算力支撑）
# ---------------------------------------------------------------------------
def benchmark_index(total_cost, area, benchmarks=None, area_caliber=None):
    """单方指标与多基准对标。

    total_cost : 总造价（万元）；area : 建筑面积（㎡）；须与 area_caliber 口径一致
    benchmarks : {名称: 对标单方指标(万元/㎡)}，分别算偏差率(%)
    偏差率 = (本项目 − 标杆)/标杆；正=高于标杆，负=低于标杆。
    """
    if area <= 0:
        raise ValueError("面积必须为正，收到 area=%s" % area)
    if total_cost < 0:
        raise ValueError("总造价不得为负，收到 total_cost=%s" % total_cost)
    unit = total_cost / area
    devs, texts = {}, {}
    if benchmarks:
        for name, val in benchmarks.items():
            if val <= 0:
                raise ValueError("对标指标须为正，%s=%s" % (name, val))
            d = (unit - val) / val * 100.0
            devs[name] = _f(d, 2)
            texts[name] = ("高于标杆 %.2f%%" % d) if d > 0 else (("低于标杆 %.2f%%" % -d) if d < 0 else "与标杆持平")
    return {"单方指标(万元/㎡)": _f(unit, 4), "单方指标(元/㎡)": _f(unit * 10000, 2),
            "面积口径": area_caliber or "未标注（建筑/使用/结构面积必须明确）",
            "各基准对标偏差率(%)": devs, "偏差方向说明": texts,
            "可比性提示": "对标须同业态、同口径、同时点；不可比时只给区间并说明，禁止强行对标"}


def index_metrics(total_cost, area, benchmark=None, quantities=None, area_caliber=None):
    """造价指标分析：单方指标（万元/㎡ 与 元/㎡）、对标偏差率、含量指标。

    quantities: {名称: 工程量}，分别除以面积得到含量指标（如 钢筋 t/㎡、混凝土 m³/㎡）
    """
    if area <= 0:
        raise ValueError("面积必须为正，收到 area=%s" % area)
    if total_cost < 0:
        raise ValueError("总造价不得为负，收到 total_cost=%s" % total_cost)
    unit_wan = total_cost / area
    unit_yuan = unit_wan * 10000.0
    dev, direction = None, None
    if benchmark is not None:
        if benchmark <= 0:
            raise ValueError("对标单方指标须为正，收到 benchmark=%s" % benchmark)
        dev = (unit_wan - benchmark) / benchmark * 100.0
        direction = "高于标杆" if dev > 0 else ("低于标杆" if dev < 0 else "与标杆持平")
    content = {}
    if quantities:
        for k, v in quantities.items():
            if v < 0:
                raise ValueError("含量指标工程量不得为负，%s=%s" % (k, v))
            content[k] = _f(v / area, 4)
    return {"单方指标(万元/㎡)": _f(unit_wan, 4),
            "单方指标(元/㎡)": _f(unit_yuan, 2),
            "面积口径": area_caliber or "未标注（建筑/使用/结构面积必须明确）",
            "对标单方指标(万元/㎡)": (benchmark if benchmark is not None else None),
            "对标偏差率(%)": (round(dev, 2) if dev is not None else None),
            "偏差方向": direction,
            "含量指标": content,
            "含量指标单位": "工程量/㎡（须与面积同口径，缺失项不凑数）",
            "合理性提示": "单方指标异常偏离须先核查口径（含税/除税、是否含精装/景观/地下），再判断异常"}

# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def selftest():
    checks = []

    def chk(name, cond, info=""):
        checks.append((name, bool(cond), info))

    def expect_error(name, fn):
        try:
            fn()
            chk(name, False, "未抛错")
        except ValueError:
            chk(name, True)

    # —— 调值公式法 ——
    r = adjust_formula(1000, 0.15, "0.25,110,100;0.30,105,100;0.30,108,100")
    chk("adjust_formula ΔP=64", abs(r["调差金额ΔP(万元)"] - 64.0) < 1e-6, r["调差金额ΔP(万元)"])
    chk("adjust_formula 权重校验≈1", abs(r["权重校验(A+ΣB)"] - 1.0) < 1e-6, r["权重校验(A+ΣB)"])
    chk("adjust_formula 一致性OK", r["权重一致性提示"] == "OK", r["权重一致性提示"])
    expect_error("adjust_formula F0=0 拦截", lambda: adjust_formula(1000, 0.15, "0.25,110,0"))
    r2 = adjust_formula(1000, 0.15, "0.25,110,100;0.30,105,100;0.20,108,100")
    chk("adjust_formula A+ΣB≠1 提示", r2["权重一致性提示"] != "OK", r2["权重一致性提示"])
    # 风险幅度：指数比 1.20、幅度 5% → excess 只调 15%；cap 封顶 5%
    r3 = adjust_formula(1000, 0.0, "1,120,100", risk=5.0, risk_mode="excess")
    chk("adjust_formula 风险幅度(超出部分) ΔP=150", abs(r3["调差金额ΔP(万元)"] - 150.0) < 1e-6, r3["调差金额ΔP(万元)"])
    r4 = adjust_formula(1000, 0.0, "1,120,100", risk=5.0, risk_mode="cap")
    chk("adjust_formula 风险幅度(封顶) ΔP=50", abs(r4["调差金额ΔP(万元)"] - 50.0) < 1e-6, r4["调差金额ΔP(万元)"])
    r5 = adjust_formula(1000, 0.0, "1,103,100", risk=5.0)
    chk("adjust_formula 幅度内不调 ΔP=0", abs(r5["调差金额ΔP(万元)"]) < 1e-9, r5["调差金额ΔP(万元)"])
    r6 = adjust_formula(1000, 0.0, "1,90,100", risk=5.0)
    chk("adjust_formula 下跌超幅 ΔP=-50", abs(r6["调差金额ΔP(万元)"] + 50.0) < 1e-6, r6["调差金额ΔP(万元)"])

    # —— 造价信息调整法（三档规则）——
    r = adjust_info(3200, 3000, 2950, 5, 1000)
    chk("adjust_info 投标<基准 涨超幅 结算=3000", abs(r["结算单价"] - 3000.0) < 1e-6, r["结算单价"])
    chk("adjust_info 调差合价=50000", abs(r["调差合价"] - 50000.0) < 1e-6, r["调差合价"])
    r = adjust_info(3500, 3000, 3200, 5, 100)
    chk("adjust_info 投标>基准 涨幅看投标价 结算=3340", abs(r["结算单价"] - 3340.0) < 1e-6, r["结算单价"])
    r = adjust_info(2700, 3000, 3200, 5, 100)
    chk("adjust_info 投标>基准 跌幅看基准价 结算=3050", abs(r["结算单价"] - 3050.0) < 1e-6, r["结算单价"])
    r = adjust_info(3100, 3000, 3000, 5, 100)
    chk("adjust_info 投标=基准 幅度内不调", r["是否调整"] is False, r["是否调整"])
    r = adjust_info(3200, 3000, 3000, 5, 100)
    chk("adjust_info 投标=基准 涨超幅 结算=3050", abs(r["结算单价"] - 3050.0) < 1e-6, r["结算单价"])
    expect_error("adjust_info base=0 拦截", lambda: adjust_info(3200, 0, 2950, 5, 1000))

    # —— 审计核心 ——
    r = audit_reduction(1200, 1080)
    chk("audit_reduction 审减额=120", abs(r["审减额(万元)"] - 120.0) < 1e-6, r["审减额(万元)"])
    chk("audit_reduction 审减率=10%", abs(r["审减率(%)"] - 10.0) < 1e-6, r["审减率(%)"])
    chk("audit_reduction 边界不超预警(=10%)", r["超预警线"] is False, r["超预警线"])
    chk("audit_reduction 反向验算=1200", abs(r["反向验算(万元)"] - 1200.0) < 1e-6, r["反向验算(万元)"])
    expect_error("audit_reduction submit=0 拦截", lambda: audit_reduction(0, 1080))
    r = audit_reduction_detail(1200, 1080, {"工程量核减": 60, "单价核减": 40, "取费核减": 20})
    chk("audit_reduction_detail 明细校验OK", r["明细校验"] == "OK", r["明细校验"])
    r = audit_reduction_detail(1200, 1080, {"工程量核减": 60})
    chk("audit_reduction_detail 明细不符告警", r["明细校验"] != "OK", r["明细校验"])
    r = audit_reduction_detail(1200, 1080)
    chk("audit_reduction_detail 无明细禁止下结论", "禁止" in r["明细校验"], r["明细校验"])

    chk("list_total=500", abs(list_total([(100, 1), (200, 2)])["清单合价"] - 500.0) < 1e-6)
    expect_error("list_total 空 拦截", lambda: list_total([]))
    expect_error("list_total 负数 拦截", lambda: list_total([(100, -1)]))
    chk("claim_amount=150", abs(claim_amount(10, 5, 100)["索赔额(万元)"] - 150.0) < 1e-6)
    r = variance(100, 120)
    chk("variance=20/20%", abs(r["偏差(万元)"] - 20) < 1e-6 and abs(r["偏差率(%)"] - 20) < 1e-6)
    expect_error("variance budget=0 拦截", lambda: variance(0, 120))
    chk("settlement_total=600", abs(settlement_total([100, 200, 300])["结算总价(万元)"] - 600) < 1e-6)

    # —— 工程量偏差 ±15% 调价 ——
    r = qty_deviation_adjust(1000, 1300, 380, over_factor=0.9, under_factor=1.1)
    chk("qty_deviation 超15% 调整后=488300", abs(r["调整后合价(元)"] - 488300.0) < 1e-6, r["调整后合价(元)"])
    chk("qty_deviation 超15% 标记调价", r["是否调整单价"] is True)
    r = qty_deviation_adjust(1000, 800, 380, over_factor=0.9, under_factor=1.1)
    chk("qty_deviation 减20% 调整后=334400", abs(r["调整后合价(元)"] - 334400.0) < 1e-6, r["调整后合价(元)"])
    r = qty_deviation_adjust(1000, 1150, 380)
    chk("qty_deviation 偏差=15% 不调", r["是否调整单价"] is False, r["调整后合价(元)"])
    r = qty_deviation_adjust(1000, 1100, 380)
    chk("qty_deviation 偏差内 不调 418000", abs(r["调整后合价(元)"] - 418000.0) < 1e-6, r["调整后合价(元)"])
    expect_error("qty_deviation list_qty=0 拦截", lambda: qty_deviation_adjust(0, 100, 380))

    # —— 造价汇总 / 预付款 / 质保金 / 逾期利息 ——
    r = project_total(800, 150, 80, gov_fee=40, tax_rate=0.09)
    chk("project_total 税前=1070", abs(r["税前工程造价(万元)"] - 1070.0) < 1e-6, r["税前工程造价(万元)"])
    chk("project_total 合计=1166.3", abs(r["工程造价合计(万元)"] - 1166.3) < 1e-6, r["工程造价合计(万元)"])
    r = project_total(800, 150, 80, gov_fee=40, tax_rate=0.09, provisional=120)
    chk("project_total 暂列金额剔除提示", "暂列金额" in r["提示"] and abs(r["剔除暂列金额后确定性造价(万元)"] - 1046.3) < 1e-6, r["提示"])
    expect_error("project_total 规费缺基数 拦截", lambda: project_total(800, gov_fee_rate=0.018))
    r = prepayment_deduct(10000, 0.2, 0.6, 8000)
    chk("prepayment 预付款=2000", abs(r["预付款总额(万元)"] - 2000.0) < 1e-6, r["预付款总额(万元)"])
    chk("prepayment 本次扣回=800", abs(r["本次应扣回(万元)"] - 800.0) < 1e-6, r["本次应扣回(万元)"])
    r = prepayment_deduct(10000, 0.2, 0.6, 5000)
    chk("prepayment 未到起扣点不扣", abs(r["本次应扣回(万元)"]) < 1e-9, r["本次应扣回(万元)"])
    r = retention_amount(10900)
    chk("retention 3%=327", abs(r["质量保证金(万元)"] - 327.0) < 1e-6, r["质量保证金(万元)"])
    expect_error("retention 超 3% 上限拦截", lambda: retention_amount(10900, rate=0.05))
    r = late_payment_interest(1000, 100, lpr=0.031)
    chk("late_interest LPR 计息≈8.4932", abs(r["逾期付款利息(万元)"] - 8.49315) < 1e-4, r["逾期付款利息(万元)"])
    r = late_payment_interest(1000, 100, lpr=0.031, agreed_rate=0.02)
    chk("late_interest 有约定从约定（不擅自替换约定利率）",
        abs(r["逾期付款利息(万元)"] - 5.47945) < 1e-4, r["计息依据"])
    chk("late_interest 约定低于LPR 给出警示", "低于同期 LPR" in r["提示"], r["提示"][:40])
    expect_error("late_interest 无利率拦截", lambda: late_payment_interest(1000, 100))

    # —— 组价（单位口径）——
    r = compose_price(100, 400, 50, 0.05, 0.04, 0.03)
    chk("compose_price 综合单价=616", abs(r["综合单价(元/计量单位)"] - 616.0) < 1e-6, r["综合单价(元/计量单位)"])
    chk("compose_price 税前=616", abs(r["税前综合单价(元/计量单位)"] - 616.0) < 1e-6)
    chk("compose_price 单位标注为元", "元" in r["计量单位"], r["计量单位"])
    r = compose_price(0.01, 0.04, 0.005, 0.05, 0.04, 0.03, unit="万元")
    chk("compose_price 万元口径", abs(r["综合单价(万元/计量单位)"] - 0.0616) < 1e-9, r["综合单价(万元/计量单位)"])
    expect_error("compose_price 全0 拦截", lambda: compose_price(0, 0, 0, 0.05, 0.04, 0.03))
    expect_error("compose_price 负税率拦截", lambda: compose_price(1, 1, 1, 0.05, 0.04, tax_rate=-0.1))

    ex = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "references", "data", "local_rates.example.json")
    if os.path.exists(ex):
        r = compose_price_with_rates(0.01, 0.02, 0.005, ex)
        chk("local_rates 数据来源标注", "数据来源" in r, r.get("数据来源"))
        chk("local_rates 标注示例数据", r.get("是否示例数据") is True, r.get("是否示例数据"))
        chk("local_rates 管理费率取自文件", abs(r["管理费(5.0%)(元/计量单位)"] - 0.00175) < 2e-4, r["管理费(5.0%)(元/计量单位)"])
        chk("local_rates 含税综合单价>税前",
            r["综合单价(元/计量单位)"] > r["税前综合单价(元/计量单位)"], r)
        r = compose_price_from_rates({"C30商品混凝土 元/m³": 2.5}, ex, labor_days=3,
                                     machines={"塔吊 元/台班": 0.1})
        chk("compose_from_rates 材料费=1200", abs(r["材料费(元/计量单位)"] - 1200.0) < 1e-6, r["材料费(元/计量单位)"])
        chk("compose_from_rates 综合单价含税=1977.696", abs(r["综合单价(元/计量单位)"] - 1977.7) < 0.01, r["综合单价(元/计量单位)"])
        expect_error("compose_from_rates 缺价格 fail-closed",
                     lambda: compose_price_from_rates({"不存在的材料": 1.0}, ex))
    expect_error("load_local_rates 缺文件 拦截", lambda: load_local_rates("不存在的文件.json"))

    # —— 索赔 ——
    r = delay_claim("2025-03-01", "2025-03-20", 28, 30, 2.0, 10.0)
    chk("delay_claim 时效内", r["是否在时效内"] is True, r["是否在时效内"])
    chk("delay_claim 费用=70", abs(r["费用索赔额(万元)"] - 70.0) < 1e-6, r["费用索赔额(万元)"])
    r2 = delay_claim("2025-03-01", "2025-05-01", 28, 30, 2.0, 10.0)
    chk("delay_claim 超时效", r2["是否在时效内"] is False, r2["是否在时效内"])
    r3 = delay_claim("2025-03-01", "2025-03-20", 28, 30, 2.0, 10.0, total_float=10)
    chk("delay_claim 扣时差 工期=20 费用=50", abs(r3["工期索赔(天)"] - 20) < 1e-6 and abs(r3["费用索赔额(万元)"] - 50.0) < 1e-6, r3["费用索赔额(万元)"])
    r4 = delay_claim("2025-03-01", "2025-03-20", 28, 30, 2.0, 0.0, event_end_date="2025-04-30")
    chk("delay_claim 持续事件最终报告截止=2025-05-28", r4["最终索赔报告截止日"] == "2025-05-28", r4.get("最终索赔报告截止日"))
    expect_error("delay_claim 倒序 拦截", lambda: delay_claim("2025-05-01", "2025-03-01", 28, 30, 2.0, 10.0))
    chk("delay_extension 关键线路=30", abs(delay_extension(30, 0)["可索赔工期(天)"] - 30) < 1e-6)
    chk("delay_extension 时差内=0", abs(delay_extension(30, 40)["可索赔工期(天)"]) < 1e-9)

    # —— 指标 ——
    r = index_metrics(10000, 10000)
    chk("index 单方=1万/㎡", abs(r["单方指标(万元/㎡)"] - 1.0) < 1e-6, r["单方指标(万元/㎡)"])
    chk("index 单方=10000元/㎡", abs(r["单方指标(元/㎡)"] - 10000.0) < 1e-6)
    r = index_metrics(12000, 10000, benchmark=1.0)
    chk("index 偏差=20%", abs(r["对标偏差率(%)"] - 20.0) < 1e-6, r["对标偏差率(%)"])
    expect_error("index area=0 拦截", lambda: index_metrics(10000, 0))
    r = index_metrics(5000, 10000, quantities={"钢筋": 500.0, "混凝土": 3000.0})
    chk("index 钢筋含量=0.05t/㎡", abs(r["含量指标"]["钢筋"] - 0.05) < 1e-6, r["含量指标"]["钢筋"])
    r = benchmark_index(12000, 10000, {"同业均值": 1.0, "限额指标": 1.1})
    chk("benchmark 偏差=20%", abs(r["各基准对标偏差率(%)"]["同业均值"] - 20.0) < 1e-6)
    chk("benchmark 偏差=9.09%", abs(r["各基准对标偏差率(%)"]["限额指标"] - 9.09) < 0.01)
    chk("benchmark 方向说明", "高于标杆" in r["偏差方向说明"]["同业均值"], r["偏差方向说明"])

    # —— 审计作业支持：归因 / 多期调差 / 勾稽 / 检查范围 ——
    r = audit_attribution(1000, 800, 380, 380)
    chk("attribution 量差 76000", abs(r["工程量核减影响(元)"] - 76000) < 1e-6, r["工程量核减影响(元)"])
    chk("attribution 归因=工程量核减为主", r["归因结论"] == "工程量核减为主", r["归因结论"])
    r = audit_attribution(1000, 1000, 380, 350)
    chk("attribution 纯价差 30000", abs(r["单价核减影响(元)"] - 30000) < 1e-6, r["单价核减影响(元)"])
    chk("attribution 价差占比 100%", abs(r["价差占总核减(%)"] - 100.0) < 1e-6, r["价差占总核减(%)"])
    r = audit_attribution(1000, 800, 380, 360)
    chk("attribution 量价混合自洽 92000", abs(r["审减额(元)"] - 92000) < 1e-6, r["审减额(元)"])
    chk("attribution 反向验算", r["反向验算"].startswith("OK"), r["反向验算"])
    expect_error("attribution 负数拦截", lambda: audit_attribution(-1, 1, 1, 1))

    r = material_adjust_weighted([{"期次": "2026-01", "用量": 100, "信息价": 500},
                                  {"期次": "2026-02", "用量": 300, "信息价": 520}],
                                 base=480, bid=470, risk=5)
    chk("weighted 合计调差 4800（仅第二期超幅度）", abs(r["调差金额"] - 4800) < 1e-6, r["调差金额"])
    chk("weighted 加权平均信息价 515", abs(r["加权平均信息价"] - 515) < 1e-9, r["加权平均信息价"])
    chk("weighted 明细期数=2", len(r["各期明细"]) == 2, len(r["各期明细"]))
    expect_error("weighted 空期间拦截", lambda: material_adjust_weighted([], 100, 100))

    r = reconcile_check({"分部分项": 800, "措施": 150, "其他": 80, "规费": 40, "税金": 30}, 1100)
    chk("reconcile 一致 OK", r["勾稽结论"].startswith("OK"), r["勾稽结论"])
    r = reconcile_check([800, 150, 80, 40, 30], 1150)
    chk("reconcile 差额 -50 / 差额率 -4.35%",
        abs(r["差额(合计−汇总)"] + 50) < 1e-9 and abs(abs(r["差额率(%)"]) - 4.35) < 1e-9, r["差额率(%)"])
    chk("reconcile 不一致结论", r["勾稽结论"].startswith("不一致"), r["勾稽结论"])
    r = reconcile_check([1000], 1000.005, tolerance_rate=0.001)
    chk("reconcile 相对允差内判 OK", r["勾稽结论"].startswith("OK"), r["勾稽结论"])

    r = sample_plan([{"项目": "A", "金额": 600}, {"项目": "B", "金额": 200},
                     {"项目": "C", "金额": 100}, {"项目": "D", "金额": 60},
                     {"项目": "E", "金额": 40}], threshold_rate=0.05, coverage_target=0.9)
    chk("sample 必查含 A/B/C/D", len(r["必查项（大额重点核查）"]) == 4, len(r["必查项（大额重点核查）"]))
    chk("sample 覆盖率 96%", abs(r["覆盖率(%)"] - 96.0) < 1e-6, r["覆盖率(%)"])
    chk("sample 未覆盖含 E", [x["项目"] for x in r["未覆盖项"]] == ["E"], r["未覆盖项"])
    expect_error("sample 覆盖率越界拦截", lambda: sample_plan([{"项目": "A", "金额": 1}], coverage_target=1.5))

    ok = sum(1 for _, c, _ in checks if c)
    for name, cond, info in checks:
        print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, ("← %s" % info) if info and not cond else ""))
    print("SELFTEST: %s（%d/%d）" % ("ALL PASS" if ok == len(checks) else "FAILED", ok, len(checks)))
    return ok == len(checks)


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------
def _parse_items(s):
    """解析 '量:单价;量:单价' 或 '数,数' → list，非法格式抛 ValueError。"""
    s = str(s or "").strip().strip("[]")
    if not s:
        raise ValueError("items 为空")
    out = []
    for seg in s.replace("；", ";").split(";"):
        seg = seg.strip()
        if not seg:
            continue
        if ":" in seg or "：" in seg:
            parts = seg.replace("：", ":").split(":")
            if len(parts) != 2:
                raise ValueError("items 每项须为 '工程量:单价'，收到 %r" % seg)
            out.append((float(parts[0]), float(parts[1])))
        else:
            out.append(float(seg))
    if not out:
        raise ValueError("items 为空")
    return out


def _parse_kv(s, cast=float, sep=":"):
    """解析 '键:值;键:值' → dict。"""
    d = {}
    s = str(s or "").strip().strip("{}")
    if not s:
        return d
    for seg in s.replace("；", ";").split(";"):
        seg = seg.strip()
        if not seg:
            continue
        if (sep not in seg) and ("：" not in sep):
            raise ValueError("键值对格式错误（须 名称%s数值）：%r" % (sep, seg))
        parts = seg.replace("：", sep).split(sep)
        if len(parts) < 2:
            raise ValueError("键值对格式错误（须 名称%s数值）：%r" % (sep, seg))
        k = parts[0].strip()
        v = sep.join(parts[1:]).strip() if sep in parts[1:] else parts[1].strip()
        d[k] = cast(v)
    return d


def _parse_periods(s):
    """解析 '期次:用量:信息价;...' → list[dict]，非法格式抛 ValueError。"""
    out = []
    for seg in str(s or "").replace("；", ";").split(";"):
        seg = seg.strip()
        if not seg:
            continue
        parts = [x.strip() for x in seg.replace("，", ",").split(":")]
        if len(parts) != 3:
            raise ValueError("periods 每项须为 '期次:用量:信息价'，收到：%r" % seg)
        try:
            out.append({"期次": parts[0], "用量": float(parts[1]), "信息价": float(parts[2])})
        except ValueError:
            raise ValueError("periods 含非数字：%r" % seg)
    if not out:
        raise ValueError("periods 为空")
    return out


def main():
    ap = argparse.ArgumentParser(description="工程造价审计真实计算引擎（金额除特别说明外单位为万元）")
    ap.add_argument("--func", default=None, help="计算函数名；不带 --func 时用 --selftest")
    ap.add_argument("--list", action="store_true", help="列出可用函数")
    # 调值/调差
    ap.add_argument("--p0", type=float, default=None, help="[adjust_formula] 当期完成金额(万元)")
    ap.add_argument("--A", type=float, default=None, help="[adjust_formula] 定值权重")
    ap.add_argument("--pairs", default=None, help='[adjust_formula] "权重,现行指数,基准指数;..."')
    ap.add_argument("--risk", type=float, default=None, help="[adjust_formula/adjust_info] 约定风险幅度(%%), 如 5")
    ap.add_argument("--risk_mode", choices=["excess", "cap", "full"], default="excess")
    ap.add_argument("--current", type=float, default=None, help="[adjust_info] 施工期信息价")
    ap.add_argument("--base", type=float, default=None, help="[adjust_info] 基准价")
    ap.add_argument("--bid", type=float, default=None, help="[adjust_info] 投标报价")
    ap.add_argument("--qty", type=float, default=1.0, help="[adjust_info] 工程量")
    # 审计
    ap.add_argument("--submit", type=float, default=None)
    ap.add_argument("--approved", type=float, default=None)
    ap.add_argument("--warn_line", type=float, default=0.10, help="[audit_reduction] 审减率预警线，默认 0.10")
    ap.add_argument("--details", default=None, help='[audit_reduction_detail] "工程量核减:60;单价核减:40"')
    ap.add_argument("--items", default=None, help='[list_total] "100:0.05;200:0.08"；[settlement_total] "800,150,80"')
    ap.add_argument("--days", type=float, default=0, help="[claim_amount] 有效延误天数")
    ap.add_argument("--daily_loss", type=float, default=0)
    ap.add_argument("--extra", type=float, default=0)
    ap.add_argument("--budget", type=float, default=None)
    ap.add_argument("--actual", type=float, default=None)
    # 工程量偏差
    ap.add_argument("--list_qty", type=float, default=None)
    ap.add_argument("--actual_qty", type=float, default=None)
    ap.add_argument("--unit_price", type=float, default=None)
    ap.add_argument("--over_factor", type=float, default=0.9)
    ap.add_argument("--under_factor", type=float, default=1.1)
    ap.add_argument("--low", type=float, default=0.85)
    ap.add_argument("--high", type=float, default=1.15)
    # 造价汇总
    ap.add_argument("--fbfx", type=float, default=None, help="[project_total] 分部分项工程费(万元)")
    ap.add_argument("--measures", type=float, default=0.0)
    ap.add_argument("--others", type=float, default=0.0)
    ap.add_argument("--gov_fee", type=float, default=None)
    ap.add_argument("--gov_fee_rate", type=float, default=None)
    ap.add_argument("--gov_fee_base", type=float, default=None)
    ap.add_argument("--provisional", type=float, default=0.0)
    ap.add_argument("--tax_rate", type=float, default=None, help="增值税率，如一般计税 0.09 / 简易计税 0.03")
    # 预付款/质保金/利息
    ap.add_argument("--contract", type=float, default=None, help="[prepayment_deduct] 合同价(万元)")
    ap.add_argument("--prepay_rate", type=float, default=None)
    ap.add_argument("--material_ratio", type=float, default=None)
    ap.add_argument("--cumulative", type=float, default=0.0)
    ap.add_argument("--already_deducted", type=float, default=0.0)
    ap.add_argument("--point_ratio", type=float, default=None)
    ap.add_argument("--settlement", type=float, default=None, help="[retention_amount] 结算总额(万元)")
    ap.add_argument("--retention_rate", type=float, default=0.03)
    ap.add_argument("--amount", type=float, default=None, help="[late_payment_interest] 欠付本金(万元)")
    ap.add_argument("--late_days", type=float, default=None, help="[late_payment_interest] 逾期天数")
    ap.add_argument("--lpr", type=float, default=None, help="同期 1 年期 LPR（年利率小数，如 0.031）")
    ap.add_argument("--agreed_rate", type=float, default=None, help="合同约定年利率（小数）")
    # 审计作业支持
    ap.add_argument("--submit_qty", type=float, default=None, help="[audit_attribution] 送审工程量")
    ap.add_argument("--audited_qty", type=float, default=None, help="[audit_attribution] 审定工程量")
    ap.add_argument("--submit_price", type=float, default=None, help="[audit_attribution] 送审综合单价")
    ap.add_argument("--audited_price", type=float, default=None, help="[audit_attribution] 审定综合单价")
    ap.add_argument("--periods", default=None,
                    help='[material_adjust_weighted] "期次:用量:信息价;..."，如 "2026-03:120:500;2026-04:200:520"')
    ap.add_argument("--parts", default=None, help='[reconcile_check] 分项金额 "800;150;80;40;30"')
    ap.add_argument("--total", type=float, default=None, help="[reconcile_check] 报表汇总数")
    ap.add_argument("--tolerance", type=float, default=0.01, help="[reconcile_check] 绝对允差")
    ap.add_argument("--tolerance_rate", type=float, default=None, help="[reconcile_check] 相对允差(%%)")
    ap.add_argument("--sample_items", default=None,
                    help='[sample_plan] 项目金额清单 "土建:8000;安装:4000;签证:60"')
    ap.add_argument("--threshold_rate", type=float, default=0.05,
                    help="[sample_plan] 必查阈值(占总额比例)，默认 0.05")
    ap.add_argument("--coverage_target", type=float, default=0.70, help="[sample_plan] 覆盖目标，默认 0.70")
    # 组价
    ap.add_argument("--labor", type=float, default=0.0)
    ap.add_argument("--material", type=float, default=0.0)
    ap.add_argument("--machine", type=float, default=0.0)
    ap.add_argument("--manage_rate", type=float, default=None)
    ap.add_argument("--profit_rate", type=float, default=None)
    ap.add_argument("--risk_amp", type=float, default=None)
    ap.add_argument("--unit", default="元", help="组价金额的计量单位（元/万元），用于输出标签")
    ap.add_argument("--rates_file", default=None,
                    help="当地价格/费率数据文件(local_rates.json)；提供后组价/取费自动引用并标注数据来源")
    ap.add_argument("--materials", default=None, help='[compose_price_from_rates] "C30商品混凝土:2.5;HRB400钢筋:0.06"')
    ap.add_argument("--machines", default=None, help='[compose_price_from_rates] "塔吊:0.1"')
    ap.add_argument("--labor_days", type=float, default=0.0, help="[compose_price_from_rates] 人工工日数")
    ap.add_argument("--extra_prices", default=None, help='手工补充缺失价格 "名称:单价"（须真实数据）')
    ap.add_argument("--allow_missing", action="store_true", help="允许材料价缺失（默认 fail-closed 报错）")
    # 索赔
    ap.add_argument("--event_date", default=None)
    ap.add_argument("--claim_date", default=None)
    ap.add_argument("--notice_days", type=int, default=28)
    ap.add_argument("--delay_days", type=float, default=0)
    ap.add_argument("--total_float", type=float, default=0.0, help="线路总时差(天)")
    ap.add_argument("--extension_cap", type=float, default=None)
    ap.add_argument("--event_end_date", default=None)
    ap.add_argument("--final_report_days", type=int, default=28)
    # 指标
    ap.add_argument("--total_cost", type=float, default=None)
    ap.add_argument("--area", type=float, default=None)
    ap.add_argument("--area_caliber", default=None, help="面积口径：建筑/使用/结构")
    ap.add_argument("--benchmark", type=float, default=None)
    ap.add_argument("--benchmarks", default=None, help='"同业均值:1.0;限额指标:1.1"')
    ap.add_argument("--quantities", default=None, help='"钢筋:500;混凝土:3000"')
    ap.add_argument("--selftest", action="store_true", help="运行自检断言")
    args = ap.parse_args()

    if args.list:
        print("可用函数：adjust_formula, adjust_info, audit_reduction, audit_reduction_detail, "
              "list_total, claim_amount, variance, settlement_total, qty_deviation_adjust, "
              "project_total, prepayment_deduct, retention_amount, late_payment_interest, "
              "compose_price, compose_price_with_rates, compose_price_from_rates, "
              "delay_claim, delay_extension, benchmark_index, index_metrics, "
              "audit_attribution, material_adjust_weighted, reconcile_check, sample_plan, selftest")
        return 0
    if args.selftest:
        return 0 if selftest() else 1
    if not args.func:
        ap.print_help()
        print("\n提示：先跑 python calc_engine.py --selftest 自检；用 --list 查看可用函数。")
        return 1

    def need(**kw):
        miss = [k for k, v in kw.items() if v is None]
        if miss:
            raise ValueError("缺少必填参数：%s" % "、".join("--" + m for m in miss))

    try:
        f = args.func
        if f == "adjust_formula":
            need(p0=args.p0, A=args.A, pairs=args.pairs)
            r = adjust_formula(args.p0, args.A, args.pairs, args.risk, args.risk_mode)
        elif f == "adjust_info":
            need(current=args.current, base=args.base, bid=args.bid)
            r = adjust_info(args.current, args.base, args.bid,
                            args.risk if args.risk is not None else 5.0, args.qty)
        elif f == "audit_reduction":
            need(submit=args.submit, approved=args.approved)
            r = audit_reduction(args.submit, args.approved, args.warn_line)
        elif f == "audit_reduction_detail":
            need(submit=args.submit, approved=args.approved)
            r = audit_reduction_detail(args.submit, args.approved,
                                       _parse_kv(args.details) if args.details else None,
                                       args.warn_line)
        elif f == "list_total":
            need(items=args.items)
            pairs = _parse_items(args.items)
            if any(not isinstance(x, tuple) for x in pairs):
                raise ValueError("list_total 需 '工程量:单价' 形式")
            r = list_total(pairs)
        elif f == "claim_amount":
            r = claim_amount(args.days, args.daily_loss, args.extra)
        elif f == "variance":
            need(budget=args.budget, actual=args.actual)
            r = variance(args.budget, args.actual)
        elif f == "settlement_total":
            need(items=args.items)
            vals = [float(x) for x in str(args.items).strip("[]").replace("；", ";").split(";")
                    for x in (x.split(",") if "," in x else [x]) if str(x).strip()]
            r = settlement_total(vals)
        elif f == "qty_deviation":
            need(list_qty=args.list_qty, actual_qty=args.actual_qty, unit_price=args.unit_price)
            r = qty_deviation_adjust(args.list_qty, args.actual_qty, args.unit_price,
                                     args.low, args.high, args.over_factor, args.under_factor)
        elif f == "project_total":
            need(fbfx=args.fbfx)
            r = project_total(args.fbfx, args.measures, args.others, args.gov_fee,
                              args.gov_fee_rate, args.gov_fee_base,
                              args.tax_rate if args.tax_rate is not None else 0.0,
                              args.provisional)
        elif f == "prepayment_deduct":
            need(contract=args.contract, prepay_rate=args.prepay_rate,
                 material_ratio=args.material_ratio)
            r = prepayment_deduct(args.contract, args.prepay_rate, args.material_ratio,
                                  args.cumulative, args.already_deducted, args.point_ratio)
        elif f == "retention_amount":
            need(settlement=args.settlement)
            r = retention_amount(args.settlement, args.retention_rate)
        elif f == "late_payment_interest":
            need(amount=args.amount, late_days=args.late_days)
            r = late_payment_interest(args.amount, args.late_days, args.lpr, args.agreed_rate)
        elif f == "compose_price":
            if args.rates_file:
                r = compose_price_with_rates(args.labor, args.material, args.machine,
                                             args.rates_file, args.manage_rate,
                                             args.profit_rate, args.risk_amp,
                                             args.tax_rate, args.unit)
            else:
                r = compose_price(args.labor, args.material, args.machine,
                                  args.manage_rate if args.manage_rate is not None else 0.05,
                                  args.profit_rate if args.profit_rate is not None else 0.04,
                                  args.risk_amp if args.risk_amp is not None else 0.0,
                                  args.tax_rate, args.unit)
        elif f == "compose_price_from_rates":
            need(materials=args.materials, rates_file=args.rates_file)
            r = compose_price_from_rates(_parse_kv(args.materials),
                                         args.rates_file, args.labor_days,
                                         _parse_kv(args.machines) if args.machines else None,
                                         args.manage_rate, args.profit_rate, args.risk_amp,
                                         args.tax_rate, not args.allow_missing,
                                         _parse_kv(args.extra_prices) if args.extra_prices else None)
        elif f == "delay_claim":
            need(event_date=args.event_date, claim_date=args.claim_date)
            r = delay_claim(args.event_date, args.claim_date, args.notice_days, args.delay_days,
                            args.daily_loss, args.extra, args.extension_cap, args.event_end_date,
                            args.total_float, args.final_report_days)
        elif f == "delay_extension":
            need(delay_days=args.delay_days, total_float=args.total_float)
            r = delay_extension(args.delay_days, args.total_float)
        elif f == "index_metrics":
            need(total_cost=args.total_cost, area=args.area)
            r = index_metrics(args.total_cost, args.area, args.benchmark,
                              _parse_kv(args.quantities) if args.quantities else None,
                              args.area_caliber)
        elif f == "audit_attribution":
            need(submit_qty=args.submit_qty, audited_qty=args.audited_qty,
                 submit_price=args.submit_price, audited_price=args.audited_price)
            r = audit_attribution(args.submit_qty, args.audited_qty,
                                  args.submit_price, args.audited_price)
        elif f == "material_adjust_weighted":
            need(periods=args.periods, base=args.base, bid=args.bid)
            r = material_adjust_weighted(_parse_periods(args.periods), args.base, args.bid,
                                         args.risk if args.risk is not None else 5.0)
        elif f == "reconcile_check":
            need(parts=args.parts, total=args.total)
            r = reconcile_check([float(x) for x in str(args.parts).strip("[]").split(";") if x.strip()],
                                args.total, args.tolerance, args.tolerance_rate)
        elif f == "sample_plan":
            need(sample_items=args.sample_items)
            r = sample_plan([{"项目": k, "金额": float(v)}
                             for k, v in _parse_kv(args.sample_items).items()],
                            args.threshold_rate, args.coverage_target)
        elif f == "benchmark_index":
            need(total_cost=args.total_cost, area=args.area)
            r = benchmark_index(args.total_cost, args.area,
                                _parse_kv(args.benchmarks) if args.benchmarks else None,
                                args.area_caliber)
        else:
            print(json.dumps({"错误": "未知 func：%s（用 --list 查看可用函数）" % f}, ensure_ascii=False))
            return 1
    except ValueError as e:
        print(json.dumps({"错误": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
