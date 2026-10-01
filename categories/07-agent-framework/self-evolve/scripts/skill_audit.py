#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skill_audit.py —— 用户级技能库结构化审计器（self-evolve 技能自带，纯标准库）

能力：
  1. 失效引用扫描：支持中文路径；分类为 broken / cross_skill / placeholder / runtime_zip / runtime_ignored / suspect
  2. 空 scripts/references/assets/templates 目录检测
  3. 孤儿 references 文件检测（全库文本无引用）
  4. frontmatter 合规（name / description / agent_created）
  5. 新增技能增量识别（与 .scan_state.json 基线 diff，重点审计其断链）

输出：
  默认：人类可读文本（向后兼容原 scan_refs.py 布局 + 新增分类/增量标注）
  --json：机器可读报告，供自动化判定 HEALTHY / NEEDS ATTENTION / CRITICAL ISSUES

设计原则：
  - 保守判定：任何无法 100% 自证为真实断链的命中，降级为 suspect/placeholder/cross_skill/runtime_*，
    绝不贸然判 CRITICAL，避免自动化误报。
  - 真实 broken（全局不存在 + 非跨技能 + 非占位符 + 非运行时/设计态）才是 CRITICAL 候选。
  - 文档示例（行内反引号 / fenced code block / 占位符特征 / 隐藏与运行时文件）一律不计入断链。
"""
import os
import re
import io
import sys
import json
import argparse
import hashlib
import datetime

SKILLS_ROOT = os.path.expanduser(r"~/.workbuddy/skills")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, ".scan_state.json")
SUBDIRS = ("scripts", "references", "assets", "templates")

# 引用路径：允许英文 + 中文 + 常见路径字符
REF_RE = re.compile(r"(?:references|scripts|assets|templates)/[A-Za-z0-9_\-./\u4e00-\u9fff]+")
# fenced code block：用于定位代码块区间
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
# 占位符 / 模板 / 文档示例特征
PLACEHOLDER_HINTS = (
    "<", "your_", "your-", "xxx", "example", "示例", "模板", "template",
    "placeholder", "待替换", "待填", "todo", "path/to", "___",
    "文件名", "占位", "待", "你的", "run.py", "icon.png",
)


def read_text(path):
    try:
        return io.open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""


def list_skills(root):
    if not os.path.isdir(root):
        return []
    return sorted([s for s in os.listdir(root) if os.path.isdir(os.path.join(root, s))])


def fence_spans(text):
    """返回所有 fenced code block 的 (start, end) 区间。"""
    return [(m.start(), m.end()) for m in FENCE_RE.finditer(text)]


def in_fence(spans, start, end):
    for s, e in spans:
        if s <= start and end <= e:
            return True
    return False


def in_inline_code(text, start, end):
    """命中是否被单个反引号包裹（行内代码，通常是文档示例而非真实路径）。"""
    if start > 0 and end < len(text) and text[start - 1] == "`" and text[end] == "`":
        return True
    return False


def skill_md_files(skill_dir):
    """返回该技能下应被扫描引用路径的文件：SKILL.md + references/*.md。"""
    files = []
    sm = os.path.join(skill_dir, "SKILL.md")
    if os.path.exists(sm):
        files.append(sm)
    refd = os.path.join(skill_dir, "references")
    if os.path.isdir(refd):
        for dp, _, fs in os.walk(refd):
            for f in fs:
                if f.endswith(".md"):
                    files.append(os.path.join(dp, f))
    return files


def classify_ref(root, skills, skill, ref, span, text):
    """
    对一个不存在于本技能内的引用 ref 进行分类。
    返回 (category, detail)
      broken          真实断链（全局不存在、非跨技能、非占位符、非运行时/设计态）
      cross_skill    指向其他技能目录内真实存在的文件（刻意跨技能引用）
      placeholder    占位符 / 模板 / 文档示例（代码块、行内反引号、含占位符特征）
      runtime_zip    技能声明 runtime.zip 解压前置，scripts/assets 缺失是设计态
      runtime_ignored 隐藏文件 / 运行时生成文件（如 .ingest_history.json），发布态缺失正常
      suspect        其余无法自证的命中，需人工核实
    """
    skill_dir = os.path.join(root, skill)
    # 1) 跨技能引用：其他技能目录内是否存在该相对路径
    base = ref.split("/", 1)[-1]
    for other in skills:
        if other == skill:
            continue
        cand = os.path.join(root, other, ref)
        if os.path.exists(cand) or os.path.exists(os.path.join(root, other, base)):
            return ("cross_skill", "指向技能 %s" % other)
    # 1.5) 隐藏 / 运行时生成文件：以 . 开头或 ingest_history 等，发布态缺失正常
    base_name = os.path.basename(ref.replace("\\", "/"))
    if base_name.startswith(".") or "ingest_history" in ref or ref.rstrip("/").endswith("_history"):
        return ("runtime_ignored", "隐藏/运行时生成文件，发布态缺失正常")
    # 2) 占位符 / 模板 / 文档示例
    spans = fence_spans(text)
    is_fence = in_fence(spans, span[0], span[1])
    low = ref.lower()
    if any(h in low for h in PLACEHOLDER_HINTS):
        return ("placeholder", "含占位符特征")
    if is_fence or in_inline_code(text, span[0], span[1]):
        return ("placeholder", "位于代码块/行内反引号内的示例")
    # 3) runtime.zip 设计态：技能声明了解压前置，且缺失路径属于 scripts/ 或 assets/
    sm_text = read_text(os.path.join(skill_dir, "SKILL.md"))
    if ("runtime.zip" in sm_text or "解压" in sm_text) and (
        ref.startswith("scripts/") or ref.startswith("assets/")
    ):
        return ("runtime_zip", "runtime.zip 解压前置，设计态缺失")
    # 4) 其余：真实断链候选
    return ("broken", "全局不存在且非跨技能/非占位符/非设计态")


def scan_skill(root, skills, skill):
    skill_dir = os.path.join(root, skill)
    sm = os.path.join(skill_dir, "SKILL.md")
    result = {
        "skill": skill,
        "missing_skill_md": not os.path.exists(sm),
        "broken_refs": [],
        "cross_skill_refs": [],
        "placeholder_refs": [],
        "runtime_zip_refs": [],
        "runtime_ignored_refs": [],
        "suspect_refs": [],
        "empty_dirs": [],
        "orphan_refs": [],
        "frontmatter": {},
    }
    if result["missing_skill_md"]:
        return result

    # --- 失效引用 ---
    seen = set()
    for fn in skill_md_files(skill_dir):
        text = read_text(fn)
        for m in REF_RE.finditer(text):
            ref = m.group(0).rstrip(".,;:)）、")
            if ref in seen:
                continue
            seen.add(ref)
            target = os.path.join(skill_dir, ref)
            if os.path.exists(target):
                continue
            cat, detail = classify_ref(root, skills, skill, ref, (m.start(), m.end()), text)
            entry = {"ref": ref, "file": os.path.basename(fn), "detail": detail}
            if cat == "broken":
                result["broken_refs"].append(entry)
            elif cat == "cross_skill":
                result["cross_skill_refs"].append(entry)
            elif cat == "placeholder":
                result["placeholder_refs"].append(entry)
            elif cat == "runtime_zip":
                result["runtime_zip_refs"].append(entry)
            elif cat == "runtime_ignored":
                result["runtime_ignored_refs"].append(entry)
            else:
                result["suspect_refs"].append(entry)

    # --- 空目录 ---
    for sub in SUBDIRS:
        p = os.path.join(skill_dir, sub)
        if os.path.isdir(p) and not [x for x in os.listdir(p) if x != "__pycache__"]:
            result["empty_dirs"].append(sub)

    # --- 孤儿 references 文件（全库文本无引用）---
    refd = os.path.join(skill_dir, "references")
    if os.path.isdir(refd):
        corpus = []
        for sk in skills:
            corpus.append(read_text(os.path.join(root, sk, "SKILL.md")))
            od = os.path.join(root, sk, "references")
            if os.path.isdir(od):
                for dp, _, fs in os.walk(od):
                    for f in fs:
                        if f.endswith(".md"):
                            corpus.append(read_text(os.path.join(dp, f)))
        corpus_text = "\n".join(corpus)
        for dp, _, fs in os.walk(refd):
            for f in fs:
                if not f.endswith(".md"):
                    continue
                stem = f[:-3]
                if (f in corpus_text) or (stem in corpus_text):
                    continue
                rel = os.path.relpath(os.path.join(dp, f), skill_dir).replace("\\", "/")
                result["orphan_refs"].append(rel)

    # --- frontmatter 合规 ---
    txt = read_text(sm)
    fm = ""
    if txt.startswith("---"):
        end = txt.find("\n---", 3)
        if end > 0:
            fm = txt[3:end]
    fm_flags = []
    if not re.search(r"^\s*name\s*:", fm, re.M):
        fm_flags.append("missing_name")
    if not re.search(r"^\s*description\s*:", fm, re.M):
        fm_flags.append("missing_description")
    if "agent_created" not in fm:
        fm_flags.append("no_agent_created")
    if not fm:
        fm_flags.append("no_frontmatter")
    result["frontmatter"] = {"flags": fm_flags, "has_frontmatter": bool(fm)}

    return result


def compute_hash(skill_dir):
    h = hashlib.md5()
    for fn in skill_md_files(skill_dir):
        h.update(fn.encode("utf-8"))
        h.update(read_text(fn).encode("utf-8"))
    return h.hexdigest()


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with io.open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"skills": {}}
    return {"skills": {}}


def save_state(state):
    try:
        with io.open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="用户级技能库结构化审计器")
    ap.add_argument("--root", default=SKILLS_ROOT, help="技能根目录")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON 报告")
    ap.add_argument("--no-update-state", action="store_true",
                    help="不更新 .scan_state.json 基线（仅查看增量）")
    args = ap.parse_args()

    root = os.path.expanduser(args.root)
    skills = list_skills(root)

    per_skill = [scan_skill(root, skills, sk) for sk in skills]

    state = load_state()
    prev = state.get("skills", {})
    new_skills = [sk for sk in skills if sk not in prev]

    broken_all = [(r["skill"], e) for r in per_skill for e in r["broken_refs"]]
    cross_all = [(r["skill"], e) for r in per_skill for e in r["cross_skill_refs"]]
    placeholder_all = [(r["skill"], e) for r in per_skill for e in r["placeholder_refs"]]
    runtime_all = [(r["skill"], e) for r in per_skill for e in r["runtime_zip_refs"]]
    runtime_ignored_all = [(r["skill"], e) for r in per_skill for e in r["runtime_ignored_refs"]]
    suspect_all = [(r["skill"], e) for r in per_skill for e in r["suspect_refs"]]
    empty_all = [(r["skill"], d) for r in per_skill for d in r["empty_dirs"]]
    orphan_all = [(r["skill"], d) for r in per_skill for d in r["orphan_refs"]]

    # frontmatter：真实问题（缺失 name/description/无 frontmatter）计入健康；
    # no_agent_created 仅对“新增技能”提示（存量第三方不刷屏）。
    fm_missing = [(r["skill"], r["frontmatter"]["flags"])
                  for r in per_skill
                  if any(f in r["frontmatter"]["flags"]
                         for f in ("missing_name", "missing_description", "no_frontmatter"))]
    third_party = [(r["skill"], r["frontmatter"]["flags"])
                   for r in per_skill
                   if "no_agent_created" in r["frontmatter"]["flags"] and r["skill"] in new_skills]

    critical = len(broken_all) + len(fm_missing)
    moderate = len(fm_missing) + len(suspect_all)
    if critical >= 2:
        health = "CRITICAL ISSUES"
    elif critical == 1 or moderate > 2:
        health = "NEEDS ATTENTION"
    else:
        health = "HEALTHY"

    report = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "skills_root": root,
        "skill_count": len(skills),
        "new_skills": new_skills,
        "health": health,
        "critical_count": critical,
        "moderate_count": moderate,
        "broken_refs": [{"skill": s, **e} for s, e in broken_all],
        "cross_skill_refs": [{"skill": s, **e} for s, e in cross_all],
        "placeholder_refs": [{"skill": s, **e} for s, e in placeholder_all],
        "runtime_zip_refs": [{"skill": s, **e} for s, e in runtime_all],
        "runtime_ignored_refs": [{"skill": s, **e} for s, e in runtime_ignored_all],
        "suspect_refs": [{"skill": s, **e} for s, e in suspect_all],
        "empty_dirs": [{"skill": s, "dir": d} for s, d in empty_all],
        "orphan_refs": [{"skill": s, "file": d} for s, d in orphan_all],
        "frontmatter_issues": [{"skill": s, "flags": fl} for s, fl in fm_missing],
        "third_party_no_flag": [{"skill": s} for s, _ in third_party],
        "per_skill": per_skill,
    }

    if args.json:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
    else:
        print("=== 技能库审计 ===")
        print("技能数: %d | 新增: %d | 健康结论: %s" % (len(skills), len(new_skills), health))
        if new_skills:
            print("\n[新增技能] " + ", ".join(new_skills))
        if broken_all:
            print("\n=== 真实断链 broken（CRITICAL 候选）===")
            for s, e in broken_all:
                print("  [%s] %s -> %s  (%s)" % (s, e["file"], e["ref"], e["detail"]))
        elif new_skills:
            print("\n（新增技能无真实断链）")
        if cross_all:
            print("\n=== 跨技能引用 cross_skill（合法，仅供参考）===")
            for s, e in cross_all:
                print("  [%s] %s -> %s  (%s)" % (s, e["file"], e["ref"], e["detail"]))
        if placeholder_all:
            print("\n=== 占位符/模板/示例引用 placeholder（忽略）===")
            for s, e in placeholder_all:
                print("  [%s] %s -> %s  (%s)" % (s, e["file"], e["ref"], e["detail"]))
        if runtime_all:
            print("\n=== runtime.zip 设计态缺失（忽略）===")
            for s, e in runtime_all:
                print("  [%s] %s -> %s" % (s, e["file"], e["ref"]))
        if runtime_ignored_all:
            print("\n=== 隐藏/运行时文件（发布态缺失正常，忽略）===")
            for s, e in runtime_ignored_all:
                print("  [%s] %s -> %s" % (s, e["file"], e["ref"]))
        if suspect_all:
            print("\n=== 疑似断链 suspect（需人工核实）===")
            for s, e in suspect_all:
                print("  [%s] %s -> %s" % (s, e["file"], e["ref"]))
        if empty_all:
            print("\n=== 空目录 ===")
            for s, d in empty_all:
                print("  [%s] %s/ 为空" % (s, d))
        if orphan_all:
            print("\n=== 孤儿 references 文件（全库无引用，需核实）===")
            for s, d in orphan_all:
                print("  [%s] %s" % (s, d))
        if fm_missing:
            print("\n=== frontmatter 合规（真实问题）===")
            for s, fl in fm_missing:
                print("  [%s] %s" % (s, " | ".join(fl)))
        if third_party:
            print("\n=== 新增第三方技能未带 agent_created（按规则不自动补，待确认）===")
            print("  " + ", ".join(s for s, _ in third_party))

    if not args.no_update_state:
        new_state = {"skills": {}}
        for sk in skills:
            new_state["skills"][sk] = compute_hash(os.path.join(root, sk))
        save_state(new_state)

    return 0


if __name__ == "__main__":
    sys.exit(main())
