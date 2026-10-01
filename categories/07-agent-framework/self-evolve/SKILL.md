---
name: self-evolve
description: >
  智能体自动进化技能（WorkBuddy 原生适配版）。两种模式：
  (1) 每日进化升级（默认/定时触发）——审计用户级技能(~/.workbuddy/skills)、SOUL.md/USER.md/IDENTITY.md、
  memory 与工作区引用，发现失效引用、事实错误、触发重叠、陈旧/弱化规则、冗余技能，并修复或上报；
  (2) 经验沉淀——把成功的多步工作流固化为可复用技能(SKILL.md)。
  触发词：自我进化、self-evolve、进化、每日进化、evolution upgrade、config health check、audit config、沉淀技能。
  NOT for：修复具体代码 bug（用通用修复流程）、诊断运行时崩溃。
argument-hint: scope-or-focus-area
agent_created: true
---

ultrathink。本技能让智能体"越用越聪明"：定期审计并升级自身配置（技能/记忆/规则），并把可复用的工作流沉淀为技能。

> 来源：改编自 GitHub 公开技能 `majiayu000/claude-skill-registry`(self-evolve) 与 `jiayaoqijia/Ottie`(meta/self-evolve)。
> 已去除原版对 Claude Code `.claude/hooks/self-improve` 提案库的依赖，改为直接读写技能文件与 memory。

## 模式判定

- 当 scope 为 `full` / `skills` / `rules` / `memory` / `quick`，或定时自动化触发、或 `(none)` 且无待处理沉淀任务 → 进入 **每日进化升级模式（审计）**。
- 当刚刚完成一个非平凡任务（多步流程、一次性脚本、API/工具新用法），或用户说"沉淀技能"/"存成技能" → 进入 **经验沉淀模式**。

---

## 模式 A：每日进化升级（审计）

目标：让智能体的技能库与记忆长期保持准确、无冗余、无失效引用。分 5 个阶段。**自动化运行时必须非交互、只做安全修复并写日志；交互运行时可询问用户。**

> 执行前先读取 `references/audit-guide.md`：内含可执行检查清单、严重度判定规则与本机受管运行时路径。

### Phase 1: 了解现状

1. 列出用户级技能：`ls ~/.workbuddy/skills/`（每个子目录即一个技能，需含 SKILL.md）。
2. 读取身份与记忆文件：
   - `~/.workbuddy/SOUL.md`、`~/.workbuddy/USER.md`、`~/.workbuddy/IDENTITY.md`
   - 当前工作区 `.workbuddy/memory/MEMORY.md` 与当日 `YYYY-MM-DD.md`
3. 读取每个技能 SKILL.md 的 frontmatter（name / description / triggers / agent_created）与正文，记录其声明的触发词与引用的脚本/参考文件路径。

### Phase 2: 分析（检查维度）

逐项扫描，记录问题并标注严重度：

| 维度 | 检查内容 | 常见信号 |
|------|----------|----------|
| 失效引用 | SKILL.md 中 `references/`、`scripts/`、`assets/` 路径是否真实存在 | 文件不存在的链接 |
| 事实错误 | 工具名/命令/路径/版本是否与当前环境一致 | 引用了不存在的工具或错误路径 |
| 触发重叠 | 多个技能 frontmatter 触发词高度重叠 | 同一句话会同时命中 2+ 技能 |
| 陈旧内容 | 提及已废弃的能力/接口/约定 | "用 xxx 工具"但工具已改名 |
| 弱化/冗余 | 技能之间内容大量重复、或同一逻辑散落多处 | 2 个技能做同一件事 |
| 缺失 frontmatter | 无 `name`/`description` 或 `agent_created` 标记 | 不符合 WorkBuddy 规范 |

### Phase 3: 修复

- **严重度**：CRITICAL（错误命令/失效引用/会误导） → 修复；MODERATE（次优输出） → 容易修则修；LOW（风格） → 仅上报。
- 修复手段：用 Edit/Write 直接改技能文件或 memory 文件。**只做就地安全修改，不删除技能、不重命名、不大幅改写能正常工作的技能。**
- 自动化运行时（非交互）：**不要新建技能、不要重命名、不要改写正常技能**；只执行明显安全的就地修复（如修正一个确认失效的相对路径），其余一律作为"建议"写入 memory 的当日日志，等用户确认。
- 若一次修复需要新增 50+ 行，改为写一条"建议"上报，不 inline 硬塞。

### Phase 4: 验证

对每个修改：重新读取该文件，确认引用可解析、frontmatter 合法、未引入新的失效引用。

### Phase 5: 报告与记录

输出健康结论（三选一）：
- **HEALTHY**：0 个 CRITICAL，≤2 个 MODERATE。
- **NEEDS ATTENTION**：有未修复的 MODERATE，或 1 个 CRITICAL。
- **CRITICAL ISSUES**：≥2 个 CRITICAL。

报告模板：
```
## 每日进化升级报告 <日期>
- 审计范围：<skills / memory / 全部>
- 健康结论：<HEALTHY | NEEDS ATTENTION | CRITICAL ISSUES>
- 已修复：<条目 + 文件 + 改动>
- 待用户确认的建议：<条目>
- 下一步：<可选>
```
并把报告追加到工作区 `.workbuddy/memory/YYYY-MM-DD.md`（作为进化日志），便于跨会话追踪。

---

## 模式 B：经验沉淀

当一个非平凡任务完成后，判断是否该沉淀为技能：

- 是否从零写了一个多步工作流？
- 是否写了可复用的脚本？
- 是否摸清了一个不显然的 API/工具模式？
- 用户是否之前问过类似的事？

若命中，且当前为交互模式：询问用户"要把这个做法存成可复用技能吗？"。用户同意后：

1. 在 `~/.workbuddy/skills/<name>/SKILL.md` 创建极简技能：
   ```markdown
   ---
   name: <short-name>
   description: "<它做什么、何时用>"
   agent_created: true
   ---
   # <标题>
   <智能体复现该工作流所需的精炼指令>
   ```
2. 若涉及脚本，存到 `~/.workbuddy/skills/<name>/scripts/`。
3. 保持最小：只写智能体自己无法推断的内容，避免与现有技能重叠。

> 自动化（每日进化）模式下**不主动新建技能**，只在 Phase 3 把"建议沉淀"写入进化日志。

---

## 约束

- **守好边界**：只管配置质量与技能沉淀。不修代码 bug、不做项目业务逻辑。
- **修坏的，不修好的**：尊重知识分层——技能教方法、记忆存上下文、身份文件定人格。
- **别膨胀**：合并时让文件更紧凑，而不是更长。
- **合并不弱化**：合并后的版本至少要和原版一样强。
- **安全优先（自动化）**：非交互运行时，宁可上报也不冒险改写；任何会删除/重命名/大改的操作都必须留给用户确认。
