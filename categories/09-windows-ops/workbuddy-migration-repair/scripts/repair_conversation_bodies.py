#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对话正文归位工具（workbuddy-migration-repair）

问题背景
--------
WorkBuddy 把每个会话的聊天正文存在
    ~/.workbuddy/projects/<工作区目录名>/<会话id>.jsonl
其中 <工作区目录名> 由工作区**完整路径**派生，规则是：
    盘符字母转小写 + 路径分隔符换成 '-'，其余字符原样保留
    例：C:\\Users\\AHS\\WorkBuddy\\2026-08-06-11-23-49
        -> c-Users-AHS-WorkBuddy-2026-08-06-11-23-49

换电脑后用户名变了（Administrator -> AHS），但 projects 下的目录名没变，
界面拿 sessions.cwd 反查正文时路径对不上，于是：
    **会话标题看得见，点进去一片空白。**
本脚本就是把目录名改到与本机 sessions.cwd 一致。

典型用法
--------
1) 只做就地改名（projects 已经在本机，只是名字带旧用户名）
       python repair_conversation_bodies.py --dry-run      # 先看要改什么
       python repair_conversation_bodies.py                # 真正执行

2) 从旧电脑拷来的 projects 目录导入，并顺手改名
       python repair_conversation_bodies.py --src "C:/Users/AHS/Desktop/old-projects"

安全保证
--------
* 全程只用 copy / rename，**从不删除任何 jsonl**；
* 目标目录已存在时改为"内容合并"，同名冲突则保留原文件并另存；
* --dry-run 可先预览；
* 执行前自动把 projects 目录做一份整体备份到 ~/.workbuddy/_projects-backup-<时间戳>/。
"""
import argparse
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

HOME = Path.home()
WB = HOME / ".workbuddy"
PROJECTS = WB / "projects"
DB = WB / "workbuddy.db"


def expected_key(win_path: str) -> str:
    """把 Windows 路径转成 WorkBuddy 的 projects 目录名。"""
    p = win_path.strip()
    if len(p) >= 2 and p[1] == ":":
        # 盘符小写，去掉冒号
        p = p[0].lower() + p[2:]
    p = p.replace("\\", "-").replace("/", "-")
    p = re.sub(r"-+", "-", p)
    return p


def current_user() -> str:
    return os.environ.get("USERNAME") or HOME.name


def user_part(key: str):
    """从 c-Users-<名字>-... 里取出 <名字>；取不到返回 None。"""
    m = re.match(r"^[a-z]-(?:Users|用户)-([^-]+)-", key)
    return m.group(1) if m else None


def rename_key(key: str, new_user: str, old_user: str = None):
    """把目录名里的旧用户名换成新用户名；不变则返回 None。"""
    if old_user:
        old = re.compile(r"^([a-z])-(Users|用户)-" + re.escape(old_user) + r"-", re.I)
    else:
        old = re.compile(r"^([a-z])-(Users|用户)-([^-]+)-", re.I)
    if not old.match(key):
        return None
    new = old.sub(lambda m: "%s-Users-%s-" % (m.group(1).lower(), new_user), key, count=1)
    return new if new != key else None


def load_cwds():
    """从数据库读出所有会话的工作区路径。"""
    if not DB.exists():
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % str(DB).replace("\\", "/"), uri=True)
        cur = con.cursor()
        cur.execute("SELECT cwd, COUNT(*) FROM sessions GROUP BY cwd")
        rows = cur.fetchall()
        con.close()
        return rows
    except Exception as e:
        print("  [警告] 读取数据库失败：%s" % e)
        return []


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--src", help="旧电脑拷来的 projects 目录（可选）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不改动")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份（不建议）")
    args = ap.parse_args()

    print("=" * 70)
    print("WorkBuddy 对话正文归位工具")
    print("=" * 70)
    print("  本机用户     : %s" % current_user())
    print("  projects 目录: %s  %s" % (PROJECTS, "[存在]" if PROJECTS.is_dir() else "[不存在]"))
    print("  数据库       : %s  %s" % (DB, "[存在]" if DB.exists() else "[不存在]"))
    print("  模式         : %s" % ("预览（不改动）" if args.dry_run else "执行"))

    PROJECTS.mkdir(parents=True, exist_ok=True)

    # ---------- 1. 从外部目录导入 ----------
    if args.src:
        src = Path(args.src).expanduser()
        print("\n[1] 从外部目录导入: %s" % src)
        if not src.is_dir():
            print("    [错误] 目录不存在，已跳过导入")
        else:
            items = [p for p in src.iterdir() if p.is_dir()]
            n_files = sum(len(fs) for _d, _s, fs in os.walk(src))
            print("    待导入 %d 个目录 / %d 个文件" % (len(items), n_files))
            if not args.dry_run:
                for p in items:
                    dst = PROJECTS / p.name
                    dst.mkdir(parents=True, exist_ok=True)
                    for dp, _dns, fns in os.walk(p):
                        rel = os.path.relpath(dp, p)
                        target = dst if rel == "." else dst / rel
                        target.mkdir(parents=True, exist_ok=True)
                        for fn in fns:
                            s, t = Path(dp) / fn, target / fn
                            if t.exists() and t.stat().st_size == s.stat().st_size:
                                continue
                            if t.exists():
                                t = target / (fn + ".from-old-pc")
                            shutil.copy2(s, t)
                    print("      导入 %s" % p.name)
            else:
                for p in items:
                    print("      (预览) 导入 %s" % p.name)

    # ---------- 2. 备份 ----------
    if not args.dry_run and not args.no_backup and PROJECTS.is_dir():
        n = sum(len(fs) for _d, _s, fs in os.walk(PROJECTS))
        if n:
            bk = WB / ("_projects-backup-%s" % time.strftime("%Y%m%d-%H%M%S"))
            shutil.copytree(PROJECTS, bk, dirs_exist_ok=True)
            print("\n[2] 已备份 projects -> %s（%d 个文件）" % (bk, n))
        else:
            print("\n[2] projects 为空，跳过备份")
    else:
        print("\n[2] 跳过备份")

    # ---------- 3. 目录名对齐 ----------
    print("\n[3] 目录名对齐（旧用户名 -> 本机用户名）")
    dirs = sorted([p for p in PROJECTS.iterdir() if p.is_dir()])
    if not dirs:
        print("    projects 下没有任何目录，无事可做。")
        return 0

    cwds = load_cwds()
    expect = {}
    for cwd, cnt in cwds:
        expect[expected_key(cwd)] = (cwd, cnt)
    print("    数据库里有 %d 个不同工作区路径" % len(expect))
    print("    磁盘上有 %d 个正文目录" % len(dirs))

    changed = 0
    unchanged = 0
    for d in dirs:
        name = d.name
        new = rename_key(name, current_user())
        if not new:
            unchanged += 1
            continue
        target = PROJECTS / new
        print("    改: %s" % name)
        print("     -> %s" % new)
        if target.exists():
            # 合并：以现有目录为主，旧目录内容补进去
            n_copy = 0
            for dp, _dns, fns in os.walk(d):
                rel = os.path.relpath(dp, d)
                tdir = target if rel == "." else target / rel
                tdir.mkdir(parents=True, exist_ok=True)
                for fn in fns:
                    s = Path(dp) / fn
                    t = tdir / fn
                    if t.exists():
                        if t.stat().st_size == s.stat().st_size:
                            continue
                        t = tdir / (fn + ".merged")
                    if not args.dry_run:
                        shutil.copy2(s, t)
                    n_copy += 1
            print("        （目标已存在，合并 %d 个文件）" % n_copy)
            if not args.dry_run:
                shutil.move(str(d), str(PROJECTS / ("oldname-" + name)))
        else:
            if not args.dry_run:
                d.rename(target)
        changed += 1

    print("\n    改名 %d 个，无需改动 %d 个" % (changed, unchanged))

    # ---------- 4. 校验 ----------
    print("\n[4] 校验：数据库工作区 <-> 磁盘正文目录")
    after = {}
    for p in PROJECTS.iterdir():
        if p.is_dir():
            after[p.name] = sum(len(fs) for _dp, _s, fs in os.walk(p))
    hit = miss = 0
    missing_names = []
    for k, (cwd, cnt) in sorted(expect.items()):
        if k in after:
            hit += 1
        else:
            miss += 1
            missing_names.append((cwd, cnt))
    print("    能对上（有正文目录）: %d 个工作区" % hit)
    print("    对不上（缺正文）    : %d 个工作区" % miss)
    if missing_names:
        print("\n    缺正文的工作区（会显示为「标题可见、点进去空白」）:")
        for cwd, cnt in sorted(missing_names, key=lambda x: -x[1])[:15]:
            print("      %4d 个会话  %s" % (cnt, cwd))
        print("\n    补救：到旧电脑上把 %s 整个目录拷过来，" % r"C:\Users\<旧用户名>\.workbuddy\projects")
        print("          然后用 --src 参数再跑一次本脚本即可。")

    n_jsonl = 0
    for p in PROJECTS.rglob("*.jsonl"):
        n_jsonl += 1
    print("\n    本机正文文件（.jsonl）总数: %d" % n_jsonl)
    print("\n完成。%s" % ("（预览模式，未做任何改动）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
