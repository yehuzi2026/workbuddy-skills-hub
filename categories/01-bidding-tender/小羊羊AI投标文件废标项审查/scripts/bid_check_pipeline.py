#!/usr/bin/env python3
"""
bid_check_pipeline.py — 废标项自动化审查流水线（v5.1.0）
========================================================

全自动流程：A(解析招标文件) → B(固定格式diff) → C1(目录比对) →
C2(逐项扫描) → C3(专项名前穷举) → D(综合判定) → 输出报告

使用方式（一键启动）：
    python bid_check_pipeline.py <招标文件第一册.md> <招标文件第二册.md> <投标文件.md> [选项]

    必选参数：
        招标文件第一册.md   - 招标文件通用部分
        招标文件第二册.md   - 招标文件专用部分
        投标文件.md         - 投标响应文件
    
    选项：
        --output-dir DIR    - 输出报告存储目录（默认：当前目录/reports/）
        --skip-ocr          - 跳过OCR图片检测（默认：不跳过）
        --verbose           - 输出详细中间结果
        --project NAME      - 项目名称（自动从招标文件提取，如提取失败可手动指定）

输出产物：
    report_D.json           - 结构化判定数据
    report_D.md             - 可读审查报告
    report_D.pdf            - 封面目视化报告（需安装fpdf2）
"""

import sys
import os
import json
import subprocess
import re
from datetime import datetime
from pathlib import Path

# ============================================================
# 工具函数
# ============================================================

def eprint(*args, **kwargs):
    """输出到 stderr（不影响stdout的JSON输出）"""
    print(*args, file=sys.stderr, **kwargs)

def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)

def script_path(name):
    """获取技能脚本的绝对路径"""
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(skill_dir, name)

# ============================================================
# 流水线各阶段
# ============================================================

class Pipeline:
    """自动审查流水线——按A→B→C1→C2→C3→D顺序执行"""

    def __init__(self, tender_book1, tender_book2, bid_file, output_dir, skip_ocr=False, verbose=False):
        self.tender_book1 = tender_book1
        self.tender_book2 = tender_book2
        self.bid_file = bid_file
        self.output_dir = output_dir
        self.skip_ocr = skip_ocr
        self.verbose = verbose
        self.python = sys.executable if sys.executable else "python"
        self.results = {}
        self.project_meta = self._extract_project_meta()

    def _extract_project_meta(self):
        """从招标文件提取项目元数据（不需要外部脚本）"""
        meta = {
            "project_name": "未识别",
            "project_no": "未识别",
            "bid_deadline": "未识别",
            "validity_period": "未识别",
        }
        # 从第二册提取
        if os.path.exists(self.tender_book2):
            text2 = open(self.tender_book2, "r", encoding="utf-8").read()
            m = re.search(r'项目编号[：:]\s*(\S+)', text2)
            if m: meta["project_no"] = m.group(1)
            m = re.search(r'项目名称[：:]\s*(.+?)(?:\n|$)', text2)
            if m: meta["project_name"] = m.group(1).strip()
            m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日\d{1,2}:\d{2})', text2)
            if m: meta["bid_deadline"] = m.group(1)
            m = re.search(r'报价有效[期后]\s*(\d+)\s*[日天]', text2)
            if m: meta["validity_period"] = m.group(1)
        return meta

    def _run_script(self, script_name, args, description):
        """运行一个子模块脚本并捕获输出"""
        script = script_path(script_name)
        if not os.path.exists(script):
            eprint(f"[{timestamp()}] WARNING: 脚本不存在，跳过: {script_name}")
            return None
        
        # 设置环境变量避免GBK编码报错
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        cmd = [self.python, script] + args
        eprint(f"[{timestamp()}] >> 模块: {description}")
        if self.verbose:
            eprint(f"   命令: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, capture_output=True, encoding='utf-8', timeout=300, env=env)
            if result.returncode != 0:
                eprint(f"    >> 失败 (rc={result.returncode})")
                if result.stderr.strip():
                    eprint(f"   错误: {result.stderr.strip()[:500]}")
                return None
            # 尝试解析JSON输出
            output = result.stdout.strip()
            if output.startswith("{"):
                return json.loads(output)
            # 尝试从文件读取
            for out_arg in args:
                if out_arg.startswith("--output") and "=" in out_arg:
                    out_path = out_arg.split("=", 1)[1]
                    if os.path.exists(out_path):
                        with open(out_path, "r", encoding="utf-8") as f:
                            return json.loads(f.read())
            eprint(f"   ✅ 完成 (无JSON输出)")
            return {"status": "completed", "stdout": output[:200]}
        except subprocess.TimeoutExpired:
            eprint(f"    ❌ 超时（300秒）")
            return None
        except json.JSONDecodeError:
            eprint(f"   ⚠️  输出不是有效JSON，使用文本结果")
            return {"status": "completed", "raw_output": result.stdout[:500]}
        except Exception as e:
            eprint(f"    ❌ 异常: {e}")
            return None

    # ---- 阶段A：解析招标文件 ----
    def run_module_a(self):
        """双扫描：全章节理解 + 关键词触发"""
        eprint(f"\n{'='*60}")
        eprint(f"[{timestamp()}] 🅰 模块A：招标文件解析器")
        eprint(f"="*60)

        # A.1 提取固定格式模板
        output = os.path.join(self.output_dir, "module_a_templates.json")
        self.results["a_templates"] = self._run_script(
            "bid_template_extractor.py",
            [self.tender_book1, "--output", output],
            "A.1 固定格式模板提取"
        )

        # A.2 关键词扫描
        output = os.path.join(self.output_dir, "module_a_keywords.json")
        self.results["a_keywords"] = self._run_script(
            "bid_keyword_scanner.py",
            [self.tender_book1, self.tender_book2, "--output", output],
            "A.2 关键词触发扫描"
        )

    # ---- 阶段B：固定格式全量diff ----
    def run_module_b(self):
        """13类字段+第14类落款区全量文字diff"""
        eprint(f"\n{'='*60}")
        eprint(f"[{timestamp()}] 🅱 模块B：固定格式全量diff")
        eprint(f"="*60)

        templates_json = os.path.join(self.output_dir, "module_a_templates.json")
        if not os.path.exists(templates_json):
            eprint("   ⚠️  模板数据未就绪，跳过模块B")
            return

        output = os.path.join(self.output_dir, "module_b.json")
        self.results["module_b"] = self._run_script(
            "bid_diff_engine.py",
            [templates_json, self.bid_file, "--output", output],
            "B 全量逐字符diff（含13类+第14类落款区）"
        )

    # ---- 阶段C1：目录比对 ----
    def run_module_c1(self):
        """目录结构比对"""
        eprint(f"\n{'='*60}")
        eprint(f"[{timestamp()}] 🅲¹ 模块C1：目录比对")
        eprint(f"="*60)

        output = os.path.join(self.output_dir, "module_c1.json")
        self.results["module_c1"] = self._run_script(
            "bid_directory_check.py",
            [self.tender_book1, self.bid_file, "--output", output],
            "C1 目录结构逐项比对"
        )

    # ---- 阶段C2：逐项全文扫描 ----
    def run_module_c2(self):
        """全文扫描：报价要求、响应时间等"""
        eprint(f"\n{'='*60}")
        eprint(f"[{timestamp()}] 🅲² 模块C2：逐项全文扫描")
        eprint(f"="*60)

        output = os.path.join(self.output_dir, "module_c2.json")
        self.results["module_c2"] = self._run_script(
            "bid_price_calc.py",
            [self.bid_file, self.tender_book1, self.tender_book2,
             "--output", output],
            "C2 报价/响应时间/承诺声明审查"
        )

    # ---- 阶段C3：专项名称穷举 ----
    def run_module_c3(self):
        """专项名称全文穷举校验"""
        eprint(f"\n{'='*60}")
        eprint(f"[{timestamp()}] 🅲³ 模块C3：专项名称全文穷举")
        eprint(f"="*60)

        # 先构造terms.json
        terms = self._build_special_terms()
        terms_json = os.path.join(self.output_dir, "special_terms.json")
        with open(terms_json, "w", encoding="utf-8") as f:
            json.dump(terms, f, ensure_ascii=False, indent=2)

        ocr_flag = ["--ocr-dir", os.path.join(self.output_dir, "ocr")] if not self.skip_ocr else []
        output = os.path.join(self.output_dir, "module_c3.json")
        self.results["module_c3"] = self._run_script(
            "bid_term_exhaustive.py",
            [terms_json, self.bid_file] + ocr_flag + ["--output", output],
            "C3 专项名称全文穷举+交叉验证"
        )

    def _build_special_terms(self):
        """构建专项名称标准值字典"""
        terms = {
            "tender_terms": [],
            "bidder_terms": []
        }
        # 从招标文件提取
        for book_path in [self.tender_book1, self.tender_book2]:
            if not os.path.exists(book_path):
                continue
            text = open(book_path, "r", encoding="utf-8").read()
            # 项目名称
            m = re.search(r'项目名称[：:]\s*(.+?)(?:\n|$)', text)
            if m:
                terms["tender_terms"].append({"term_name": "项目名称", "standard_value": m.group(1).strip()})
            # 项目编号
            m = re.search(r'项目编号[：:]\s*(\S+)', text)
            if m:
                terms["tender_terms"].append({"term_name": "项目编号", "standard_value": m.group(1)})
            # 采购人
            m = re.search(r'采购[人方][名称：:]*\s*(.+?)(?:\n|$)', text)
            if m:
                terms["tender_terms"].append({"term_name": "甲方名称", "standard_value": m.group(1).strip()})
            # 投标有效期
            m = re.search(r'报价有效[期后]\s*(\d+)\s*[日天]', text)
            if m:
                terms["tender_terms"].append({"term_name": "投标有效期", "standard_value": m.group(1)})
            # 保证金
            m = re.search(r'保证金[金额：:]*\s*(\d[\d,.]*)\s*元', text)
            if m:
                terms["tender_terms"].append({"term_name": "保证金金额", "standard_value": m.group(1)})

        # 从投标文件提取投标单位信息
        if os.path.exists(self.bid_file):
            text = open(self.bid_file, "r", encoding="utf-8").read()
            # 投标公司名称
            m = re.search(r'供应商名称[（(].*?[)）][：:]\s*(.+?)(?:\n|$)', text)
            if not m:
                m = re.search(r'(山东[\u4e00-\u9fff]+科技[\u4e00-\u9fff]+)', text)
            if m:
                bidder_name = m.group(1).strip()
                terms["bidder_terms"].append({"term_name": "投标公司名称", "standard_value": bidder_name})

            # 法定代表人
            m = re.search(r'我\s*(.+?)\s*系\s*(.+?)\s*法定代表人', text)
            if not m:
                m = re.search(r'法定代表人[：:]\s*(\S+)', text)
            if m:
                terms["bidder_terms"].append({"term_name": "法定代表人姓名", "standard_value": m.group(1).replace("姓名","").strip()})

            # 授权代表
            m = re.search(r'委托代理人[：:]\s*(\S{2,4})', text)
            if m:
                terms["bidder_terms"].append({"term_name": "授权代表姓名", "standard_value": m.group(1).strip()})

        return terms

    # ---- 阶段D：综合判定 ----
    def run_module_d(self):
        """综合判定引擎：交叉验证 + 生成报告"""
        eprint(f"\n{'='*60}")
        eprint(f"[{timestamp()}] 🅳 模块D：综合判定引擎")
        eprint(f"="*60)

        # 收集各模块输出文件
        a_templates = os.path.join(self.output_dir, "module_a_templates.json")
        a_keywords = os.path.join(self.output_dir, "module_a_keywords.json")
        b_result = os.path.join(self.output_dir, "module_b.json")
        c_result = os.path.join(self.output_dir, "module_c1.json")
        c2_result = os.path.join(self.output_dir, "module_c2.json")
        c3_result = os.path.join(self.output_dir, "module_c3.json")

        output_md = os.path.join(self.output_dir, "report_D.md")
        output_json = os.path.join(self.output_dir, "report_D.json")

        self.results["module_d"] = self._run_script(
            "bid_report_generator.py",
            [a_templates, b_result, c_result,
             "--c2", c2_result,
             "--c3", c3_result,
             "--output-json", output_json,
             "--output-md", output_md],
            "D 综合判定+报告生成"
        )

    def run(self):
        """执行完整的审查流水线"""
        start_time = datetime.now()
        eprint(f"\n{'#'*60}")
        eprint(f"#  投标文件废标项自动化审查流水线 v5.1.0")
        eprint(f"#  启动时间: {timestamp()}")
        eprint(f"#  招标文件: {os.path.basename(self.tender_book1)}")
        eprint(f"#           + {os.path.basename(self.tender_book2)}")
        eprint(f"#  投标文件: {os.path.basename(self.bid_file)}")
        eprint(f"{'#'*60}\n")

        # ====== 强制事前清单 ======
        eprint("\n" + "!"*60)
        eprint("!!! 强制性事前清单 — 开始审查前必须逐项确认 !!!")
        eprint("!"*60)
        eprint("""
        在输出审查结论之前，必须确认以下项目全部完成。
        如果某一步依赖的子脚本运行失败，必须手动完成该步骤。

        步骤1: 提取招标文件全部固定格式附件
               → 是否已从第一册"第四部分 附件"提取了完整附件列表？  [  ]
               
        步骤2: 逐附件比对★附件的落款区文字
               → 是否已逐字比对每个★附件的落款区文字？         [  ]
               
        步骤3: 检查报价部分
               → 报价一览表是否有多个方案？                     [  ]
               → 公司名称是否正确？                             [  ]
               → 报价函日期是否早于投标截止时间？                [  ]
               
        步骤4: 检查★服务响应表
               → 每条响应程度标注是否与实际情况一致？            [  ]
               → 承诺值是否与招标要求一致？                     [  ]
               → 证明材料页码是否逐条填写完整？                  [  ]
               
        步骤5: 全文扫描模板复用痕迹
               → 是否存在其他项目的地名/人名/路径残留？          [  ]
               
        ⚠️ 以上任何一项未完成，审查结论不可信任！
        """)
        eprint("!"*60 + "\n")

        # 顺序执行各阶段
        self.run_module_a()     # 解析招标文件
        self.run_module_b()     # 固定格式diff
        self.run_module_c1()    # 目录比对
        self.run_module_c2()    # 逐项扫描
        self.run_module_c3()    # 专项名称穷举
        self.run_module_d()     # 综合判定

        # 汇总结果
        elapsed = (datetime.now() - start_time).total_seconds()
        eprint(f"\n{'='*60}")
        eprint(f"[{timestamp()}] 🏁 审查流水线完成")
        eprint(f"   耗时: {elapsed:.1f}秒")
        eprint(f"   输出目录: {self.output_dir}")

        # 输出快速上报表
        summary = self._generate_summary()
        summary_path = os.path.join(self.output_dir, "report_summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        eprint(f"   快速上报表: {summary_path}")
        eprint(f"\n📊 审查总览:")
        for item in summary.get("overview", []):
            eprint(f"   {item}")
        if summary.get("disqualification_count", 0) > 0:
            eprint(f"\n⛔ 发现 {summary['disqualification_count']} 项废标项！")
        else:
            eprint(f"\n✅ 未发现直接废标项")

        return summary

    def _generate_summary(self):
        """从各模块结果生成快速上报表"""
        summary = {
            "project": self.project_meta,
            "timestamp": timestamp(),
            "overview": [],
            "disqualification_count": 0,
            "warning_count": 0,
            "flags": []
        }

        # 检查模块B结果（固定格式diff）
        b = self.results.get("module_b", {})
        if b:
            diffs = b.get("differences_found", 0) if isinstance(b, dict) else 0
            if diffs > 0:
                summary["disqualification_count"] += diffs
                summary["overview"].append(f"⛔ 模块B: 固定格式发现 {diffs} 处差异 (P0)")
                summary["flags"].append({
                    "module": "B",
                    "severity": "P0",
                    "count": diffs,
                    "description": "固定格式文字与招标文件模板不一致"
                })
            else:
                summary["overview"].append("✅ 模块B: 固定格式通过")

        # 检查模块C1（目录比对）
        c1 = self.results.get("module_c1", {})
        if c1:
            missing = c1.get("missing_sections", []) if isinstance(c1, dict) else []
            if missing:
                summary["disqualification_count"] += len(missing)
                summary["overview"].append(f"⛔ 模块C1: 缺失 {len(missing)} 个章节")
                summary["flags"].append({
                    "module": "C1",
                    "severity": "P0",
                    "count": len(missing),
                    "description": "目录缺失必交章节",
                    "details": missing
                })
            else:
                summary["overview"].append("✅ 模块C1: 目录完整")

        # 检查模块C2（价格/响应时间）
        c2 = self.results.get("module_c2", {})
        if c2:
            issues = c2.get("issues", []) if isinstance(c2, dict) else []
            p0_count = sum(1 for i in issues if i.get("severity") == "P0") if issues else 0
            if p0_count > 0:
                summary["disqualification_count"] += p0_count
            summary["overview"].append(f"⛔ 模块C2: 发现 {len(issues)} 个问题 (含P0={p0_count})")

        # 检查模块C3（专项名称）
        c3 = self.results.get("module_c3", {})
        if c3:
            terms = c3.get("terms", []) if isinstance(c3, dict) else []
            fails = [t for t in terms if t.get("verdict") == "❌"]
            if fails:
                summary["warning_count"] += len(fails)
                for f in fails:
                    summary["overview"].append(f"⚠️ 模块C3: {f.get('term_name','?')} 存在不一致")
                    summary["flags"].append({
                        "module": "C3",
                        "severity": "P1",
                        "term": f.get("term_name"),
                        "description": "专项名称前后不一致"
                    })
            else:
                summary["overview"].append("✅ 模块C3: 专项名称一致")

        # 检查模块D判定结果
        d = self.results.get("module_d", {})
        if d:
            verdict = d.get("summary", {}).get("final_verdict", "") if isinstance(d, dict) else ""
            if "废标" in str(verdict) or "fail" in str(verdict).lower():
                summary["overview"].append(f"⛔ 模块D判定: {verdict}")
                summary["final_verdict"] = str(verdict)
            else:
                summary["overview"].append(f"✅ 模块D判定: {verdict}")
                summary["final_verdict"] = str(verdict)

        return summary


# ============================================================
# 命令行入口
# ============================================================

def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    tender_book1 = sys.argv[1]
    tender_book2 = sys.argv[2]
    bid_file = sys.argv[3]

    # 校验输入文件
    for f in [tender_book1, tender_book2, bid_file]:
        if not os.path.exists(f):
            print(f"错误：文件不存在 - {f}")
            sys.exit(1)

    # 解析选项
    output_dir = None
    skip_ocr = False
    verbose = False
    project_name = None

    i = 4
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--output-dir" and i + 1 < len(sys.argv):
            output_dir = sys.argv[i + 1]
            i += 2
        elif arg == "--skip-ocr":
            skip_ocr = True
            i += 1
        elif arg == "--verbose":
            verbose = True
            i += 1
        elif arg == "--project" and i + 1 < len(sys.argv):
            project_name = sys.argv[i + 1]
            i += 2
        else:
            i += 1

    if not output_dir:
        output_dir = os.path.join(os.getcwd(), "reports")
    ensure_dir(output_dir)

    if verbose:
        eprint(f"输入文件确认:")
        eprint(f"  第一册: {tender_book1} ({os.path.getsize(tender_book1)} bytes)")
        eprint(f"  第二册: {tender_book2} ({os.path.getsize(tender_book2)} bytes)")
        eprint(f"  投标书: {bid_file} ({os.path.getsize(bid_file)} bytes)")
        eprint(f"  输出目录: {output_dir}")

    # 启动流水线
    pipeline = Pipeline(
        tender_book1=tender_book1,
        tender_book2=tender_book2,
        bid_file=bid_file,
        output_dir=output_dir,
        skip_ocr=skip_ocr,
        verbose=verbose
    )

    summary = pipeline.run()

    # 最终输出JSON格式的审查摘要到stdout
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
