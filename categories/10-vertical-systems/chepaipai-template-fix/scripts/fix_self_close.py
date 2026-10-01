#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_self_close.py
把 HTML in-DOM 模板(或 Vue 字符串模板)里所有自闭合的 Element Plus 组件
  <el-xxx ... />
改为显式闭合
  <el-xxx ...></el-xxx>
以根治 HTML in-DOM 模板下「自闭合非 void 自定义元素不自闭、吞掉后续兄弟节点」的坑。

用法:
  python fix_self_close.py <target_file> [--check]
  --check  只统计不改写

正则要点：属性部分只允许 "..." / '...' 内任意字符（含 >），其余单个字符排除
引号与 > —— 这样分支无歧义，避免灾难性回溯（"[^"]*"|'[^']*'|[^>] 会让 [^>] 吞掉
引号字符，长行上 2^N 回溯爆炸卡死）。
"""
import re, shutil, datetime, sys, os

PAT = re.compile(r'<(el-[A-Za-z0-9-]+)((?:"[^"]*"|\'[^\']*\'|[^>\'"])*?)\s*/>')


def fix(path, do_write=True):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    counts = {}

    def repl(m):
        name = m.group(1)
        attrs = m.group(2)
        counts[name] = counts.get(name, 0) + 1
        return "<%s%s></%s>" % (name, attrs, name)

    new_text, n = PAT.subn(repl, text)
    print("total replaced:", n)
    for k in sorted(counts, key=lambda x: -counts[x]):
        print("  %-22s %d" % (k, counts[k]))
    remain = len(PAT.findall(new_text))
    print("remaining self-closing el tags:", remain)

    if do_write and n > 0:
        bak = path + ".bak_selfclose_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, bak)
        print("backup ->", bak)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        print("written ->", path)
    return n, counts, remain


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python fix_self_close.py <file> [--check]")
        sys.exit(2)
    path = sys.argv[1]
    check = "--check" in sys.argv
    fix(path, do_write=not check)
