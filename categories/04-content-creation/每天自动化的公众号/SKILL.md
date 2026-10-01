---
name: "每天自动化的公众号"
description: "微信公众号每日自动化运营系统。覆盖：战略框架(数量→收益→志同道合)、P1/P2/P3 北极星、流量优先内容策略、SEO 标题、三个涨粉钩子、以及【30篇/天·API自动存草稿·用户发布】的可运行流水线（gen_articles.py 调智谱GLM-4-flash 三段拼接生成 + save_drafts_api.py 走公众号草稿箱API，完全不依赖浏览器、绕过 browser-act 安全闸）。当用户要搭 AI 自动写公众号、做日更系统、配置写稿自动化、用数据优化涨粉时使用。"
agent_created: true
---

# 每天自动化的公众号

把公众号运营做成「每天定时自动写稿 + 自动存草稿 + 自动复盘优化」的可运行系统，而不是一篇篇手工写。

> 本 skill 定义「怎么搭、怎么跑、踩过哪些坑」。配套脚本在 `scripts/`，经验库起步模板在 `references/经验库模板.md`，战略细节在 `references/strategy.md`。

---

## 0. 适用场景与前置条件

**适用**：订阅号 / 服务号，想用 AI 每日自动产出文章并持续用数据优化涨粉。
**前置**：
- 公众号后台账号（mp.weixin.qq.com），知道 AppID / AppSecret（存于 `~/.workbuddy/zhipu_config.json` 同目录的凭据，或本 skill 脚本里硬编码的 wxb244d16ead2a7bda）
- **智谱 AI API Key**（GLM-4-flash，已验证可用；模型单段输出硬顶≈550字，故用三段拼接凑 1500–2000 字）
- Python 3.10+（跑生成器与存稿脚本，用 WorkBuddy 隔离 python venv）
- 公众号已**实名 + 设头像名称**（否则草稿都存不进后台）

**硬约束（任何号都绕不开）**：
- 订阅号每天仅 1 次群发 → 每日 30 篇只有 1 篇能推送给粉丝，其余靠搜一搜/分享获取流量
- **未实名验证** → 连草稿都存不进后台（保存会跳 `personverify` 页）
- 新号（0 粉）发文默认曝光≈0，瓶颈在**分发**不在内容

---

## 1. 战略框架（最重要，先定再干）

目标函数执行次序：**先冲粉丝数量 → 数量带来收益 → 收益后再谈志同道合**。

| 阶段 | 北极星指标 | 内容策略 |
|---|---|---|
| **P1 冷启动**（0→500 粉） | 净增粉丝数 | 每日 30 篇全做流量内容冲数量，立场/筛人内容暂缓 |
| **P2 变现**（500 粉+） | 收益额 / 单粉产出 | 开流量主 + 商单，「数量→收益」自然发生 |
| **P3 志同道合**（收益后） | 同频粉占比 / 取关率 < 2% | 才做筛人、收窄定位、精准私域 |

> 11 个细分赛道全覆盖：金融热点 / 哲学思想 / 实用文章 / 养生 / 中医 / 风水 / 易学学习 / 学习技巧 / 方法论 / 管理学 / 公司运营 + 其他热门。按**当日热点灵活分配**（哪类有热点多写哪类），不强制均分。

---

## 2. 内容策略（写稿必须遵守）

- **流量优先**：当前阶段 30 篇全做追热点拉新的流量内容，不做立场/筛人内容。
- **SEO 标题**：标题必须含 1 个真实会被搜索的词，句式 `核心搜索词 + 冲突/悬念`，≤30 字。
- **三个涨粉钩子（每篇必带）**：身份钩子（开头"如果你也是那种…的人"）+ 关注钩子（文末给具体关注理由，禁写"点个关注吧"）+ 互动钩子（文末提易答问题引导留言）。
- **结构**：1500–2000 字（glm-4-flash 三段拼接达成），强钩子开头、彩色小标题、金句高亮、免责声明（养生/中医类必加"不替代医生诊断"，风水/易学类必加"仅供参考"）。
- **评级（按涨粉非阅读）**：🔥爆款 / ✅良好 / ⚪平稳 / ❌扑街 / ⚠️无效流量。

---

## 3. 每日自动化配置（30篇/天 · API 存草稿 · 用户发布）

**写稿自动化（建议每天 09:00）**：
1. 联网抓当日各赛道热榜（WebSearch 11 个赛道），选 30 个流量选题，更新 `topics.json`
2. 跑 `gen_articles.py` → 在 `每日产出/YYYY-MM-DD/articles/` 生成 30 篇 HTML + meta.json + manifest.json
3. 跑 `save_drafts_api.py --date YYYY-MM-DD` → 经公众号草稿箱 API 存入后台草稿箱（增量+断点续存，已存的跳过）
4. **铁律：只存草稿，绝不自动群发/发表**，发布由用户手动在后台完成

**复盘自动化（建议每天 21:00）**：
1. 抓后台数据 → 跑 `scripts/analyze_stats.py` 出 analysis JSON
2. 更新经验库，输出次日选题建议

> ⚠️ **发布分工**：AI 负责「写 + 存草稿」，用户负责「选封面 + 群发确认」。封面需用户手动选（微信封面走自有素材管理器，模拟上传会被静默拒绝）；群发受 browser-act 230331 安全闸保护，需用户本人过点闸。

> ⚠️ **rrule 时区**：系统按**本地时间**解释 BYHOUR（实测 BYHOUR=21→本地 21:25，非 UTC）。`automation_update` 的 nextRunAt 是旧 rrule 缓存不可信，以 rrule + UI 显示为准。

---

## 4. 存草稿流水线（API 路线，绕开浏览器）

**为什么走 API 而非 browser-act**：browser-act 受 230331 安全闸限制（Allow Full Access 会随机掉权限），且封面/群发等敏感操作本就需用户过点闸。草稿箱 API（`cgi-bin/draft/add`）用 AppSecret 直接调，**完全不碰浏览器**，30 篇/天更稳更快。

**链路**：`get_token` → `material/add_material` 上传封面拿 `thumb_media_id` → 逐篇 `draft/add` → 校验返回 `media_id`。

**关键脚本**：
- `gen_articles.py`：调智谱 GLM-4-flash，三段拼接（每段 `chat_min` 重试到≥400字）凑 1500–2000 字，统一渲染成公众号 inline-style HTML。用法：`python gen_articles.py`（读 `topics.json`，写 `每日产出/YYYY-MM-DD/articles/`）。
  - ⚠️ 标题解析兼容 `#TITLE:` / `# 标题：` / markdown 一级标题 `# xxx` / 全角冒号，空时兜底到首行或 SEO；见 `render_html`。
  - ⚠️ 目录用 `datetime.date.today()`，跨天补存必须 `--date YYYY-MM-DD`。
- `save_drafts_api.py`：读 `articles/*.html` + `*.meta.json`（或 manifest），逐篇 `draft/add`。用法：`python save_drafts_api.py [--date YYYY-MM-DD] [--cover /path.png]`。
  - 增量：`.saved_idx.json` 记录已存编号，已存的跳过，不怕中断。
  - 封面缓存：`.cover_media_id` 文件，首次上传后复用。

**断点续存工作流**（曾因跨天会话丢失后台进程，需手动补）：
1. 若只生成未存完：直接重跑 `save_drafts_api.py --date <生成日>`（增量跳过已存）
2. 单篇失败（`empty content` 44004 多为 title 空）：单独 `gen_one` 重生成该篇 → 单独 `draft_add`
3. 核验：分页 `draft/batchget`（**单次 count 上限 20，需分页**），标题在 `content.news_item[0].title`

---

## 5. 关键踩坑（必读，省几天命）

1. **实名验证阻断一切**：未实名时存草稿跳 `personverify` 页。闭环（写稿→发布）要等认证通过。
2. **browser-act 230331 安全闸**：敏感操作（群发确认、Allow Full Access 随机掉）需用户过点闸 → **改用草稿箱 API 绕开**，发布仍留用户手动。
3. **GLM-4-flash 单段输出硬顶≈550字**：必须三段拼接（build_part 1/2/3），每段 `chat_min` 重试到≥400字，否则总字数不达标。
4. **标题解析必须 robust**：模型常输出 `# 标题：`(全角冒号)或 markdown `# xxx`，只用 `#TITLE:` 会丢标题→空 title→`draft/add` 报 44004。已加多写法兼容+兜底。
5. **跨天目录陷阱**：`gen_articles.py`/`save_drafts_api.py` 默认用 `today()`；今天生成、明天存会找不到目录 → 一律显式 `--date`。
6. **draft/batchget count 上限 20**：验证时必须分页（offset 0/20/40）拉全，否则只看到前 20 条误判缺失。
7. **batchget 标题路径**：`content.news_item[0].title`（content 是嵌套 dict，不是直接 title 字段）。

---

## 6. 配套脚本

- `gen_articles.py`：30 篇生成器（GLM-4-flash 三段拼接 + 统一 HTML 渲染 + 免责声明）。
- `save_drafts_api.py`：批量存草稿（增量+断点，API 路线）。
- `scripts/fetch_stats.js`：后台首页提取 homeStats（总用户数/昨日阅读/分享/新增关注）。
- `scripts/analyze_stats.py`：读 raw JSON 按涨粉北极星出 analysis JSON。

---

## 7. 复盘归因看板字段（每篇文章必记）

标题 / 选题类型 / 内容属性（流量/立场）/ SEO 主词与长尾 / 字数 / 阅读 / 分享 / 在看 / **涨粉** / **涨粉率** / 评级。

---

*本 skill 沉淀自「初心杂谈的碎碎念」公众号从 0 粉冷启动、目标 500 粉、日更 30 篇的完整搭建实践（2026-08）。*
