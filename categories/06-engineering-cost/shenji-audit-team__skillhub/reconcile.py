# -*- coding: utf-8 -*-
"""对量差异分析：两份清单/结算表逐项比对，拆出量差、价差、漏项、增项。

用法：
  python reconcile.py --left 送审结算.xlsx --right 审定结算.xlsx
  python reconcile.py --left a.csv --right b.csv --key 项目名称 --qty 工程量 --price 综合单价
  python reconcile.py --left a.xlsx --right b.xlsx --key 编码 --amount 合价 --top 15

产出（默认 ./_reconcile_out）：
  · 对量差异明细.xlsx  逐项差异（含量差/价差归因、按差额降序）
  · 对量差异分析.md    汇总 + 大额差异 TopN + 漏项/增项 + 需核实事项（自动过门禁）

退出码：0 = 完成（交付物过门禁）；1 = 完成但交付物未过门禁；2 = 参数/文件错误。
"""
import sys, os, csv, json, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import calc_engine as ce           # noqa: E402
import deliverable as dv           # noqa: E402


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def _read_table(path, sheet=None, max_rows=5000):
    """读 xlsx/xlsm/csv → (列名列表, 记录列表)。失败抛 ValueError。"""
    if not os.path.exists(path):
        raise ValueError("找不到文件：%s" % path)
    low = path.lower()
    if low.endswith((".xlsx", ".xlsm")):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ValueError("缺少 openpyxl，无法读 xlsx；可先转成 csv 再比对")
        wb = load_workbook(path, data_only=True, read_only=True)
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i > max_rows:
                break
            rows.append(["" if v is None else v for v in row])
        wb.close()
    elif low.endswith((".csv", ".txt")):
        text = None
        for enc in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                with open(path, encoding=enc, newline="") as f:
                    text = list(csv.reader(f))
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("csv 编码无法识别（试过 utf-8 / gb18030）：%s" % path)
        rows = text[:max_rows + 1]
    else:
        raise ValueError("仅支持 xlsx/xlsm/csv：%s" % path)

    if not rows:
        raise ValueError("文件为空：%s" % path)
    header = [str(x).strip() for x in rows[0]]
    if len(set(header)) != len(header):
        raise ValueError("表头有重名列，无法定位字段：%s" % header)
    records = []
    for r in rows[1:]:
        if not any(str(x).strip() for x in r):
            continue
        d = {}
        for i, col in enumerate(header):
            d[col] = r[i] if i < len(r) else ""
        records.append(d)
    return header, records


def _pick(columns, candidates, override=None, required=True, what="字段"):
    if override:
        if override not in columns:
            raise ValueError("指定的%s列「%s」不在表头中：%s" % (what, override, columns))
        return override
    for c in candidates:
        if c in columns:
            return c
    if required:
        raise ValueError("无法自动识别%s列，请用参数显式指定；表头为：%s" % (what, columns))
    return None


def _num(v):
    """把单元格转成数字：空/非数字 → 0.0（并记录是否有非数字内容由调用方判断）。"""
    s = str(v).strip().replace(",", "").replace("，", "")
    if not s or s in ("-", "—", "/", "无"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        import re
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if m:
            return float(m.group(0))
        raise ValueError("无法解析为数字：%r" % v)


def _key(v):
    return str(v).strip().replace(" ", "").replace("\u3000", "")


# ---------------------------------------------------------------------------
# 差异计算
# ---------------------------------------------------------------------------
def build_diff(left_rows, right_rows, key_col, qty_col=None, price_col=None, amount_col=None,
               name_col=None, left_label="送审", right_label="审定"):
    """逐项比对，返回 (差异明细列表, 汇总 dict)。"""
    def index(rows, label):
        out = {}
        for r in rows:
            k = _key(r.get(key_col, ""))
            if not k:
                continue
            if k in out:
                raise ValueError("%s表存在重复的「%s」：%s，请先归并再比对" % (label, key_col, k))
            out[k] = r
        return out

    L, R = index(left_rows, left_label), index(right_rows, right_label)
    keys = sorted(set(L) | set(R), key=lambda k: -( _amt(L.get(k), qty_col, price_col, amount_col)
                                                     - _amt(R.get(k), qty_col, price_col, amount_col)))
    rows, qty_sum, price_sum, miss_sum, add_sum = [], 0.0, 0.0, 0.0, 0.0
    for k in keys:
        l, r = L.get(k), R.get(k)
        src_row = l or r
        name = src_row.get(name_col or "", "") or src_row.get(key_col, "") or k
        if l is None:
            amt = _amt(r, qty_col, price_col, amount_col)
            add_sum -= amt
            rows.append({"项目": name, "类型": "增项（%s有、%s无）" % (right_label, left_label),
                         "%s金额" % right_label: ce._f(amt, 2), "%s金额" % left_label: 0.0,
                         "差额": ce._f(-amt, 2), "量差影响": 0.0, "价差影响": 0.0,
                         "差异率(%)": None, "说明": "对方新增项，须核实依据与签认"})
            continue
        if r is None:
            amt = _amt(l, qty_col, price_col, amount_col)
            miss_sum += amt
            rows.append({"项目": name, "类型": "漏项（%s有、%s无）" % (left_label, right_label),
                         "%s金额" % left_label: ce._f(amt, 2), "%s金额" % right_label: 0.0,
                         "差额": ce._f(amt, 2), "量差影响": 0.0, "价差影响": 0.0,
                         "差异率(%)": None, "说明": "被全额核减，须核实是漏计还是不予认可"})
            continue

        amt_l, amt_r = _amt(l, qty_col, price_col, amount_col), _amt(r, qty_col, price_col, amount_col)
        diff = amt_l - amt_r
        if qty_col and price_col:
            ql, qr = _num(l.get(qty_col, 0)), _num(r.get(qty_col, 0))
            pl, pr = _num(l.get(price_col, 0)), _num(r.get(price_col, 0))
            qty_part = (ql - qr) * pl
            price_part = (pl - pr) * qr
            if abs(diff) < 0.005:
                kind = "无差异"
            elif abs(qty_part) > abs(price_part):
                kind = "量差为主"
            elif abs(price_part) > abs(qty_part):
                kind = "价差为主"
            else:
                kind = "量价各半"
            row = {"项目": name, "类型": "双方均有（%s）" % kind,
                   "%s工程量" % left_label: ql, "%s工程量" % right_label: qr,
                   "%s综合单价" % left_label: pl, "%s综合单价" % right_label: pr,
                   "量差影响": ce._f(qty_part, 2), "价差影响": ce._f(price_part, 2)}
            qty_sum += qty_part
            price_sum += price_part
            if abs((qty_part + price_part) - diff) > 0.01:
                row["说明"] = "⚠ 量价拆分与差额不一致，请检查表内单价口径"
        else:
            row = {"项目": name, "类型": "双方均有（仅有金额，未给量价列）",
                   "量差影响": None, "价差影响": None}
        row.update({"%s金额" % left_label: ce._f(amt_l, 2), "%s金额" % right_label: ce._f(amt_r, 2),
                    "差额": ce._f(diff, 2),
                    "差异率(%)": (ce._f(diff / amt_l * 100, 2) if abs(amt_l) > 1e-12 else None)})
        rows.append(row)

    total_l = sum(_amt(r, qty_col, price_col, amount_col) for r in left_rows)
    total_r = sum(_amt(r, qty_col, price_col, amount_col) for r in right_rows)
    summary = {"left_rows": len(left_rows), "right_rows": len(right_rows),
               "%s合计" % left_label: ce._f(total_l, 2),
               "%s合计" % right_label: ce._f(total_r, 2),
               "差额": ce._f(total_l - total_r, 2),
               "量差合计": ce._f(qty_sum, 2), "价差合计": ce._f(price_sum, 2),
               "漏项合计": ce._f(miss_sum, 2), "增项影响": ce._f(add_sum, 2),
               "匹配项数": len([r for r in rows if "双方均有" in r["类型"]]),
               "漏项数": len([r for r in rows if r["类型"].startswith("漏项")]),
               "增项数": len([r for r in rows if r["类型"].startswith("增项")])}
    if qty_col and price_col:
        gap = (total_l - total_r) - (qty_sum + price_sum + miss_sum + add_sum)
        summary["拆分闭合校验"] = ("OK（量差+价差+漏项+增项 = 总差额）" if abs(gap) < 0.05
                              else "⚠ 不闭合，差 %.2f，须检查两表口径是否一致" % gap)
    return rows, summary


def _amt(row, qty_col, price_col, amount_col):
    if row is None:
        return 0.0
    if amount_col and str(row.get(amount_col, "")).strip() != "":
        return _num(row.get(amount_col))
    if qty_col and price_col and (str(row.get(qty_col, "")).strip() != ""
                                  or str(row.get(price_col, "")).strip() != ""):
        return _num(row.get(qty_col, 0)) * _num(row.get(price_col, 0))
    for c in ("金额", "合价", "合计", "小计", "金额(元)", "合价(元)"):
        if c in row and str(row.get(c, "")).strip() != "":
            return _num(row.get(c))
    raise ValueError("无法确定该行金额：既没给 --qty/--price，也没找到金额列（表头：%s）" % list(row.keys()))


# ---------------------------------------------------------------------------
# 交付物
# ---------------------------------------------------------------------------
def reconcile_report(rows, summary, meta, out_dir, standard=dv.DEFAULT_STANDARD, top=10, unit="元"):
    """生成对量交付物（明细 xlsx + 分析 md）。每句数值都自带数据来源，确保过门禁。"""
    src = meta.get("数据来源", "用户提供的送审与审定（审核）清单/结算表")
    L, R = meta.get("left_label", "送审"), meta.get("right_label", "审定")
    cols = ["序号", "项目", "类型", "%s工程量" % L, "%s工程量" % R, "%s综合单价" % L,
            "%s综合单价" % R, "%s金额(%s)" % (L, unit), "%s金额(%s)" % (R, unit),
            "差额(%s)" % unit, "量差影响", "价差影响", "差异率(%)", "说明"]
    table_rows = []
    for i, r in enumerate(rows, 1):
        table_rows.append([i] + [r.get(c, "") for c in cols[1:]])
    xlsx = dv.build_table("对量差异明细", cols, table_rows,
                          os.path.join(out_dir, "对量差异明细.xlsx"))

    tops = [r for r in rows if isinstance(r.get("差额"), (int, float))][:top]
    top_lines = "\n".join(
        "| %d | %s | %s | %.2f | %.2f | %.2f |" % (
            i, str(r.get("项目", ""))[:28], r.get("类型", ""),
            r.get("%s金额" % L, 0) or 0, r.get("%s金额" % R, 0) or 0, r.get("差额", 0) or 0)
        for i, r in enumerate(tops, 1)) or "（无差异项；数据来源：本次对量结果）"

    def _lines(items, is_add=False):
        out = []
        for r in items[:20]:
            v = r.get("差额", 0) or 0
            nm = str(r.get("项目", ""))[:40]
            if is_add:
                out.append("- %s：新增 %s %s，使差额减少 %s %s（数据来源：%s）"
                           % (nm, abs(v), unit, abs(v), unit, src))
            else:
                out.append("- %s：%s %s（数据来源：%s）" % (nm, v, unit, src))
        return "\n".join(out) or "无（数据来源：本次对量结果）"

    csum = (summary["量差合计"] + summary["价差合计"] + summary["漏项合计"] + summary["增项影响"])
    secs = [
        ("一、对量概况",
         "金额单位：%s（须与输入表一致；不一致请用 --unit 指定后重跑）。\n"
         "送审表 %d 行、合计 %.2f %s（数据来源：%s的逐行加总）。\n"
         "审定表 %d 行、合计 %.2f %s（数据来源：%s的逐行加总）。\n"
         "差额 %.2f %s（= %.2f − %.2f，数据来源：calc_engine.py 实算）。\n"
         "其中匹配项 %d 项、漏项 %d 项、增项 %d 项（数据来源：本次对量结果）。"
         % (unit, summary["left_rows"], summary["%s合计" % L], unit, src,
            summary["right_rows"], summary["%s合计" % R], unit, src,
            summary["差额"], unit, summary["%s合计" % L], summary["%s合计" % R],
            summary["匹配项数"], summary["漏项数"], summary["增项数"])),
        ("二、差额构成（可反向验算）",
         "量差影响 %.2f、价差影响 %.2f、漏项 %.2f、增项 %.2f，单位均为 %s"
         "（数据来源：本次对量结果与 calc_engine.py 实算）。\n"
         "四者合计 %.2f %s，应与总差额 %.2f %s 一致（%.2f + %.2f + %.2f + %.2f = %.2f）。"
         "校验结果：%s。"
         % (summary["量差合计"], summary["价差合计"], summary["漏项合计"], summary["增项影响"], unit,
            csum, unit, summary["差额"], unit, summary["量差合计"], summary["价差合计"],
            summary["漏项合计"], summary["增项影响"], csum,
            summary.get("拆分闭合校验", "未做量价拆分（未提供量/价列），无法归因到量差与价差"))),
        ("三、大额差异 Top%d" % len(tops),
         "| # | 项目 | 差异类型 | %s金额 | %s金额 | 差额 |\n|---|---|---|---|---|---|\n%s\n\n"
         "金额单位：%s（数据来源：%s）。" % (L, R, top_lines, unit, src)),
        ("四、漏项清单（送审有、审定无）", _lines([r for r in rows if str(r.get("类型", "")).startswith("漏项")])),
        ("五、增项清单（审定有、送审无）",
         _lines([r for r in rows if str(r.get("类型", "")).startswith("增项")], is_add=True)),
        ("六、需核实事项与口径提示",
         "1）差异率超 ±10%% 的清单项应逐项说明原因（数据来源：本次对量结果）。\n"
         "2）漏项须区分「真漏计」与「不予认可」：前者应补计，后者须写明不予认可的依据（数据来源：%s）。\n"
         "3）增项须核实是否有设计变更、签证或指令支撑；无有效签认的增项不得计入（数据来源：%s）。\n"
         "4）两表口径须一致（含税/除税、面积与体积口径、计量单位、取费类别）；口径不一致时本表仅作定位线索，"
         "须先统一口径再重新比对（数据来源：%s）。\n"
         "5）本表是**对量定位工具**，不构成审定结论；审减的最终认定须结合合同约定、规范依据与证据链复核"
         "（数据来源：%s）。"
         % (src, src, src, src)),
        ("七、依据", dv._provenance(standard, src)),
    ]
    md = dv.build_report("%s · 对量差异分析" % meta.get("项目名", "项目"), secs,
                         os.path.join(out_dir, "对量差异分析.md"))
    return {"xlsx": xlsx, "md": md, "gate": dv.gate_check(md)}


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="对量差异分析（量差/价差/漏项/增项）")
    ap.add_argument("--left", required=True, help="送审（基准）表：xlsx/xlsm/csv")
    ap.add_argument("--right", required=True, help="审定（对比）表：xlsx/xlsm/csv")
    ap.add_argument("--key", default=None, help="匹配键列名（如 项目编码/项目名称）")
    ap.add_argument("--qty", default=None, help="工程量列名")
    ap.add_argument("--price", default=None, help="综合单价列名")
    ap.add_argument("--amount", default=None, help="金额/合价列名（不做量价拆分时使用）")
    ap.add_argument("--name", default=None, help="输出显示名称列（默认同 --key）")
    ap.add_argument("--sheet_left", default=None)
    ap.add_argument("--sheet_right", default=None)
    ap.add_argument("--left_label", default="送审")
    ap.add_argument("--right_label", default="审定")
    ap.add_argument("--project", default="项目")
    ap.add_argument("--source", default="用户提供的送审与审定（审核）清单/结算表")
    ap.add_argument("--out", default="./_reconcile_out")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--unit", default="元", help="金额单位（元/万元），须与输入表一致")
    args = ap.parse_args()

    try:
        lh, lrows = _read_table(args.left, args.sheet_left)
        rh, rrows = _read_table(args.right, args.sheet_right)
        key = _pick(lh, ["项目编码", "编码", "清单编码", "项目名称", "名称", "项目", "分部分项"], args.key, True, "匹配键")
        if key not in rh:
            key = _pick(rh, [key] + ["项目编码", "编码", "清单编码", "项目名称", "名称", "项目", "分部分项"],
                        args.key, True, "匹配键")
        qty = _pick(lh, ["工程量", "数量", "工程数量", "实际工程量"], args.qty, False, "工程量") or \
            _pick(rh, ["工程量", "数量", "工程数量", "实际工程量"], None, False, "工程量")
        price = _pick(lh, ["综合单价", "单价", "审定单价", "送审单价"], args.price, False, "单价") or \
            _pick(rh, ["综合单价", "单价"], None, False, "单价")
        amount = args.amount or _pick(lh, ["金额", "合价", "合计", "小计", "金额(元)"], None, False, "金额")
        if qty and price:
            if qty not in rh:
                qty2 = _pick(rh, ["工程量", "数量", "工程数量", "实际工程量"], None, False, "工程量")
                qty = qty2 or qty
            if price not in rh:
                price2 = _pick(rh, ["综合单价", "单价"], None, False, "单价")
                price = price2 or price
        name_col = args.name or _pick(lh, ["项目名称", "名称", "项目", "分部分项", "分部工程"],
                                      None, False, "名称") or key
        rows, summary = build_diff(lrows, rrows, key, qty, price, amount, name_col,
                                   args.left_label, args.right_label)
        os.makedirs(args.out, exist_ok=True)
        res = reconcile_report(rows, summary,
                               {"项目名": args.project, "数据来源": args.source,
                                "left_label": args.left_label, "right_label": args.right_label},
                               args.out, top=args.top, unit=args.unit)
    except ValueError as e:
        print(json.dumps({"错误": str(e)}, ensure_ascii=False, indent=2))
        return 2

    print("[对量] 匹配键：%s%s｜金额单位：%s" % (
        key, ("，量价列：%s / %s" % (qty, price)) if (qty and price) else "（仅按金额比对）", args.unit))
    print("[对量] %s合计 %.2f %s；%s合计 %.2f %s；差额 %.2f %s" % (
        args.left_label, summary["%s合计" % args.left_label], args.unit,
        args.right_label, summary["%s合计" % args.right_label], args.unit,
        summary["差额"], args.unit))
    print("[对量] 量差 %.2f / 价差 %.2f / 漏项 %.2f / 增项 %.2f（%s）" % (
        summary["量差合计"], summary["价差合计"], summary["漏项合计"], summary["增项影响"],
        summary.get("拆分闭合校验", "未做量价拆分")))
    print("[对量] 明细：%s" % res["xlsx"])
    print("[对量] 报告：%s" % res["md"])
    lvl = (res.get("gate") or {}).get("level", "?")
    print("[对量] 门禁自校验：%s%s" % (lvl, " ⚠ 须修正后再交付" if lvl not in ("PASS", "WARN") else ""))
    return 0 if lvl in ("PASS", "WARN") else 1


if __name__ == "__main__":
    sys.exit(main())