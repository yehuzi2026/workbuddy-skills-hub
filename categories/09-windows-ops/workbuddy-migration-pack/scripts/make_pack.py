#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 迁移包一键生成器 v3.0（全量版）
=========================================================
把 AI 助手的全部"成长"打包到桌面，供复制到新电脑一键恢复。
v3.0 新增：完整对话正文（projects JSONL）+ 产物与工件（blobs/file-history 等）。

用法:
  python make_pack.py                      # 全量（对话+产物+工作区，约 5 分钟，~600MB）
  python make_pack.py --skip-workspace     # 不打项目工作区
  python make_pack.py --skip-artifacts     # 不打产物与工件
  python make_pack.py --skip-conversations # 不打对话正文
  python make_pack.py --date 2026-09-15    # 指定日期（默认今天）
  python make_pack.py --out "D:\\备份"      # 指定输出目录（默认桌面）

产出:
  <out>/WorkBuddy迁移包-<日期>/
    ⭐先看这里-换电脑恢复指引.md
    restore-new-pc.sh / 双击我-一键恢复.bat
    01-身份与记忆/        SOUL/IDENTITY/USER/MEMORY 档案/memory 缓存
    02-技能库/skills/
    03-配置与连接/        connectors/credentials/automation-backups/local_storage/mcp*.json
    04-自动化任务/workbuddy.db（一致性备份）
    05-对话记录/          conversations-<日期>.zip + sessions 元数据
    06-产物与工件/        artifacts-<日期>.zip（blobs/file-history/artifact-index/changes-detail/剪贴板等）
    07-项目工作区-可选/    workbuddy-workspace-<日期>.zip + 目录清单
"""
import argparse
import datetime
import os
import shutil
import sqlite3
import stat
import sys
import zipfile
from pathlib import Path

HOME = Path.home()
H = HOME / ".workbuddy"
WORKSPACE = HOME / "WorkBuddy"
PKG_PREFIX = "WorkBuddy迁移包-"

# 产物与工件目录（相对 ~/.workbuddy，解压时原样还原）
ARTIFACT_DIRS = [
    "blobs", "file-history", "artifact-index", "changes-detail",
    "changes-index", "clipboard-images", "appearance-resources",
]

README_TPL = r"""# ⭐ 换电脑 · WorkBuddy 完整迁移指引（{{DATE}} 全量版）

> 这个文件夹 = **你的 AI 助手的全部"灵魂、技能、记忆、对话与产物"**（{{DATE}} 快照）。
> 把它整个拷到新电脑，双击一个 bat，我就"活"过去了——连我们聊过的每一句话都在。

---

## 📦 包里有什么

| 目录 | 内容 | 是否必拷 |
|---|---|---|
| `01-身份与记忆/` | SOUL / IDENTITY / USER + 记忆档案 + memory 缓存 | ✅ 必须 |
| `02-技能库/` | **{{SKILL_COUNT}} 个技能**（全部成长技能） | ✅ 必须 |
| `03-配置与连接/` | mcp.json、连接器、凭据、本地登录态 | ✅ 必须 |
| `04-自动化任务/` | workbuddy.db（**{{AUTO_COUNT}} 个定时自动化**） | ✅ 必须 |
| `05-对话记录/` | **完整对话正文** conversations zip（全部工作区的会话 JSONL）+ 会话元数据 | ✅ 必须 |
| `06-产物与工件/` | **所有产物**：生成的文件/图片/工件（blobs）、文件修改历史、工件索引、剪贴板图片 | ✅ 必须 |
| `07-项目工作区-可选/` | 全部历史项目文件（WorkBuddy 工作区） | ✅ 建议 |
| `restore-new-pc.sh` / `双击我-一键恢复.bat` | 一键恢复 | ✅ 用这个 |

---

## 🚀 新电脑恢复步骤（共 5 步）

### 第 1 步：装 WorkBuddy 并登录【原账号】
用**和现在同一个账号**登录，随便打开一次（生成 ~/.workbuddy 目录，云端记忆才能同步）。

### 第 2 步：把这个文件夹整个拷过去
U 盘 / 移动硬盘 / 网盘都行。整个文件夹原样拷贝（约 {{TOTAL_MB}} MB）。

### 第 3 步：完全退出 WorkBuddy
任务栏图标右键退出。

### 第 4 步：执行一键恢复（二选一）
**方式 A ✅ 推荐：双击 `双击我-一键恢复.bat`**（自动找 WorkBuddy 自带 Git Bash，不用装任何东西）
**方式 B：Git Bash 里运行** `bash restore-new-pc.sh`

脚本自动完成：备份旧数据 → 身份/记忆 → 技能 → 配置连接 → 自动化库 → **解压对话正文** → **解压产物** → 解压项目工作区。

> 💡 Git Bash 不用单独安装——WorkBuddy 自带（`C:\Users\你的用户名\.workbuddy\binaries\PortableGit\`）。

### 第 5 步：重开 WorkBuddy 确认
1. ✅ 我认识你  2. ✅ 技能可用  3. 🔧 连接器页重新「信任」GitHub/CloudBase/邮箱  4. 🔧 检查自动化任务

---

## ⚠️ 安全提醒
- 包内含登录凭据、令牌与**全部聊天记录**，只走你自己可控的通道（U盘/私人网盘/加密压缩）。
- 恢复完成后删除多余副本。

## 📌 以后刷新
直接说："重新生成迁移包"（全量版约 5 分钟）。
"""

RESTORE_TPL = r"""#!/bin/bash
# ============================================================
# WorkBuddy 一键恢复脚本（新电脑专用）v3.0 · {{DATE}}
# 用法：Git Bash 中进入本文件夹运行  bash restore-new-pc.sh
# 前提：新电脑已安装 WorkBuddy，用【同一账号】登录并打开过一次
# ============================================================

set -e
export PATH="/usr/bin:/bin:$PATH"

PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
H="$HOME/.workbuddy"
TS="$(date +%Y%m%d%H%M%S)"

echo "=============================================="
echo "  WorkBuddy 恢复（迁移包 {{DATE}} 全量版）"
echo "  目标: ${H}"
echo "=============================================="

if [ ! -d "$H" ]; then
    echo "[错误] 未找到 ~/.workbuddy/ —— 请先安装 WorkBuddy，登录【原账号】打开一次。"
    exit 1
fi
echo "[提示] 请先完全退出 WorkBuddy 程序；确认后按 Enter 继续，Ctrl+C 取消..."
read -r _

BK="$H/_pre-restore-backup-$TS"
if [ -f "$H/MEMORY.md" ] || [ -d "$H/skills" ]; then
    mkdir -p "$BK"
    cp -r "$H"/SOUL.md "$H"/IDENTITY.md "$H"/USER.md "$H"/MEMORY.md "$BK/" 2>/dev/null || true
    [ -d "$H/skills" ] && cp -r "$H/skills" "$BK/"
    echo "[信息] 新电脑原有数据已备份到 $BK"
fi

UNZIP_OK=0
command -v unzip >/dev/null 2>&1 && UNZIP_OK=1

echo ""
echo "[1/7] 恢复身份与记忆..."
for f in SOUL.md IDENTITY.md USER.md MEMORY.md; do
    [ -f "$PKG_DIR/01-身份与记忆/$f" ] && cp "$PKG_DIR/01-身份与记忆/$f" "$H/$f" && echo "  -> $f"
done
if [ ! -f "$PKG_DIR/01-身份与记忆/MEMORY.md" ]; then
    LATEST=$(ls "$PKG_DIR/01-身份与记忆/"MEMORY-最新完整档案-*.md 2>/dev/null | head -1)
    [ -n "$LATEST" ] && cp "$LATEST" "$H/MEMORY.md" && echo "  -> MEMORY.md（最新完整档案）"
fi
mkdir -p "$H/memory"
cp -r "$PKG_DIR/01-身份与记忆/memory-缓存/"* "$H/memory/" 2>/dev/null || true

echo ""
echo "[2/7] 恢复技能库（不覆盖本机较新版本）..."
if [ -d "$PKG_DIR/02-技能库/skills" ]; then
    mkdir -p "$H/skills"
    cp -rn "$PKG_DIR/02-技能库/skills/"* "$H/skills/" 2>/dev/null || true
    rm -rf "$H/skills"/*/__pycache__ "$H/skills"/*/*/__pycache__ 2>/dev/null || true
    echo "  -> $(ls -d "$H/skills/"*/ 2>/dev/null | wc -l) 个技能（已存在项保留本机版本，不覆盖）"
fi

echo ""
echo "[3/7] 恢复配置与连接..."
C="$PKG_DIR/03-配置与连接"
for d in connectors credentials automation-backups local_storage; do
    [ -d "$C/$d" ] && cp -rf "$C/$d" "$H/"
done
for f in mcp.json mcp-approvals.json models.json; do
    [ -f "$C/$f" ] && cp "$C/$f" "$H/$f"
done
echo "  -> 已恢复（MCP/连接器稍后需在『连接器管理』重新点信任）"

echo ""
echo "[4/7] 恢复自动化任务库（合并式，不整库覆盖）..."
PKGDB="$PKG_DIR/04-自动化任务/workbuddy.db"
CURDB="$H/workbuddy.db"
if [ -f "$PKGDB" ]; then
    if [ ! -f "$CURDB" ]; then
        cp "$PKGDB" "$CURDB"
        echo "  -> 本机无既有库，直接恢复（{{AUTO_COUNT}} 个自动化任务）"
    else
        cp "$CURDB" "$BK/workbuddy.db.before-merge" 2>/dev/null || true
        PY=""
        for c in "$H"/binaries/python/versions/*/python.exe; do [ -x "$c" ] && PY="$c"; done
        if [ -n "$PY" ] && [ -f "$PKG_DIR/04-自动化任务/merge_db.py" ]; then
            "$PY" "$PKG_DIR/04-自动化任务/merge_db.py" "$PKGDB" "$CURDB" \
              && echo "  -> 合并完成（本机既有数据已备份到 $BK/workbuddy.db.before-merge）"
        else
            echo "  [警告] 本机已有数据库，为避免覆盖已跳过导入。"
            echo "         既有库已备份: $BK/workbuddy.db.before-merge"
            echo "         如需合并请手动处理: $PKGDB"
        fi
    fi
fi

echo ""
echo "[5/7] 恢复完整对话记录..."
[ -d "$PKG_DIR/05-对话记录/sessions" ] && cp -rn "$PKG_DIR/05-对话记录/sessions" "$H/" 2>/dev/null || true
CZ="$PKG_DIR/05-对话记录/{{CONV_ZIP}}"
if [ -f "$CZ" ]; then
    if [ "$UNZIP_OK" = "1" ]; then
        unzip -qo "$CZ" -d "$H/"
        # ★ 关键：projects 目录名由 cwd 派生（c-Users-<用户名>-WorkBuddy-<工作区>），
        #   旧机器的用户名必须改成当前机器的，否则对话正文与 cwd 对不上号、点开是空的。
        NEWU="$(basename "$HOME")"
        if [ -d "$H/projects" ]; then
            for d in "$H/projects"/*-Users-*/; do
                [ -d "$d" ] || continue
                b="$(basename "$d")"
                nb="$(printf '%s' "$b" | sed -E "s/^c-Users-[^-]+-/c-Users-$NEWU-/")"
                [ "$nb" = "$b" ] && continue
                if [ ! -d "$H/projects/$nb" ]; then
                    mv "$d" "$H/projects/$nb" && echo "    改名归位: $b -> $nb"
                else
                    cp -rn "$d/." "$H/projects/$nb/" 2>/dev/null || true
                    mv -f "$d" "$H/projects/oldname-$b" && echo "    合并归位: $b -> $nb（原件存为 oldname-$b）"
                fi
            done
        fi
        echo "  -> 对话正文已解压到 $H/projects（目录名已按当前用户名 $NEWU 归位）"
    else
        echo "  [手动] 无 unzip 命令：请把 {{CONV_ZIP}} 解压到 $H （解压出 projects 文件夹），"
        echo "         再把 projects/ 下 *-Users-旧用户名-* 目录改名为 *-Users-$NEWU-*"
    fi
fi

echo ""
echo "[6/7] 恢复产物与工件..."
AZ="$PKG_DIR/06-产物与工件/{{ART_ZIP}}"
if [ -f "$AZ" ]; then
    if [ "$UNZIP_OK" = "1" ]; then
        unzip -qo "$AZ" -d "$H/"
        echo "  -> blobs / file-history / artifact-index / changes-detail / 剪贴板图片 已还原"
    else
        echo "  [手动] 请把 {{ART_ZIP}} 解压到 $H （解压出 blobs 等文件夹）"
    fi
fi

echo ""
echo "[7/7] 恢复项目工作区..."
WZ="$PKG_DIR/07-项目工作区-可选/{{WS_ZIP}}"
if [ -f "$WZ" ]; then
    mkdir -p "$HOME/WorkBuddy"
    if [ "$UNZIP_OK" = "1" ]; then
        unzip -qo "$WZ" -d "$HOME/"
        echo "  -> 项目工作区已解压到 $HOME/WorkBuddy"
    else
        echo "  [手动] 请把 {{WS_ZIP}} 解压到 C:\Users\你的用户名\ （解压出 WorkBuddy 文件夹）"
    fi
fi

echo ""
echo "=============================================="
echo "  恢复完成！"
echo "  1. 重开 WorkBuddy（同一账号）"
echo "  2. 连接器管理页重新点『信任』"
echo "  3. 自动化任务/技能/对话/产物全部就位"
echo "=============================================="
"""

LAUNCHER_TPL = r"""@echo off
chcp 936 >nul
title WorkBuddy 换电脑一键恢复（迁移包 {{DATE}} 全量版）
cd /d "%~dp0"

echo ============================================================
echo    WorkBuddy 换电脑恢复 - 迁移包 {{DATE}}（对话+产物+工作区）
echo ============================================================
echo.
echo  [前提] 新电脑已安装 WorkBuddy，用原账号登录并打开过一次
echo  [前提] 现在请先完全退出 WorkBuddy 程序
echo.
echo  按任意键开始恢复（耗时几分钟，请耐心等待）...
pause >nul

set "BASH="
if exist "%USERPROFILE%\.workbuddy\binaries\PortableGit\versions\current\bin\bash.exe" set "BASH=%USERPROFILE%\.workbuddy\binaries\PortableGit\versions\current\bin\bash.exe"
if not defined BASH if exist "%USERPROFILE%\.workbuddy\binaries\PortableGit\bin\bash.exe" set "BASH=%USERPROFILE%\.workbuddy\binaries\PortableGit\bin\bash.exe"
if not defined BASH for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\PortableGit\versions\*") do if exist "%%~fD\bin\bash.exe" set "BASH=%%~fD\bin\bash.exe"
if not defined BASH if exist "C:\Program Files\Git\bin\bash.exe" set "BASH=C:\Program Files\Git\bin\bash.exe"
if not defined BASH if exist "C:\Program Files (x86)\Git\bin\bash.exe" set "BASH=C:\Program Files (x86)\Git\bin\bash.exe"

if not defined BASH (
  echo.
  echo  [未找到 Git Bash] 请确认 WorkBuddy 已安装并至少打开过一次。
  pause
  exit /b 1
)

echo.
echo  使用 Git Bash: %BASH%
echo.
set LC_ALL=C.UTF-8
"%BASH%" restore-new-pc.sh

echo.
echo  执行结束。按任意键关闭窗口。
pause >nul
"""

# 随包附带的「只补不清」数据库合并脚本（恢复端调用它，避免整库覆盖）
MERGE_DB_TPL = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy 迁移包 · 数据库「只补不清」合并工具

用法: python merge_db.py <包内 workbuddy.db> <本机 workbuddy.db>

原则:
  * 以本机库为基底，按主键**只插入**包内独有的行，绝不 UPDATE / DELETE 本机数据；
  * 清掉包内带来的「老机器用户名」workspaces（与现有记录重复的删除，可改写的改写）；
  * 为「有对话正文但没有空间索引」的 cwd 补建 workspace，否则那些对话在界面上看不到；
  * 盘符统一大写（SQLite 精确匹配区分大小写，大小写不一致会导致空间里对话全空）。
"""
import os
import sqlite3
import sys

BS = chr(92)
OLD_USER = "Administrator"
OLD_FRAG = BS + "Users" + BS + OLD_USER + BS
NEW_FRAG = BS + "Users" + BS + (os.environ.get("USERNAME") or "") + BS


def tables(con):
    return [r[0] for r in con.execute("select name from sqlite_master where type='table'")]


def cols(con, t):
    return [r[1] for r in con.execute('pragma table_info("%s")' % t)]


def pkcols(con, t):
    return [r[1] for r in con.execute('pragma table_info("%s")' % t) if r[5] > 0]


def proj_key(cwd):
    s = cwd.replace(":", "").replace(BS, "-").replace("/", "-")
    return (s[0].lower() + s[1:]) if s and s[0].isalpha() else s


def main():
    if len(sys.argv) < 3:
        print("用法: merge_db.py <src.db> <dst.db>")
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    pk = sqlite3.connect(src)
    pk.row_factory = sqlite3.Row
    cu = sqlite3.connect(dst, timeout=30)
    cu.execute("pragma busy_timeout=30000")

    ins_total = 0
    for t in tables(pk):
        if t.startswith("__") or t not in tables(cu):
            continue
        pkc = pkcols(pk, t)
        if not pkc:
            continue
        common = [c for c in cols(pk, t) if c in cols(cu, t)]
        where = " and ".join('"%s"=?' % c for c in pkc)
        names = ",".join('"%s"' % c for c in common)
        ph = ",".join("?" * len(common))
        for r in pk.execute('select * from "%s"' % t):
            k = tuple(r[c] for c in pkc)
            if cu.execute('select 1 from "%s" where %s' % (t, where), k).fetchone():
                continue
            cu.execute('insert into "%s"(%s) values(%s)' % (t, names, ph),
                       [r[c] for c in common])
            ins_total += 1
    cu.commit()

    # 1) 清掉包内带来的老用户名 workspaces
    freed = 0
    if OLD_FRAG:
        old = [r[0] for r in cu.execute(
            "select path from workspaces where path like ?", ("%" + OLD_FRAG + "%",))]
        for p in old:
            np_ = p.replace(OLD_FRAG, NEW_FRAG)
            if cu.execute("select 1 from workspaces where path=?", (np_,)).fetchone():
                cu.execute("delete from workspaces where path=?", (p,))
            elif os.path.isdir(np_):
                cu.execute("update workspaces set path=? where path=?", (np_, p))
            else:
                cu.execute("delete from workspaces where path=?", (p,))
            freed += 1
        cu.commit()

    # 2) 有正文但缺空间索引的 cwd → 补 workspace（否则对话点不开）
    added = 0
    proj = os.path.join(os.path.expanduser("~"), ".workbuddy", "projects")
    if os.path.isdir(proj):
        present = set(os.listdir(proj))
        for r in cu.execute("select cwd, count(*) c from sessions "
                            "where cwd is not null and cwd<>'' group by cwd"):
            cwd = r[0]
            if cu.execute("select 1 from workspaces where path=?", (cwd,)).fetchone():
                continue
            if proj_key(cwd) not in present:
                continue
            if not os.path.isdir(cwd):
                try:
                    os.makedirs(cwd, exist_ok=True)
                except Exception:
                    pass
            mt = 0
            try:
                mt = int(os.stat(cwd).st_mtime * 1000)
            except Exception:
                pass
            cu.execute("insert or ignore into workspaces(path,last_opened_at) values(?,?)",
                       (cwd, mt))
            added += 1
        cu.commit()

    # 3) 盘符统一大写
    cu.execute("update workspaces set path=upper(substr(path,1,1))||substr(path,2) "
               "where substr(path,1,1) between 'a' and 'z'")
    cu.execute("update sessions set cwd=upper(substr(cwd,1,1))||substr(cwd,2) "
               "where substr(cwd,1,1) between 'a' and 'z'")
    cu.commit()

    print("  补入行数: %d" % ins_total)
    print("  清理老路径空间: %d 个, 补建空间: %d 个" % (freed, added))
    for t in ("workspaces", "sessions", "automations"):
        try:
            print("  %-12s %d" % (t, cu.execute('select count(*) from "%s"' % t).fetchone()[0]))
        except Exception:
            pass
    print("  quick_check: %s" % cu.execute("pragma quick_check").fetchone()[0])
    cu.execute("pragma wal_checkpoint(TRUNCATE)")
    cu.close()
    pk.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def log(msg):
    print(msg, flush=True)


def dsize(p: Path):
    t, n = 0, 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                t += f.stat().st_size
                n += 1
        except Exception:
            pass
    return t / 1048576, n


def copy_tree(src: Path, dst: Path):
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    elif src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def clear_readonly(root: Path) -> int:
    """递归清除只读属性（.git 对象文件默认只读，会阻断覆盖/重命名）"""
    cnt = 0
    for r, dirs, files in os.walk(root):
        for name in dirs + files:
            p = os.path.join(r, name)
            try:
                os.chmod(p, stat.S_IWRITE)
                cnt += 1
            except Exception:
                pass
    return cnt


def backup_db(src: Path, dst: Path) -> int:
    con = sqlite3.connect(str(src))
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        b = sqlite3.connect(str(dst))
        con.backup(b)
        b.close()
        try:
            return con.execute("SELECT COUNT(*) FROM automations").fetchone()[0]
        except Exception:
            return 0
    finally:
        con.close()


def make_zip_from_dirs(sources, base: Path, dst_zip: Path, prefix: str = ""):
    """把多个目录打进一个 zip。arcname = 相对 base 的路径（可加 prefix）"""
    entries = []
    for s in sources:
        s = Path(s)
        if not s.exists():
            continue
        if s.is_file():
            entries.append((s, s.name))
        else:
            for f in s.rglob("*"):
                if f.is_file():
                    entries.append((f, str(f.relative_to(base))))
    total = len(entries)
    with zipfile.ZipFile(dst_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, (f, arc) in enumerate(entries, 1):
            z.write(f, arcname=(prefix + arc) if prefix else arc)
            if i % 500 == 0 or i == total:
                log(f"    压缩进度 {i}/{total}")
    return total


def workspace_manifest(ws: Path, out_txt: Path):
    rows = []
    for d in sorted(ws.iterdir()):
        if not d.is_dir():
            continue
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        rows.append((size, d.name))
    rows.sort(reverse=True)
    out_txt.write_text("\n".join(f"{s/1048576:8.1f} MB  {n}/" for s, n in rows) + "\n", encoding="utf-8")
    log(f"    工作区目录清单: {len(rows)} 个项目")


def main():
    ap = argparse.ArgumentParser(description="生成 WorkBuddy 换电脑迁移包（全量版）")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--skip-workspace", action="store_true")
    ap.add_argument("--skip-artifacts", action="store_true")
    ap.add_argument("--skip-conversations", action="store_true")
    ap.add_argument("--out", default=str(HOME / "Desktop"))
    ap.add_argument("--clean-old-packs", action="store_true")
    args = ap.parse_args()

    date = args.date
    out_root = Path(args.out)
    pkg_name = f"{PKG_PREFIX}{date}"
    pkg = out_root / pkg_name
    stamp = datetime.datetime.now().strftime("%H%M%S")

    if not H.is_dir():
        log(f"[错误] 未找到 {H}")
        return 1

    skill_count = len([d for d in (H / "skills").iterdir() if d.is_dir()]) if (H / "skills").is_dir() else 0
    log(f"== 生成 {pkg_name}（全量版）==")
    log(f"   技能目录: {skill_count}")

    stale = [d for d in out_root.glob(f"{PKG_PREFIX}*")
             if d.is_dir() and d.name != pkg_name
             and ".building-" not in d.name and ".old-" not in d.name]
    for old in stale:
        if args.clean_old_packs:
            try:
                shutil.rmtree(old)
                log(f"   已清理旧包: {old.name}")
            except Exception:
                log(f"   [提示] 旧包 {old.name} 未能自动删除，请手动删除")
        else:
            log(f"   [提示] 输出目录还有其他包: {old.name}")

    build = out_root / f"{pkg_name}.building-{stamp}"
    if build.exists():
        shutil.rmtree(build, ignore_errors=True)
    for sub in ["01-身份与记忆/memory-缓存", "02-技能库", "03-配置与连接",
                "04-自动化任务", "05-对话记录", "06-产物与工件", "07-项目工作区-可选"]:
        (build / sub).mkdir(parents=True, exist_ok=True)
    pkg = build

    # ---- 1. 身份与记忆 ----
    log("[1/7] 身份与记忆")
    for f in ["SOUL.md", "IDENTITY.md", "USER.md"]:
        if (H / f).is_file():
            shutil.copy2(H / f, pkg / "01-身份与记忆" / f)
    if (H / "MEMORY.md").is_file():
        shutil.copy2(H / "MEMORY.md", pkg / "01-身份与记忆" / "MEMORY-本地版.md")
    mem_files = sorted((H / "memory").glob("*_memory.md")) if (H / "memory").is_dir() else []
    mem_stamp = "latest"
    if mem_files:
        latest_mem = mem_files[0]
        try:
            for line in latest_mem.read_text(encoding="utf-8", errors="ignore").splitlines()[:8]:
                if "Last updated" in line:
                    mem_stamp = line.split("Last updated:")[1].strip()[:10]
                    break
        except Exception:
            pass
        shutil.copy2(latest_mem, pkg / "01-身份与记忆" / f"MEMORY-最新完整档案-{mem_stamp}.md")
        for m in mem_files:
            shutil.copy2(m, pkg / "01-身份与记忆" / "memory-缓存" / m.name)
        log(f"   记忆档案: {latest_mem.name}（stamp={mem_stamp}）")

    # ---- 2. 技能库 ----
    log("[2/7] 技能库")
    copy_tree(H / "skills", pkg / "02-技能库" / "skills")

    # ---- 3. 配置与连接 ----
    log("[3/7] 配置与连接")
    for d in ["connectors", "credentials", "automation-backups", "local_storage"]:
        if (H / d).is_dir():
            copy_tree(H / d, pkg / "03-配置与连接" / d)
    for f in ["mcp.json", "mcp-approvals.json", "models.json"]:
        if (H / f).is_file():
            shutil.copy2(H / f, pkg / "03-配置与连接" / f)

    # ---- 4. 自动化任务库 ----
    log("[4/7] 自动化任务库")
    auto_count = 0
    if (H / "workbuddy.db").is_file():
        auto_count = backup_db(H / "workbuddy.db", pkg / "04-自动化任务" / "workbuddy.db")
        log(f"   自动化任务数: {auto_count}")

    # ---- 5. 对话记录（正文 projects/ + 元数据 sessions/）----
    conv_zip_name = f"conversations-{date}.zip"
    log("[5/7] 对话记录（完整正文）")
    if (H / "sessions").is_dir():
        copy_tree(H / "sessions", pkg / "05-对话记录" / "sessions")
    if (H / "projects").is_dir() and not args.skip_conversations:
        mb, n = dsize(H / "projects")
        log(f"   源: {mb:.1f} MB / {n} 文件，开始压缩…")
        cnt = make_zip_from_dirs([H / "projects"], H, pkg / "05-对话记录" / conv_zip_name)
        log(f"   已打包 {cnt} 个文件 -> {conv_zip_name}")
    elif args.skip_conversations:
        log("   已跳过（--skip-conversations）")

    # ---- 6. 产物与工件 ----
    art_zip_name = f"artifacts-{date}.zip"
    log("[6/7] 产物与工件")
    if not args.skip_artifacts:
        srcs = [H / d for d in ARTIFACT_DIRS if (H / d).exists()]
        mb = sum(dsize(s)[0] for s in srcs)
        log(f"   源: {mb:.1f} MB，开始压缩…")
        cnt = make_zip_from_dirs(srcs, H, pkg / "06-产物与工件" / art_zip_name)
        log(f"   已打包 {cnt} 个文件 -> {art_zip_name}")
    else:
        log("   已跳过（--skip-artifacts）")

    # ---- 7. 项目工作区 ----
    ws_zip_name = f"workbuddy-workspace-{date}.zip"
    log("[7/7] 项目工作区")
    if WORKSPACE.is_dir():
        workspace_manifest(WORKSPACE, pkg / "07-项目工作区-可选" / "工作区目录清单.txt")
        if args.skip_workspace:
            log("   已跳过（--skip-workspace）")
        else:
            cnt = make_zip_from_dirs([WORKSPACE], HOME, pkg / "07-项目工作区-可选" / ws_zip_name)
            log(f"   已打包 {cnt} 个文件 -> {ws_zip_name}")

    # ---- 文档与脚本 ----
    repl = {
        "{{DATE}}": date,
        "{{PKG_NAME}}": pkg_name,
        "{{SKILL_COUNT}}": str(skill_count),
        "{{AUTO_COUNT}}": str(auto_count),
        "{{CONV_ZIP}}": conv_zip_name,
        "{{ART_ZIP}}": art_zip_name,
        "{{WS_ZIP}}": ws_zip_name,
        "{{TOTAL_MB}}": "约600",
    }

    def render(tpl: str) -> str:
        for k, v in repl.items():
            tpl = tpl.replace(k, v)
        return tpl

    (pkg / "⭐先看这里-换电脑恢复指引.md").write_text(render(README_TPL), encoding="utf-8")
    sh = pkg / "restore-new-pc.sh"
    sh.write_text(render(RESTORE_TPL), encoding="utf-8", newline="\n")
    try:
        os.chmod(sh, 0o755)
    except Exception:
        pass
    (pkg / "双击我-一键恢复.bat").write_bytes(render(LAUNCHER_TPL).encode("gbk", errors="replace"))
    # 随包附带数据库「只补不清」合并脚本（恢复端有既有库时调用）
    (pkg / "04-自动化任务" / "merge_db.py").write_text(MERGE_DB_TPL, encoding="utf-8")
    log("   已写入 04-自动化任务/merge_db.py（恢复端合并数据库用）")

    # ---- 自校验 ----
    log("== 自校验 ==")
    must = ["01-身份与记忆/SOUL.md", "02-技能库/skills", "04-自动化任务/workbuddy.db",
            "⭐先看这里-换电脑恢复指引.md", "restore-new-pc.sh", "双击我-一键恢复.bat"]
    ok = True
    for m in must:
        exist = (pkg / m).exists()
        log(("  ✅ " if exist else "  ❌ 缺失 ") + m)
        ok = ok and exist
    pkg_skills = len([d for d in (pkg / "02-技能库" / "skills").iterdir() if d.is_dir()])
    log(f"  {'✅' if pkg_skills == skill_count else '❌'} 技能数量: 包内 {pkg_skills} vs 源 {skill_count}")
    ok = ok and pkg_skills == skill_count
    for zp, label in [(pkg / "05-对话记录" / conv_zip_name, "对话"),
                      (pkg / "06-产物与工件" / art_zip_name, "产物"),
                      (pkg / "07-项目工作区-可选" / ws_zip_name, "工作区")]:
        if zp.is_file():
            with zipfile.ZipFile(zp) as z:
                bad = z.testzip()
                log(f"  {'✅' if bad is None else '❌'} {label} zip: {len(z.namelist())} 条目, 损坏={bad}, {zp.stat().st_size/1048576:.1f} MB")
                ok = ok and bad is None
        else:
            log(f"  ⏭️ {label} zip 未包含")

    total = sum(f.stat().st_size for f in pkg.rglob("*") if f.is_file())
    log(f"== 构建完成 {'✅' if ok else '❌'} ==  包体积: {total/1048576:.1f} MB")

    # ---- 落地替换 ----
    final = out_root / pkg_name
    if final.exists():
        old_dir = out_root / f"{pkg_name}.old-{stamp}"
        renamed = False
        try:
            final.rename(old_dir)
            renamed = True
        except Exception:
            n = clear_readonly(final)
            log(f"   已清除旧包只读属性 {n} 项，重试替换…")
            try:
                final.rename(old_dir)
                renamed = True
            except Exception:
                pass
        if renamed:
            log(f"   旧包已重命名为: {old_dir.name}（确认新包无误后可手动删除）")
        else:
            try:
                clear_readonly(final)
                shutil.copytree(build, final, dirs_exist_ok=True)
                log("   旧包目录被占用，已用覆盖式合并更新 ✅")
            except Exception as e:
                log(f"   [错误] 替换失败: {e}")
                log(f"   新包完整保留在: {build}")
                return 3
    try:
        build.rename(final)
        log(f"   路径: {final}")
    except Exception:
        if not (final / "restore-new-pc.sh").exists():
            log(f"   [错误] 新包落地失败，完整新包保留在: {build}")
            return 4
        log(f"   路径: {final}")

    for b in out_root.glob(f"{PKG_PREFIX}*.building-*"):
        if b.is_dir():
            try:
                shutil.rmtree(b)
                log(f"   已清理临时构建目录: {b.name}")
            except Exception:
                log(f"   [提示] 临时目录未能自动删除，可手动删除: {b.name}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
