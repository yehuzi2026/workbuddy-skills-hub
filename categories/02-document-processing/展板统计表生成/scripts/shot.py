#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
展板统计表 HTML -> 2x 高清 PNG（自动裁掉底部白边）

用法:
    python shot.py <html路径> [输出png路径] [宽度px]

默认宽度 780px，默认输出与 html 同目录同名 .png。
依赖: Playwright 的 chromium headless shell（本机已装）+ Pillow
"""
import glob
import os
import subprocess
import sys

DEFAULT_WIDTH = 780
TALL = 4000          # 窗口给足高度，多余部分靠裁剪去掉
BOTTOM_PAD = 68      # 保留原设计 34px 下边距 (2x)


def find_chrome():
    pats = [
        os.path.expanduser("~/AppData/Local/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"),
        os.path.expanduser("~/AppData/Local/ms-playwright/chromium-*/chrome-win64/chrome.exe"),
        os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"),
        "/c/Program Files/Google/Chrome/Application/chrome.exe",
        "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    ]
    for p in pats:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[-1]
    raise SystemExit("[ERR] 找不到 Chromium/Chrome/Edge 可执行文件")


def render(chrome, html, out, width):
    url = "file:///" + os.path.abspath(html).replace("\\", "/")
    cmd = [
        chrome, "--headless", "--no-sandbox", "--disable-gpu",
        "--screenshot=" + out,
        "--window-size=%d,%d" % (width, TALL),
        "--force-device-scale-factor=2",
        "--hide-scrollbars",
        "--default-background-color=FFFFFFFF",
        url,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(out):
        raise SystemExit("[ERR] 渲染失败:\n" + (r.stderr or r.stdout))
    return out


def trim_whitespace(png, pad=BOTTOM_PAD):
    try:
        from PIL import Image
    except ImportError:
        print("[WARN] 未装 Pillow，跳过裁白边")
        return None
    im = Image.open(png).convert("RGB")
    w, h = im.size
    px = im.load()
    last = 0
    for y in range(h - 1, -1, -1):
        white = True
        for x in range(0, w, 4):
            r, g, b = px[x, y]
            if not (r > 250 and g > 250 and b > 250):
                white = False
                break
        if not white:
            last = y
            break
    new_h = min(h, last + pad)
    if new_h < h:
        im.crop((0, 0, w, new_h)).save(png)
    return (w, h, new_h)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    html = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(html)[0] + ".png"
    width = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_WIDTH
    if not os.path.exists(html):
        raise SystemExit("[ERR] html 不存在: " + html)

    chrome = find_chrome()
    print("[1/2] 渲染:", chrome)
    render(chrome, html, out, width)
    print("[2/2] 裁白边:", trim_whitespace(out))
    print("[OK] ->", os.path.abspath(out))


if __name__ == "__main__":
    main()
