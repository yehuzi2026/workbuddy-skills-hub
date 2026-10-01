#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_panels.py (车拍拍主站后台 · 逐面板验证模板)
登录 admin/admin123，真实点击每个侧边栏菜单，逐个面板验证：
  - 面板确实切换（currentMenu === key）
  - 面板渲染出 el-card/el-form/el-table 任一（结构可见）
  - 全程无未捕获 JS 错误 / console.error
用法:
  python verify_panels.py
注意: MENUS 为目标站点的菜单 key->中文 映射，换站请改此处；保险后台见 verify_insu.py 同构。
"""
import sys
from playwright.sync_api import sync_playwright

BASE = "http://wuhanhonganghang.cn"
ADMIN, PWD = "admin", "admin123"

# key -> 菜单中文文字（用于点击 li:has-text）
MENUS = [
    ("dashboard", "数据看板"), ("vehicle", "车辆审批"), ("auction", "拍卖管理"),
    ("quote", "报价管理"), ("order", "订单管理"), ("member", "会员管理"),
    ("finance", "财务结算"), ("deposit", "保证金"), ("material", "物资拍卖"),
    ("aftersale", "售后管理"), ("observer", "保险公司"), ("picc", "人保对接"),
    ("notification", "消息通知"), ("settings", "系统设置"), ("report", "数据报表"),
    ("search", "全局搜索"),
]

PROXY_JS = (
    "() => {"
    "const appEl=document.querySelector('#app');"
    "if(!appEl||!appEl.__vue_app__) return {mounted:false};"
    "const inst=appEl.__vue_app__._instance;"
    "return {mounted:true, currentMenu: inst.proxy.currentMenu, adminRole: inst.proxy.adminRole};"
    "}"
)


def main():
    errs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script(
            "window.__errs=[];"
            "window.addEventListener('error',e=>window.__errs.push('ERR:'+(e.message||e.error)));"
            "window.addEventListener('unhandledrejection',e=>window.__errs.push('REJ:'+(e.reason&&e.reason.message||e.reason)));"
        )
        page.on("console", lambda m: errs.append("CONSOLE:%s:%s" % (m.type, m.text)) if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append("PAGEERROR:%s" % e))

        page.goto(BASE + "/admin/index.html", wait_until="networkidle")
        page.wait_for_timeout(800)
        page.fill('input[type=text], input:not([type=password])', ADMIN)
        page.fill('input[type=password]', PWD)
        btn = page.locator('button:has-text("登 录"), button:has-text("登录")').first
        if btn.count() == 0:
            btn = page.locator('button[type=submit], button').first
        btn.click()
        page.wait_for_timeout(2500)
        if "/admin/dashboard.php" not in page.url:
            print("FATAL: 未跳转到 dashboard.php"); browser.close(); sys.exit(2)

        st = page.evaluate(PROXY_JS)
        if not st.get("mounted"):
            print("FATAL: app not mounted"); browser.close(); sys.exit(2)

        results = []
        for key, label in MENUS:
            try:
                page.click("li:has-text('%s')" % label, timeout=8000)
                page.wait_for_timeout(1200)
                info = page.evaluate(PROXY_JS)
                composite = page.evaluate(
                    "document.querySelectorAll('#app .el-card, #app .el-form, #app .el-table').length"
                )
                ok_menu = info.get("currentMenu") == key
                ok_render = composite > 0
                flag = "PASS" if (ok_menu and ok_render) else "FAIL"
                results.append((key, label, ok_menu, ok_render, composite, flag))
                print("  %-12s %-6s menu=%s composite=%d -> %s" % (key, label, ok_menu, composite, flag))
            except Exception as e:
                results.append((key, label, False, False, 0, "ERR:%s" % e))
                print("  %-12s %-6s EXCEPTION %s" % (key, label, e))

        page_errs = page.evaluate("window.__errs||[]")
        print("\n=== JS 错误汇总 ===")
        print("page.__errs:", page_errs if page_errs else "无")
        real_console = [e for e in errs if "CONSOLE:error" in e or "PAGEERROR" in e]
        print("console/page errors:", real_console if real_console else "无")

        fails = [r for r in results if r[5] != "PASS"]
        print("\n=== 结果 ===")
        print("面板 PASS: %d / %d" % (sum(1 for r in results if r[5] == "PASS"), len(results)))
        if fails:
            print("失败面板:"); 
            for f in fails: print("  ", f)
        browser.close()
        sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
