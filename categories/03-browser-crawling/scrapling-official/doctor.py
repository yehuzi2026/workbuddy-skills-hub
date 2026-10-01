# -*- coding: utf-8 -*-
"""
Scrapling 本机体检（doctor）

用途：一键确认本机 Scrapling 是否可用。覆盖 HTTP / JS渲染 / 反爬破解(Cloudflare) / 国内招标站
      四级能力，并检测会干扰抓取的本机代理变量。

用法（Git Bash）：
    export PATH="/c/Users/AHS/.workbuddy/binaries/PortableGit/versions/1.2.0/usr/bin:$PATH"
    export PYTHONIOENCODING=utf-8
    C:/Users/AHS/.workbuddy/binaries/python/envs/default/Scripts/python.exe doctor.py

耗时：Cloudflare 那一步需 45~90 秒，属正常，不要误判为卡死。
"""
import os
import sys
import time

PASS, FAIL, WARN = [], [], []


def head(t):
    print("\n" + "=" * 62 + f"\n{t}\n" + "=" * 62, flush=True)


def ok(n, d):
    PASS.append(n)
    print(f">>> [PASS] {n} | {d}", flush=True)


def bad(n, d):
    FAIL.append(n)
    print(f">>> [FAIL] {n} | {d}", flush=True)


def warn(n, d):
    WARN.append(n)
    print(f">>> [WARN] {n} | {d}", flush=True)


head("0. 环境与版本")
try:
    import scrapling
    print("scrapling:", scrapling.__version__, "| python:", sys.version.split()[0], flush=True)
except Exception as e:
    print("scrapling 导入失败:", e)
    sys.exit(1)

# 本机代理检测：WorkBuddy 注入的沙箱代理会拦掉部分站点，报 502 / CONNECT tunnel failed
proxies = {k: v for k, v in os.environ.items()
           if k.lower() in ("http_proxy", "https_proxy", "all_proxy")}
if proxies:
    warn("本机代理", f"{proxies} -> 目标站若报 502/CONNECT tunnel failed，"
                     "用 `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY` 剥离后重试")
else:
    ok("本机代理", "未设置，走直连")

head("1. HTTP 静态抓取（最快路径）")
try:
    from scrapling.fetchers import Fetcher
    t0 = time.time()
    p = Fetcher.get("https://quotes.toscrape.com/", stealthy_headers=True)
    ok("HTTP静态抓取", f"状态码={p.status} 抓到{len(p.css('.quote'))}条 耗时{time.time()-t0:.1f}s")
except Exception as e:
    bad("HTTP静态抓取", f"{type(e).__name__}: {str(e)[:80]}")

head("2. JS 渲染抓取")
try:
    from scrapling.fetchers import DynamicFetcher
    t0 = time.time()
    p = DynamicFetcher.fetch("https://quotes.toscrape.com/js/", headless=True)
    ok("JS渲染抓取", f"状态码={p.status} 抓到{len(p.css('.quote'))}条 耗时{time.time()-t0:.1f}s")
except Exception as e:
    bad("JS渲染抓取", f"{type(e).__name__}: {str(e)[:80]}")

head("3. 隐身模式破解 Cloudflare Turnstile（核心能力，耗时较长）")
try:
    from scrapling.fetchers import StealthyFetcher
    t0 = time.time()
    p = StealthyFetcher.fetch(
        "https://nopecha.com/demo/cloudflare",
        headless=True, solve_cloudflare=True, network_idle=True, timeout=90000,
    )
    links = p.css("#padded_content a")
    ok("Cloudflare破解", f"状态码={p.status} 目标元素{len(links)}个 耗时{time.time()-t0:.1f}s")
except Exception as e:
    bad("Cloudflare破解", f"{type(e).__name__}: {str(e)[:80]}")

head("4. 国内站点连通性（含招标类公开站）")
# verify=False 用于绕过部分政务站证书链配置问题；报 502 的多为代理拦截
DOMESTIC = [
    "https://www.baidu.com",
    "https://www.cebpubservice.cn/",
    "https://www.hbggzyfwpt.cn/",
]
from scrapling.fetchers import Fetcher
for u in DOMESTIC:
    try:
        p = Fetcher.get(u, timeout=25, verify=False)
        t = (p.css("title::text").get() or "").strip()[:30]
        ok(f"国内站 {u.split('//')[1][:26]}", f"状态码={p.status} 标题={t}")
    except Exception as e:
        bad(f"国内站 {u.split('//')[1][:26]}", f"{type(e).__name__}: {str(e)[:70]}")

head("体检汇总")
for n in PASS:
    print(f"PASS | {n}")
for n in WARN:
    print(f"WARN | {n}")
for n in FAIL:
    print(f"FAIL | {n}")
print(f"\n通过 {len(PASS)} / 警告 {len(WARN)} / 失败 {len(FAIL)}")
