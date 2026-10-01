#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix-gitbash-coreutils.py — Git Bash 缺 coreutils 自愈修复器

症状
-----
Git Bash 里 ls / cat / grep / head / sed / awk / dirname / xargs ... 全部
"command not found"，同时 stderr 反复刷：
    shell-runtime-bash-env.sh: line 3: dirname: command not found
    shell-runtime-bash-env.sh: line 3: cd: null directory

根因（2026-09-15 定位）
-----------------------
1) WorkBuddy 以「非登录 + 非交互」方式启动 bash，只读 BASH_ENV 指向的
   cli/vendor/shim/shell-runtime-bash-env.sh，因此 /etc/profile 根本不执行
   —— 而 /etc/profile 才是把 /mingw64/bin:/usr/local/bin:/usr/bin:/bin
   写进 PATH 的地方。
2) PATH 里没有 /usr/bin → 该 shim 第 3 行的 dirname 找不到。
3) 第 3 行失败 → __codebuddy_shell_runtime_dir 为空 → 第 5/6 行的
   [ ! -f "/safe-bin/..." ] 判断全部短路 → brokered-sandbox-bash-env.sh
   没被 source → brokered-bin 也没进 PATH。
4) 结果：整套 coreutils 消失。一个 dirname 引发连锁瘫痪。

为何反复发作
------------
$HOME 下原本没有 .bashrc / .bash_profile / .profile，没有任何用户级入口去补
PATH。换机、迁移、或 WorkBuddy 升级覆盖了 shim 文件之后，必然复发。

本脚本做三件事
--------------
  A. 给 WorkBuddy 的 BASH_ENV shim 注入最小 PATH 引导（幂等，先自动备份）
  B. 确保 ~/.bashrc 与 ~/.bash_profile 存在（用户级统一入口）
  C. 用新起的 bash 进程实测验证，输出中文诊断报告

用法
----
  python fix-gitbash-coreutils.py            # 修复 + 验证
  python fix-gitbash-coreutils.py --check    # 只诊断，不写任何文件
  python fix-gitbash-coreutils.py --restore  # 从备份还原 shim
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

MARKER = "# [WorkBuddy coreutils bootstrap]"
GUARD_VAR = "WB_PATH_BOOTSTRAPPED"

BOOTSTRAP_BLOCK = """# ---------------------------------------------------------------------------
# [WorkBuddy coreutils bootstrap]  自动注入，请勿手工删除
# 必须在任何 dirname / $(...) 调用之前执行，否则本文件第 3 行会自我中断：
#   非登录 + 非交互的 bash 不执行 /etc/profile，PATH 里没有 /usr/bin，
#   于是 dirname 找不到 -> __codebuddy_shell_runtime_dir 为空 ->
#   第 5/6 行 [ ! -f "/safe-bin/..." ] 全部短路 ->
#   brokered-sandbox-bash-env.sh 没被 source -> 整套 coreutils 消失。
# 这几行把 GNU 工具链补回 PATH，链条随即自愈（幂等）。
# 用户级自定义请写 ~/.bashrc，本处只做最小引导。
# ---------------------------------------------------------------------------
if [ -z "${WB_PATH_BOOTSTRAPPED:-}" ]; then
  WB_PATH_BOOTSTRAPPED=1
  export WB_PATH_BOOTSTRAPPED

  # /usr/bin、/mingw64/bin 是 MSYS2 挂载点，由 bash 自动解析到当前 PortableGit
  # 安装根，因此不写死 versions/1.2.0 这种版本号，换版本后依然有效。
  case ":${PATH}:" in
    *:/usr/bin:*) ;;
    *) PATH="/mingw64/bin:/usr/local/bin:/usr/bin:/bin${PATH:+:${PATH}}"; export PATH ;;
  esac

  if [ -n "${HOME:-}" ] && [ -f "${HOME}/.bashrc" ]; then
    . "${HOME}/.bashrc"
  fi
fi

"""

BASHRC_CONTENT = """# ==============================================================================
#  ~/.bashrc  —  WorkBuddy / Git Bash 环境修复（由 fix-gitbash-coreutils.py 维护）
# ------------------------------------------------------------------------------
#  解决现象：Git Bash 里 ls / cat / grep / head / sed / awk / dirname ...
#            全部 "command not found"，属于本机反复发作的老毛病。
#
#  根因链条：
#    1) WorkBuddy 以「非登录 + 非交互」方式启动 bash，只读 BASH_ENV，
#       因此 /etc/profile 不会执行 —— 而 /etc/profile 第 52 行才是把
#       /mingw64/bin:/usr/local/bin:/usr/bin:/bin 写进 PATH 的地方。
#    2) PATH 里既然没有 /usr/bin，BASH_ENV 脚本 shell-runtime-bash-env.sh
#       第 3 行的 dirname 就找不到；
#    3) 该行失败 -> __codebuddy_shell_runtime_dir 为空 -> 第 5/6 行的
#       [ ! -f "/safe-bin/..." ] 判断全部短路 -> brokered-sandbox-bash-env.sh
#       没被 source -> brokered-bin 也没进 PATH；
#    4) 结果：整套 coreutils 消失。一个 dirname 引发连锁瘫痪。
#
#  本文件同时被 ~/.bash_profile 与 ~/.profile 引用，登录 shell 一样受益。
#  幂等：重复 source 不会把 PATH 越撑越长。
# ==============================================================================

# ---------- 1. 补回 PortableGit 的 GNU 工具链 ----------
# /usr/bin 与 /mingw64/bin 是 MSYS2 挂载点，由 bash 自动解析到当前 PortableGit
# 安装根，因此不写死版本号（如 versions/1.2.0），换版本后依然有效。
case ":${PATH}:" in
  *:/usr/bin:*)
    : # 已就绪，无需处理
    ;;
  *)
    PATH="/mingw64/bin:/usr/local/bin:/usr/bin:/bin${PATH:+:${PATH}}"
    export PATH
    ;;
esac

# ---------- 2. 关于 GNU find / sort ----------
# C:\\Windows\\System32 里也有 find.exe 和 sort.exe，语义与 GNU 完全不同
# （Windows 的 find 是字符串搜索，脚本里 find . -name x 会直接报错）。
# 第 1 步已把 /mingw64/bin 与 /usr/bin 前置到 C:\\Windows\\System32 之前，
# 因此 find / sort 会命中 GNU 版本，这里无需额外处理。

# ---------- 3. 保住 CodeBuddy 沙箱目录的最高优先级 ----------
# safe-bin 拦截安全删除、brokered-bin 提供受控命令转发。
# 上面的前置操作可能把它们挤到后面，这里幂等地把它们重新提到最前，
# 确保沙箱与安全删除能力不因本次修复而降级。
for __wb_dir in "${CODEBUDDY_BROKERED_BIN_DIR:-}" "${CODEBUDDY_SAFE_DELETE_BIN_DIR:-}"; do
  [ -n "$__wb_dir" ] || continue
  case ":${PATH}:" in
    *":${__wb_dir}:"*)
      : # 已是最前，无需处理
      ;;
    *)
      PATH="${__wb_dir}:${PATH}"
      export PATH
      ;;
  esac
done
unset __wb_dir

# ---------- 4. 载入标记（供自检 / 排障使用）----------
WB_BASHRC_LOADED=yes
export WB_BASHRC_LOADED
"""

BASH_PROFILE_CONTENT = """# [WorkBuddy coreutils bootstrap]
# ==============================================================================
#  ~/.bash_profile  —  登录 shell 入口
# ------------------------------------------------------------------------------
#  登录 shell 读 ~/.bash_profile；非登录/非交互的 bash 走 BASH_ENV。
#  这里只负责把 ~/.bashrc 引进来，修复逻辑统一放在 ~/.bashrc 里维护。
# ==============================================================================

test -f ~/.profile && . ~/.profile
test -f ~/.bashrc  && . ~/.bashrc
"""

# 验证用到的命令清单
PROBE_COMMANDS = [
    "ls", "cat", "cp", "mv", "mkdir", "touch", "ln", "chmod", "date", "sleep",
    "head", "tail", "wc", "sort", "uniq", "cut", "tr", "sed", "awk", "grep",
    "find", "xargs", "du", "df", "env", "dirname", "basename", "realpath",
    "readlink", "stat", "mktemp", "seq", "tee", "git",
]


# --------------------------------------------------------------------------
# 环境探测
# --------------------------------------------------------------------------

def home_dir() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def find_workbuddy_roots() -> list[Path]:
    """找出可能的 WorkBuddy 安装根目录。"""
    cands: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        try:
            k = str(p.resolve()).lower()
        except OSError:
            k = str(p).lower()
        if k not in seen and p.is_dir():
            seen.add(k)
            cands.append(p)

    # 1) 从运行中的自身路径反推（脚本可能在 WorkBuddy 工作区内）
    for base in (Path.cwd(), Path(__file__).resolve().parent):
        for parent in [base, *base.parents]:
            if parent.name.lower() == "workbuddy":
                add(parent)
                break

    # 2) 常见安装位置
    for drive in ("C:", "D:", "E:"):
        for sub in ("LenovoSoftstore/Install/WorkBuddy",
                    "Program Files/WorkBuddy",
                    "Program Files (x86)/WorkBuddy",
                    "WorkBuddy"):
            add(Path(f"{drive}/{sub}"))

    # 3) 从环境变量线索找
    for key in ("WORKBUDDY_HOME", "CODEBUDDY_HOME", "LOCALAPPDATA"):
        v = os.environ.get(key)
        if v:
            add(Path(v) / "WorkBuddy")
            add(Path(v).parent / "WorkBuddy")

    return cands


def find_shim() -> Path | None:
    """定位 BASH_ENV 指向的 shell-runtime-bash-env.sh。"""
    # 最可靠：直接问环境变量
    env_shim = os.environ.get("BASH_ENV")
    if env_shim:
        p = Path(env_shim)
        if p.is_file():
            return p

    rel = Path("resources/app.asar.unpacked/cli/vendor/shim/shell-runtime-bash-env.sh")
    for root in find_workbuddy_roots():
        p = root / rel
        if p.is_file():
            return p
    return None


def find_portablegit() -> Path | None:
    """定位 WorkBuddy 托管的 PortableGit。"""
    bases = [home_dir() / ".workbuddy/binaries/PortableGit"]
    bases += [r / "PortableGit" for r in find_workbuddy_roots()]
    for base in bases:
        if not base.is_dir():
            continue
        vers = sorted((base / "versions").glob("*"), reverse=True) if (base / "versions").is_dir() else []
        for v in vers:
            if (v / "usr/bin").is_dir():
                return v
    return None


def bash_exe() -> Path | None:
    pg = find_portablegit()
    if pg:
        for c in (pg / "bin/bash.exe", pg / "usr/bin/bash.exe"):
            if c.is_file():
                return c
    return None


# --------------------------------------------------------------------------
# 写文件（必须无 BOM + LF，否则 sh 会语法错）
# --------------------------------------------------------------------------

def write_text_no_bom(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


# --------------------------------------------------------------------------
# A. shim 注入
# --------------------------------------------------------------------------

def backup_shim(shim: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = shim.with_name(f"{shim.name}.bak-{stamp}")
    shutil.copy2(shim, dst)
    return dst


def shim_has_bootstrap(shim: Path) -> bool:
    return MARKER in read_text(shim)


def inject_shim(shim: Path, dry: bool) -> tuple[bool, str]:
    """把 BOOTSTRAP_BLOCK 注入 shim 最顶部。返回 (是否改动, 说明)。"""
    text = read_text(shim)
    if MARKER in text:
        return False, "shim 已含 bootstrap，跳过"

    new_text = BOOTSTRAP_BLOCK + text
    if dry:
        return True, "（dry-run）将注入 bootstrap"
    bak = backup_shim(shim)
    write_text_no_bom(shim, new_text)
    return True, f"shim 已注入 bootstrap（备份：{bak.name}）"


def strip_bootstrap(shim: Path, dry: bool) -> tuple[bool, str]:
    """从 shim 中移除 bootstrap 块（回滚用）。"""
    text = read_text(shim)
    if MARKER not in text:
        return False, "shim 未含 bootstrap，无需移除"
    pattern = re.compile(
        r"# -+\n" + re.escape(MARKER) + r".*?\nfi\n\n",
        re.DOTALL,
    )
    new_text, n = pattern.subn("", text, count=1)
    if n == 0:
        # 兜底：按 guard 变量粗切
        idx = text.find(MARKER)
        end = text.find("\nfi\n", idx)
        if end == -1:
            return False, "定位 bootstrap 边界失败，请手工处理（已保留备份）"
        new_text = text[end + len("\nfi\n"):].lstrip("\n")
    if dry:
        return True, "（dry-run）将移除 bootstrap"
    write_text_no_bom(shim, new_text)
    return True, "shim 已移除 bootstrap"


# --------------------------------------------------------------------------
# B. 用户级 dotfile
# --------------------------------------------------------------------------

def ensure_dotfile(path: Path, content: str, marker: str, dry: bool) -> tuple[bool, str]:
    if path.is_file():
        cur = read_text(path)
        if marker in cur:
            return False, f"{path.name} 已就绪"
        if dry:
            return True, f"（dry-run）将覆盖 {path.name}"
        bak = path.with_name(path.name + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(path, bak)
        write_text_no_bom(path, content)
        return True, f"{path.name} 已更新（原文件备份为 {bak.name}）"
    if dry:
        return True, f"（dry-run）将创建 {path.name}"
    write_text_no_bom(path, content)
    return True, f"{path.name} 已创建"


# --------------------------------------------------------------------------
# C. 验证
# --------------------------------------------------------------------------

def verify(verbose: bool = True) -> int:
    exe = bash_exe()
    if not exe:
        print("  🔴 找不到 PortableGit 的 bash.exe，无法验证")
        return -1

    script = (
        'printf "PATH_HEAD=%s\\n" "${PATH%%:*}"; '
        'printf "GUARD=%s\\n" "${' + GUARD_VAR + ':-NO}"; '
        'printf "BASHRC=%s\\n" "${WB_BASHRC_LOADED:-NO}"; '
        'm=0; '
        'for c in ' + " ".join(PROBE_COMMANDS) + '; do '
        'command -v "$c" >/dev/null 2>&1 || { printf "MISSING %s\\n" "$c"; m=$((m+1)); }; '
        'done; '
        'printf "MISSING_COUNT=%s\\n" "$m"; '
        'printf "LS_VER=%s\\n" "$(ls --version 2>/dev/null | head -1)"'
    )
    try:
        cp = subprocess.run(
            [str(exe), "-c", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  🔴 验证执行失败：{exc}")
        return -1

    out = cp.stdout or ""

    guard = re.search(r"^GUARD=(.*)$", out, re.M)
    bashrc = re.search(r"^BASHRC=(.*)$", out, re.M)
    miss = re.search(r"^MISSING_COUNT=(\d+)$", out, re.M)
    lsver = re.search(r"^LS_VER=(.*)$", out, re.M)

    missing = re.findall(r"^MISSING (\S+)$", out, re.M)

    if verbose:
        print(f"  引导标记 {GUARD_VAR} : {guard.group(1) if guard else '?'}")
        print(f"  ~/.bashrc 载入标记    : {bashrc.group(1) if bashrc else '?'}")
        print(f"  coreutils 版本        : {lsver.group(1) if lsver else '?'}")
        print(f"  命令探活              : {len(PROBE_COMMANDS) - int(miss.group(1) if miss else -1)}"
              f"/{len(PROBE_COMMANDS)} 可用")
        if missing:
            print(f"  🔴 仍缺失：{', '.join(missing)}")
        if cp.stderr and cp.stderr.strip():
            print("  🟡 stderr 输出：")
            for line in cp.stderr.strip().splitlines()[:6]:
                print(f"      {line}")
        else:
            print("  ✅ stderr 干净（dirname 报错链已消除）")

    if miss and miss.group(1) == "0" and not (cp.stderr or "").strip():
        return 0
    return 1


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Git Bash 缺 coreutils 自愈修复器")
    ap.add_argument("--check", action="store_true", help="只诊断，不写任何文件")
    ap.add_argument("--restore", action="store_true", help="从 shim 移除已注入的 bootstrap")
    args = ap.parse_args()

    dry = args.check
    mode = "回滚" if args.restore else ("诊断" if dry else "修复")

    print("=" * 66)
    print(f"  Git Bash coreutils 自愈修复器 — 模式：{mode}")
    print("=" * 66)

    # --- 环境 ---
    pg = find_portablegit()
    print("\n[1/4] 环境探测")
    print(f"  HOME             : {home_dir()}")
    print(f"  PortableGit      : {pg if pg else '🔴 未找到'}")
    print(f"  BASH_ENV         : {os.environ.get('BASH_ENV') or '(未设置)'}")

    shim = find_shim()
    print(f"  WorkBuddy shim   : {shim if shim else '🔴 未找到'}")

    if args.restore:
        if not shim:
            print("\n🔴 找不到 shim，无法回滚。")
            return 2
        print("\n[2/4] 回滚 shim")
        changed, msg = strip_bootstrap(shim, dry)
        print(f"  {'✅' if changed else '⚪'} {msg}")
        print("\n[3/4] 验证")
        rc = verify()
        print("\n" + "=" * 66)
        print("  回滚完成。coreutils 会再次缺失——这正是原来的状态。")
        print("=" * 66)
        return 0 if rc == 0 else 1
    if not shim:
        print("\n🔴 找不到 WorkBuddy 的 BASH_ENV shim 脚本。")
        print("   若 WorkBuddy 装在别处，请手动设置环境变量 BASH_ENV 后重试。")
        return 2

    # --- A. shim ---
    print("\n[2/4] 注入 BASH_ENV 引导")
    try:
        changed, msg = inject_shim(shim, dry)
        print(f"  {'✅' if changed else '⚪'} {msg}")
    except PermissionError:
        print("  🔴 写入被拒（文件被占用或权限不足）。请关掉 WorkBuddy 后重试。")
        return 3
    except OSError as exc:
        print(f"  🔴 写入失败（{exc}）。若为资源占用，稍后重试即可。")
        return 3

    # --- B. dotfiles ---
    print("\n[3/4] 用户级入口")
    h = home_dir()
    for name, content, marker in (
        (".bashrc", BASHRC_CONTENT, "WB_BASHRC_LOADED"),
        (".bash_profile", BASH_PROFILE_CONTENT, MARKER),
    ):
        ch, m = ensure_dotfile(h / name, content, marker, dry)
        print(f"  {'✅' if ch else '⚪'} {m}")

    # --- C. 验证 ---
    print("\n[4/4] 实测验证")
    rc = verify()

    print("\n" + "=" * 66)
    if rc == 0:
        print("  ✅ 修复完成：coreutils 已全部恢复，stderr 干净。")
    elif dry:
        print("  ℹ️  诊断结束。去掉 --check 即可实际写入修复。")
    else:
        print("  🟡 修复已写入，但验证未完全通过，请查看上面的缺失项。")
    print("=" * 66)
    return rc if not dry else 0


if __name__ == "__main__":
    sys.exit(main())
