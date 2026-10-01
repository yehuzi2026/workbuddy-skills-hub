# 审计清单（WorkBuddy 适配）

本文件为 self-evolve 技能「每日进化升级模式」提供可执行的检查清单与判定规则。

## 0. 前置

- 用户级技能根目录：`~/.workbuddy/skills/`
- 身份文件：`~/.workbuddy/SOUL.md`、`USER.md`、`IDENTITY.md`
- 工作区记忆：`<workspace>/.workbuddy/memory/MEMORY.md` 与 `YYYY-MM-DD.md`
- 受管运行时：Python `C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe`；Node `C:/Users/Administrator/.workbuddy/binaries/node/versions/22.22.2/node.exe`

## 1. 失效引用检查

对每个技能 SKILL.md 正文里出现的相对路径（如 `references/audit-guide.md`、`scripts/run.py`、`assets/icon.png`）：
- 解析为 `~/.workbuddy/skills/<skill>/<path>`；
- 用 `ls` / Read 确认存在；不存在即记 CRITICAL（失效引用）。

## 2. frontmatter 合规性

合法 frontmatter 必须含：`name`、`description`。用户创建的技能建议带 `agent_created: true`。
- 缺失 `name`/`description` → MODERATE；
- 触发词与另一技能高度重叠（如都声明"标书/投标"）→ MODERATE（重叠会抢触发）。

## 3. 工具/命令事实核查

扫描技能中出现的工具名与命令，对照本环境真实可用项：
- 真实存在的工具/连接器：github、tencent-docs、Skill(fetch/find-skills) 等；
- 不存在或已改名的工具名（如原版提到的 `SkillManage` 在此环境通过 Write/Edit 直接操作技能文件实现）→ 标注 MODERATE，提示改写为直接文件操作。

## 4. 陈旧/冗余

- 同一个工作流在 2+ 技能里重复实现 → MODERATE，建议合并；
- 技能正文引用了 Claude Code 专属路径（`.claude/`、`CLAUDE.md`）而本环境无对应物 → MODERATE，改写为 WorkBuddy 等价路径。

## 5. 严重度与处置

| 严重度 | 示例 | 自动化(非交互) | 交互 |
|--------|------|----------------|------|
| CRITICAL | 失效引用、会误导的命令 | 仅当路径可 100% 确认修正时就地改；否则上报 | 改或询问 |
| MODERATE | 重叠触发、陈旧路径、缺 frontmatter | 上报为"建议" | 容易修则修 |
| LOW | 措辞/风格 | 仅上报 | 仅上报 |

## 5.1 新增技能增量监控（每日自动化重点）

扫描器 `scripts/skill_audit.py` 自带增量识别：与 `.scan_state.json` 基线 diff，输出
`new_skills`（上次扫描后新安装的技能）。**新增技能是真实断链的高发区**（发布时目录改名而
脚本名未同步、引用名拼写不一致——08-07 的 xiaohongshu-similar-account 即此类），每日进化
自动化须对 `new_skills` 重点审计：
- 其 `broken_refs` 一律置顶报告；
- 命中 broken → 作为「待确认建议」上报，并提示「回复技能名/编号即可触发 skill-patch 补建」；
- 自动化（非交互）不自动补建，严守安全优先。

扫描器输出：默认人类可读文本；`--json` 供自动化判定 `health`（HEALTHY / NEEDS ATTENTION /
CRITICAL ISSUES）。分类保守：
`broken`（真实断链）/ `cross_skill`（跨技能，合法）/ `placeholder`（占位符/示例，忽略）/
`runtime_zip`（runtime.zip 解压前置，设计态）/ `runtime_ignored`（隐藏/运行时文件，忽略）/
`suspect`（需人工）。仅 `broken` + 缺失 name/description 计入 critical。

## 5.2 缺失脚本补建流程（与 skill-patch 协作）

当审计确认某技能存在 broken（缺失脚本/资源）且用户点名（如「C1」/技能名）后，加载
`skill-patch` 技能执行「引用→契约→测试」补建。要点（详见 skill-patch/SKILL.md）：
1. 定位缺失项（grep 引用点 + 行号）；
2. 提取契约（读 SKILL.md 上下文 + 对应 references 章节，**切忌臆造**）；
3. 探测本机后端（DOCX→PDF 优先 Word COM；OOXML 优先 stdlib，不依赖 python-docx）；
4. 零依赖实现 + 语义化退出码 + 资源释放（防 WINWORD 残留）+ 中文路径测试；
5. 双向测试（合规 exit 0 / 违规 exit 非0 且精准定位 / 转换类验证 PDF 完整）；
6. 跑 `skill_audit.py --json` 确认不再命中 broken（扫描闭环）；
7. 写当日进化日志。

## 6. 报告模板

```
## 每日进化升级报告 <YYYY-MM-DD>
- 审计范围：<...>
- 健康结论：<HEALTHY | NEEDS ATTENTION | CRITICAL ISSUES>
- 已修复：<条目 · 文件 · 改动>
- 待确认建议：<条目>
- 下一步：<可选>
```

报告须追加进 `<workspace>/.workbuddy/memory/YYYY-MM-DD.md`。
