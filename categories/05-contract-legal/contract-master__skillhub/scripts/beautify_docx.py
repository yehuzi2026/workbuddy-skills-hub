#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
beautify_docx.py — OfficeCLI 结构层美化后处理（跨 skill / 跨生成器通用）

设计原则（P0 约束，不可违反）：
  - 严禁改动任何 skill 的字体规范（宋体 / 黑体 / 仿宋等）。
    本脚本只做结构性美化，绝不触碰 run 级字体、字号、颜色。
  - 所有 officecli 调用均被捕获；单步失败不影响其他步骤，绝不损坏原文件。
  - 基线校验：若原始文件本身 OpenXML 非法，立即中止，不做任何写入。

依赖：officecli（iOfficeAI/OfficeCLI，v1.0.143+），二进制路径 ~/.local/bin/officecli

用法：
  python3 beautify_docx.py <file.docx> [选项]

选项：
  --mode {report,draft}         场景模式（保留参数，默认 report，当前不自动注入任何标识）
  --header-text "文本"          自定义页眉文字（不传则不添加页眉）
  --footer-text "文本"          自定义页脚文字（不传则不添加页脚）
  --no-header                  跳过页眉（若已设置）
  --no-footer                  跳过页脚（若已设置）
  --no-table                   跳过表格美化
  --table-style "样式名"        表格样式（默认 "Light Grid"，中性网格）
  --no-margin                  跳过页边距兜底
  --no-validate                跳过美化后 validate + view issues 质量门

退出码：
  0  成功（含可忽略的非致命步骤告警）
  1  原始文件已损坏或美化后校验未通过
  2  环境缺失（officecli 未安装）
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile

# 本脚本为跨 skill 通用组件，仅作结构层美化，绝不修改任何 run 级字体
# （宋体 / 黑体 / 仿宋等规范由各 skill 的 SKILL.md 与生成代码负责）。
# 重要：绝不硬编码任何律所 / 机构 / 品牌标识。
#       页眉 / 页脚文字必须由调用方通过 --header-text / --footer-text 显式传入。


def find_officecli():
    p = shutil.which("officecli")
    if p:
        return p
    for c in (
        os.path.expanduser("~/.local/bin/officecli"),
        "/usr/local/bin/officecli",
        "/opt/homebrew/bin/officecli",
    ):
        if os.path.exists(c):
            return c
    return None


def run_oc(oc, args, fatal=False, timeout=90):
    """运行 officecli。返回 (returncode, stdout, stderr)。"""
    try:
        r = subprocess.run([oc] + args, capture_output=True, text=True, timeout=timeout)
    except Exception as e:  # 超时 / 进程异常
        if fatal:
            raise
        return (-1, "", str(e))
    if fatal and r.returncode != 0:
        raise RuntimeError(f"officecli {' '.join(args)} 失败: {r.stderr.strip()[:200]}")
    return (r.returncode, r.stdout, r.stderr)


def style_header(oc, f, text):
    """页眉：已存在则更新，不存在则新增。"""
    rc, _, _ = run_oc(oc, ["get", f, "/header[1]"])
    if rc == 0:
        run_oc(oc, ["set", f, "/header[1]", "--prop", f"text={text}", "--prop", "align=right"])
        print(f"  ✓ 页眉更新 → {text}")
    else:
        run_oc(oc, ["add", f, "/", "--type", "header", "--prop", "type=default",
                    "--prop", f"text={text}", "--prop", "align=right"])
        print(f"  ✓ 页眉新增 → {text}")


def style_footer(oc, f, text):
    """页脚：已存在则更新，不存在则新增。"""
    rc, _, _ = run_oc(oc, ["get", f, "/footer[1]"])
    if rc == 0:
        run_oc(oc, ["set", f, "/footer[1]", "--prop", f"text={text}", "--prop", "align=center"])
        print(f"  ✓ 页脚更新 → {text}")
    else:
        run_oc(oc, ["add", f, "/", "--type", "footer", "--prop", "type=default",
                    "--prop", f"text={text}", "--prop", "align=center"])
        print(f"  ✓ 页脚新增 → {text}")


def has_table_style(oc, f, style_name):
    """检测目标 docx 是否已定义指定表格样式（如 Light Grid）。

    python-docx 默认模板自带 Light Grid 等 100+ 表格样式；
    Node.js docx 包生成的文件通常不含这些 Word 内置表格样式。
    据此判断应由哪条路径美化表格。
    """
    rc, out, _ = run_oc(oc, ["query", f, "style"])
    if rc != 0:
        return False
    return bool(re.search(r'(?:id|name)=%s\b' % re.escape(style_name), out)) \
        or (style_name in out)


def beautify_tables(oc, f, style_name):
    """表格精致化：跨生成器鲁棒方案。

    两种主流 docx 生成器对「表格样式」支持不同：
      - python-docx（合同智囊 / 手册智囊）：默认模板含 Light Grid 等命名样式，
        套用 style=Light Grid 可渲染网格；但若改用 border.all 直写 tblBorders，
        会因 tblPr 已含 tblLook（顺序约束）触发 OpenXML schema 错误。
      - Node.js docx（绩效智囊）：默认不含任何命名表格样式，套用 style=Light Grid
        会成为悬空引用（Word 不渲染网格，等于无效）；但 border.all 直写边框可用。

    策略：先检测目标样式是否已定义。
      - 已定义 → 套用命名样式（style=...），渲染可靠。
      - 未定义 → 改用 border.all 直写黑色单线边框，渲染可靠。
    并对每张表做「首选方法失败则回退另一种」的双保险。
    """
    use_named = has_table_style(oc, f, style_name)
    border_spec = "single;1pt;000000"
    i = 1
    styled = 0
    while i <= 100:  # 安全上限，避免无限循环
        if use_named:
            rc, _, _ = run_oc(oc, ["set", f, f"/body/tbl[{i}]",
                                   "--prop", f"style={style_name}"])
        else:
            rc, _, _ = run_oc(oc, ["set", f, f"/body/tbl[{i}]",
                                   "--prop", f"border.all={border_spec}"])
        if rc != 0:
            # 首选方法失败，回退另一种作为双保险
            if use_named:
                rc2, _, _ = run_oc(oc, ["set", f, f"/body/tbl[{i}]",
                                       "--prop", f"border.all={border_spec}"])
            else:
                rc2, _, _ = run_oc(oc, ["set", f, f"/body/tbl[{i}]",
                                       "--prop", f"style={style_name}"])
            if rc2 != 0:
                break
        styled += 1
        i += 1
    if styled:
        label = style_name if use_named else "黑色单线边框(border.all)"
        print(f"  ✓ 表格美化 → {styled} 个表格（{label}，生成器自适应）")
    else:
        print("  · 未发现表格，跳过")


def check_line_spacing(f):
    """行距红线检测：直接读 document.xml，扫描 w:spacing 中异常大的固定行距。

    ⚠️ 生成器最常见的"几百页"事故根因：python-docx 误用 line_spacing = Pt(360)
    （固定行距 360 磅 ≈ 12.7cm/行），而非 1.5 倍行距。此处兜底检测：
      - lineRule="exact" 且 line > 480（twips）→ 固定行距异常（>24pt），警告
      - lineRule="auto" 且 line > 480 → 多倍行距异常（>2倍），警告
    正常 1.5 倍行距 = line=360 + lineRule=auto，不触发。
    """
    try:
        with zipfile.ZipFile(f) as z:
            xml = z.read("word/document.xml").decode("utf-8")
    except Exception:
        return 0, 0
    exact_bad = re.findall(r'w:line="(\d+)"\s+w:lineRule="exact"', xml)
    auto_bad = re.findall(r'w:line="(\d+)"\s+w:lineRule="auto"', xml)
    exact_over = [int(v) for v in exact_bad if int(v) > 480]
    auto_over = [int(v) for v in auto_bad if int(v) > 480]
    total_bad = len(exact_over) + len(auto_over)
    if exact_over:
        print(f"  ⚠ 行距红线：检测到 {len(exact_over)} 段固定行距超 480 twips（>24pt）——"
              f"疑似误用 line_spacing=Pt(360)，会导致文档数百页！")
        print(f"    建议：python-docx 用 `paragraph_format.line_spacing = 1.5`（倍数），勿用 Pt(360)")
    if auto_over:
        print(f"  ⚠ 行距提示：{len(auto_over)} 段行距倍数超 2 倍，请确认是否为预期版式")
    return total_bad, len(re.findall(r'w:spacing', xml))


def main():
    ap = argparse.ArgumentParser(description="OfficeCLI 结构层美化（跨生成器通用）")
    ap.add_argument("file", help="待美化的 docx 路径")
    ap.add_argument("--mode", choices=["report", "draft"], default="report",
                   help="场景模式（保留参数，当前不影响默认美化行为，均不注入标识）")
    ap.add_argument("--header-text", default=None, help="自定义页眉文字（不传则不添加页眉）")
    ap.add_argument("--footer-text", default=None, help="自定义页脚文字（不传则不添加页脚）")
    ap.add_argument("--no-header", action="store_true")
    ap.add_argument("--no-footer", action="store_true")
    ap.add_argument("--no-table", action="store_true")
    ap.add_argument("--table-style", default="Light Grid")
    ap.add_argument("--no-margin", action="store_true")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()

    oc = find_officecli()
    if not oc:
        print("❌ 未找到 officecli，请先安装 iOfficeAI/OfficeCLI（参见 ~/.workbuddy/skills/officecli）",
              file=sys.stderr)
        return 2

    f = args.file
    if not os.path.exists(f):
        print(f"❌ 文件不存在：{f}", file=sys.stderr)
        return 2

    print(f"🎨 OfficeCLI 结构层美化（{args.mode} 模式）：{f}")

    # 0. 基线校验：原始文件必须合法
    rc, _, err = run_oc(oc, ["validate", f])
    if rc != 0:
        print(f"❌ 原始文件 OpenXML 校验未通过，中止美化以免损坏：\n{err.strip()[:300]}",
              file=sys.stderr)
        return 1

    # 0.5 行距红线检测（生成器"几百页"事故的最终防线，不阻塞但强警告）
    bad_count, _ = check_line_spacing(f)
    if bad_count:
        print(f"  ⚠ 行距红线检测：发现 {bad_count} 处异常固定行距，请务必修复后再交付！", file=sys.stderr)
    else:
        print("  ✓ 行距红线检测通过（无异常固定行距）")

    # 1. 文档级页面尺寸 + 页边距兜底（A4 标准：21×29.7cm；上下2.54cm / 左右3.18cm）
    #    ⚠️ 页面尺寸必须显式设置：python-docx 默认 Letter（21.59×27.94cm），
    #       Node.js docx 默认同 Letter，若不兜底会导出非 A4 版式。
    if not args.no_margin:
        try:
            run_oc(oc, ["set", f, "/section[1]",
                        "--prop", "pageWidth=21cm",
                        "--prop", "pageHeight=29.7cm",
                        "--prop", "marginTop=2.54cm",
                        "--prop", "marginBottom=2.54cm",
                        "--prop", "marginLeft=3.18cm",
                        "--prop", "marginRight=3.18cm"], fatal=True)
            print("  ✓ 页面兜底 → A4 21×29.7cm + 边距 上下2.54cm / 左右3.18cm")
        except Exception as e:
            print(f"  ⚠ 页面尺寸/页边距设置跳过：{e}")

    # 2. 表格精致化
    if not args.no_table:
        beautify_tables(oc, f, args.table_style)

    # 3. 页眉（仅当显式传入 --header-text 时才设置；绝不自动注入任何标识）
    if not args.no_header and args.header_text:
        try:
            style_header(oc, f, args.header_text)
        except Exception as e:
            print(f"  ⚠ 页眉处理跳过：{e}")

    # 4. 页脚（仅当显式传入 --footer-text 时才设置）
    if not args.no_footer and args.footer_text:
        try:
            style_footer(oc, f, args.footer_text)
        except Exception as e:
            print(f"  ⚠ 页脚处理跳过：{e}")

    # 5. 质量门
    if not args.no_validate:
        rc, _, err = run_oc(oc, ["validate", f])
        if rc != 0:
            print(f"  ❌ 美化后校验未通过：\n{err.strip()[:300]}", file=sys.stderr)
            return 1
        print("  ✓ 美化后 OpenXML 校验通过")
        rc2, out2, _ = run_oc(oc, ["view", f, "issues", "--limit", "10"])
        if rc2 == 0 and out2.strip():
            print("  📋 格式问题提示（不影响交付，供参考）：")
            for line in out2.strip().splitlines():
                print(f"     {line}")

    print("✅ 美化完成（未改动任何字体规范）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
