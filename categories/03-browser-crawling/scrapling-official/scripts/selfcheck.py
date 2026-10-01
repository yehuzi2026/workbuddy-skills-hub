# -*- coding: utf-8 -*-
"""
Scrapling 技能本机自检脚本（WorkBuddy on Windows）

用途：一键确认 Scrapling 技能在本机是否「真的能用」。
背景：2026-09-14 曾出现「pip 包装好了、但浏览器内核没下完」的假就绪状态，
      单看 import 成功会误判为可用。本脚本逐层核验到「真实抓一次网页」为止。

用法：
    <受管venv>/Scripts/python.exe selfcheck.py            # 全量（含真实抓取）
    <受管venv>/Scripts/python.exe selfcheck.py --no-net   # 跳过联网（离线体检）
退出码：0 = 全部通过；1 = 存在失败项
"""
import os
import sys
import io
import argparse
import subprocess

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
VENV = r"C:\Users\AHS\.workbuddy\binaries\python\envs\default"
SCRIPTS = os.path.join(VENV, "Scripts")
MP = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\AHS\AppData\Local"), "ms-playwright")

ok_count = 0
fail_count = 0
warn_count = 0


def line(status, text):
    global ok_count, fail_count, warn_count
    if status == "OK":
        ok_count += 1
    elif status == "FAIL":
        fail_count += 1
    else:
        warn_count += 1
    icon = {"OK": "✅", "FAIL": "🔴", "WARN": "🟡"}[status]
    print(f"  {icon} {text}")


def check_paths():
    print("\n[1/5] 关键路径")
    for label, p in [
        ("受管 venv python", os.path.join(SCRIPTS, "python.exe")),
        ("scrapling CLI", os.path.join(SCRIPTS, "scrapling.exe")),
        ("scrapling MCP", os.path.join(SCRIPTS, "scrapling-mcp.exe")),
        ("技能目录 SKILL.md", os.path.join(SKILL_DIR, "SKILL.md")),
    ]:
        line("OK" if os.path.exists(p) else "FAIL", f"{label}: {p}")


def check_pkgs():
    print("\n[2/5] Python 依赖")
    mods = ["scrapling", "curl_cffi", "playwright", "patchright", "browserforge",
            "lxml", "cssselect", "w3lib", "msgspec", "anyio"]
    for m in mods:
        try:
            mod = __import__(m)
            line("OK", f"{m} {getattr(mod, '__version__', '')}".strip())
        except Exception as e:
            line("FAIL", f"{m} 导入失败: {type(e).__name__}: {e}")
    # fetchers 三件套
    try:
        from scrapling.fetchers import Fetcher, DynamicFetcher, StealthyFetcher  # noqa
        line("OK", "fetchers: Fetcher / DynamicFetcher / StealthyFetcher 可导入")
    except Exception as e:
        line("FAIL", f"fetchers 导入失败: {type(e).__name__}: {e}")


def check_browsers():
    print("\n[3/5] 浏览器内核 (ms-playwright)")
    if not os.path.isdir(MP):
        line("FAIL", f"目录不存在: {MP}  → 需执行: scrapling install --force")
        return
    entries = [d for d in os.listdir(MP) if os.path.isdir(os.path.join(MP, d))]
    chromium = [d for d in entries if d.startswith("chromium")]
    if chromium:
        for c in chromium:
            size = sum(os.path.getsize(os.path.join(r, f))
                       for r, _, fs in os.walk(os.path.join(MP, c)) for f in fs)
            line("OK", f"{c}  ({size / 1024 / 1024:.0f} MB)")
    else:
        line("FAIL", "未找到 chromium 内核 → 需执行: scrapling install --force")
    other = [d for d in entries if not d.startswith("chromium")]
    if other:
        print(f"      其他: {', '.join(sorted(other))}")


def check_playwright_exe():
    print("\n[4/5] Playwright 浏览器可执行文件")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
            line("OK" if os.path.exists(exe) else "FAIL",
                 f"chromium: {exe}  (exists={os.path.exists(exe)})")
    except Exception as e:
        line("FAIL", f"无法解析 chromium 路径: {type(e).__name__}: {e}")


def check_realtime():
    print("\n[5/5] 真实抓取（端到端）")
    url = "https://example.com"
    try:
        from scrapling.fetchers import Fetcher
        r = Fetcher.get(url, timeout=30)
        html = getattr(r, "html_content", "") or ""
        line("OK" if getattr(r, "status", 0) == 200 and html else "FAIL",
             f"静态 Fetcher: status={getattr(r, 'status', '?')} len={len(html)}")
    except Exception as e:
        line("FAIL", f"静态 Fetcher 失败: {type(e).__name__}: {str(e)[:160]}")
    try:
        from scrapling.fetchers import DynamicFetcher
        r = DynamicFetcher.fetch(url, headless=True, timeout=60000)
        html = getattr(r, "html_content", "") or ""
        line("OK" if getattr(r, "status", 0) == 200 and html else "FAIL",
             f"DynamicFetcher(浏览器): status={getattr(r, 'status', '?')} len={len(html)}")
    except Exception as e:
        line("FAIL", f"DynamicFetcher 失败: {type(e).__name__}: {str(e)[:160]}")


def main():
    ap = argparse.ArgumentParser(description="Scrapling 技能本机自检")
    ap.add_argument("--no-net", action="store_true", help="跳过联网抓取（仅离线体检）")
    args = ap.parse_args()

    print("=" * 64)
    print("Scrapling 技能自检  |  WorkBuddy on Windows")
    print(f"解释器: {sys.executable}")
    print(f"技能目录: {SKILL_DIR}")
    print("=" * 64)

    check_paths()
    check_pkgs()
    check_browsers()
    check_playwright_exe()
    if args.no_net:
        print("\n[5/5] 真实抓取 —— 已按 --no-net 跳过")
    else:
        check_realtime()

    print("\n" + "=" * 64)
    print(f"结果: ✅ {ok_count} 通过   🟡 {warn_count} 警告   🔴 {fail_count} 失败")
    if fail_count:
        print("修复建议: 在受管 venv 内执行  scrapling install --force")
        print("          必要时重装: pip install -U \"scrapling[all]\"")
    else:
        print("技能就绪，可直接使用。")
    print("=" * 64)
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
