# -*- coding: utf-8 -*-
"""法规时效巡检：解析 references/regulatory_register.md 与规范数据库的核校日，超期告警。

用法：
  python staleness_check.py [--days 365] [--register references/regulatory_register.md]
退出码：0 = 无超期；1 = 有超期或注册表异常；2 = 内部错误。
"""
import os, re, sys, json, argparse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REGISTER = os.path.join(HERE, "references", "regulatory_register.md")
DEFAULT_DB = os.path.join(HERE, "references", "standards", "规范数据库.json")

ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*$")
CHECK_DATE = re.compile(r"核校日[:：]\s*(\d{4}-\d{2}-\d{2})")


def _setup_io():
    for _name in ("stdin", "stdout", "stderr"):
        try:
            getattr(sys, _name).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_io()


def main():
    ap = argparse.ArgumentParser(description="法规/条款库时效巡检")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--register", default=DEFAULT_REGISTER)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.days < 0:
        sys.stderr.write("--days 不得为负\n")
        return 2
    if not os.path.isfile(args.register):
        sys.stderr.write("ERROR: 找不到注册表 %s\n" % args.register)
        return 1

    text = open(args.register, encoding="utf-8").read()
    m = CHECK_DATE.search(text)
    report_date = m.group(1) if m else None

    rows = []
    for line in text.splitlines():
        mm = ROW.match(line)
        if mm:
            name, code, clause, status, date = mm.groups()
            rows.append((name.strip(), date.strip(), status.strip()))

    today = datetime.date.today()
    overdue = []
    for name, date_s, status in rows:
        try:
            d = datetime.date.fromisoformat(date_s)
        except ValueError:
            continue
        age = (today - d).days
        if age > args.days:
            overdue.append({"条目": name, "核校日": date_s, "已过天数": age, "状态": status})

    # 规范数据库整体核校日
    db_info = {}
    if os.path.isfile(args.db):
        try:
            data = json.load(open(args.db, encoding="utf-8"))
            meta = data.get("_metadata", {}) if isinstance(data, dict) else {}
            lu = meta.get("last_updated") or meta.get("until_date")
            if lu:
                age = (today - datetime.date.fromisoformat(lu)).days
                db_info = {"规范数据库核校日": lu, "已过天数": age,
                           "是否超期": age > args.days}
                if db_info["是否超期"]:
                    overdue.append({"条目": "规范数据库.json", "核校日": lu,
                                    "已过天数": age, "状态": "超期"})
        except Exception as e:
            db_info = {"规范数据库解析失败": str(e)}

    result = {"注册表条目数": len(rows), "阈值(天)": args.days,
              "报告核校日": report_date, "超期条目数": len(overdue),
              "超期明细": overdue, "规范数据库": db_info}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("法规注册表条目: %d  超期(>%d天): %d" % (len(rows), args.days, len(overdue)))
        if report_date:
            print("报告核校日: %s" % report_date)
        if db_info:
            print("规范数据库核校日: %s（已 %s 天）" % (db_info.get("规范数据库核校日", "?"),
                                                 db_info.get("已过天数", "?")))
        for o in overdue:
            print("  [超期] %s  核校日 %s  已 %d 天" % (o["条目"], o["核校日"], o["已过天数"]))
        print("结论：%s" % ("存在超期条目，引用前须重新核验 ⚠" if overdue else "全部在有效期内 ✅"))
    return 1 if overdue else 0


if __name__ == "__main__":
    sys.exit(main())
