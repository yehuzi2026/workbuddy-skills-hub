---
name: 万磁王技能万事通
description: 本技能用于从 GitHub / Gitee 等仓库安全下载、审计并安装外部 Agent Skill（尤其标书、招投标、文档生成、自动化类技能）到本机用户级技能目录，使其可被 WorkBuddy 直接触发使用。当用户要求"从 GitHub 下载技能""安装/补装某某 skill""帮我装个标书技能""把 Gitee 上的 XX 技能拿下来""获取并适配外部技能""给 WorkBuddy 加个技能"时触发。覆盖仓库定位、安全审计（P0/P1/P2 分级）、WorkBuddy 格式适配（受管 venv、run_script.sh 包装器、中文乱码修复、`.claude` 路径改写）、依赖安装与验证全流程。
agent_created: true
---

# 万磁王技能万事通

从任意 Git 仓库把外部技能安全、干净地装到本机，并让它能用。本技能沉淀了"下载 → 审计 → 适配 → 安装 → 装依赖 → 验证"的完整流水线，专为 WorkBuddy on Windows 环境调优。

## 一、何时启用

- 用户说"从 GitHub/Gitee 下载/安装/补装某某技能""帮我装个标书技能""把那个 skill 拿下来""给 WorkBuddy 加个技能"等。
- 任何需要把外部仓库的 Agent Skill 安全落到本机并可用的场景。
- 本机已有的同类技能：`bid-writer-pro`、`bidwriter`、`bid-doc`、`tender-writer` 即按此流程安装。
- 已按此流程安装：`nuwa-skill`（女娲）、`darwin-skill`（达尔文）—— 2026-09-15。

## 二、总流程（六步，不可跳步）

1. 定位仓库
2. 下载到临时暂存区
3. 安全审计（强制，绝不静默安装）
4. 适配 WorkBuddy 格式
5. 安装到用户级目录
6. 装依赖 + 验证

## 三、步骤细则

### 步骤 1 — 定位仓库

- 用 WebSearch / WebFetch 找到目标仓库（GitHub 或 Gitee）。
- 确认两件事：**仓库 URL** 与**技能子目录**（技能多在仓库根，或在 `skills/<name>/`、`<repo>/<name>/` 下）。
- 首次回复用户时列出：来源仓库、技能目录、预计能力、是否需要 Python 依赖。

### 步骤 2 — 下载到临时暂存区

- 优先 `git clone --depth 1 <url>`（Gitee 同样支持 git clone）。
- **代理坑（高频）**：WorkBuddy 会给子进程注入 `http_proxy=http://127.0.0.1:<port>`，`git clone` 走该代理时 smart-http 握手被拒，报
  `fatal: unable to access '...': Empty reply from server`（而 `curl` 走同一代理可能返回 200，容易误判为"网络正常"）。
  处置：剥离代理重试，通常直连即通 ——
  `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY git clone --depth 1 <url>`
- 网络失败回退：下载 tarball / zip 解压；GitHub 镜像（如 `ghfast.top`）在本机实测常超时，优先直连。
- 落盘到临时目录（如 `WorkBuddy/tmp_xxx`），**不要直接克隆进技能目录**。
- 确认技能文件夹含 `SKILL.md`，并查看其顶层结构（scripts / references / templates / assets）。
- **先量体积再决定装什么**：`du -sh <repo>/* | sort -hr`。宣传物料（`promo/`、封面 png/gif、多语种 README）常占 80% 以上体积且与运行无关。

### 步骤 3 — 安全审计（强制，绝不静默安装）

- 扫描 `SKILL.md`、`scripts/`、`references/` 的高危模式（命令见 `references/audit_patterns.md`）。
- 风险分级：
  - **P0（高危）**：外发网络到未知地址、无提示删除工作区外文件、窃取/外传凭据 —— **强烈警告，必须用户明确确认才继续**。
  - **P1（需确认）**：会修改系统环境、全局 pip 安装、执行交互式命令 —— **告知用户并获得确认**。
  - **P2（安全）**：仅本地文件读写、本地脚本调用、纯提示词 —— 可直接继续。
- 本环境 `skills-security-check` 技能不可用，改用 `references/audit_patterns.md` 的 grep 命令手动审计。
- **区分"技能运行时脚本"与"仓库自带 CI"**：`.github/scripts/*`、`*.yml` workflow 属于仓库 CI（常含 `urllib` 访问 GitHub API、读 `GITHUB_TOKEN`），
  不会随技能运行 —— 判定 P2 并在安装时**直接排除 `.github/`**，不要误报成 P0。
- 逐个人读 `scripts/` 下的实际脚本源码，确认：网络目标是否为用户显式传入的 URL、写盘范围是否限于技能目录/输出目录。
- 审计结论必须写进给用户的回复。

### 步骤 4 — 适配 WorkBuddy 格式

- frontmatter 补 `agent_created: true`；`name` / `description` 含中文触发词。
- **`.claude` 路径改写（第三方技能常见）**：多数外部 skill 按 Claude Code 习惯把技能目录钉死成 `.claude/skills/`。
  装到 WorkBuddy 后需替换为 `~/.workbuddy/skills/`（含 `scripts/` 内 docstring 的示例路径）。
  - ⚠️ **必须甄别，不能无脑全局替换**：若该 skill 本身是「runtime 中立性审查」类工具（如 `darwin-skill`），
    其正文里的 `.claude/skills/` 往往是**审查规则/正则**（用来检测别人的 skill 是否绑死单一 runtime），
    **必须原样保留**。只改它假设**自身运行环境**的路径引用。甄别方法：看该行是"扫描/写入/执行某路径"（改）还是"grep 正则/审查标准"（留）。
- 若技能依赖本地虚拟环境（出现 `install.bat` / `run_script.bat` / `.venv/Scripts/python.exe`）：
  - **删除** `install.bat`、`install.py`（会创建本地 `.venv` 或向全局 pip 安装，污染系统）。
  - **新增** `run_script.sh` 包装器（模板见 `references/run_script_template.sh`），统一调用受管 venv 的 python。
  - 把 `SKILL.md` 内所有 `run_script.bat ` 替换为 `bash run_script.sh `，并改写"脚本调用方式"段落，说明受管 venv 路径。
- **体积裁剪**：只装技能运行实体 + 有价值的参考（`SKILL.md` / `scripts/` / `references/` / `templates/` / `examples/` / `README.md` / `LICENSE`），
  排除 `.git/`、`.github/`、`promo/`、封面大图、二维码、多语种宣传稿。
  实测（2026-09-15）：`nuwa-skill` 全量 67MB（含 .git 32MB）→ 裁后 2.5MB；`darwin-skill` 保留 assets/templates 后 5.2MB。
  裁完**必须做断链检查**：`grep -noE "assets/[^ )]+|templates/[^ )]+|references/[^ )]+|scripts/[^ )]+" SKILL.md` 对比实际安装的文件。
- **乱码修复**：中文 frontmatter 经 Edit 工具偶发被写成 U+FFFD 替换符（如"采购文件"变成 3 个替换符）。安装后用 Python 复查 `s.count("\uufffd")` 并精确替换（示例见 `references/audit_patterns.md`）。
- **多处改动优先整体重写**：同一文件要改 3 处以上时，用 `Read` 读全文 → `Write` 一次写回，别连发多个 Edit（见"四、复用坑速查"）。

### 步骤 5 — 安装到用户级目录

- 复制到 `~/.workbuddy/skills/<name>/`（用户级，跨项目复用）。
- 若同名目录已存在，先移除旧目录再复制，避免文件残留。
- 确认最终 `SKILL.md` 存在且 frontmatter 正确（含 `agent_created: true`）。

### 步骤 6 — 装依赖 + 验证

- 受管 venv 路径（**必须 Windows 风格**）：
  `C:/Users/<当前Windows用户名>/.workbuddy/binaries/python/envs/default/Scripts/python.exe`
  本机（2026-09-14 实测）Windows 用户名是 `AHS`，即 `C:/Users/AHS/.workbuddy/binaries/python/envs/default/Scripts/python.exe`。
  建 venv 用受管解释器：`C:/Users/AHS/.workbuddy/binaries/python/versions/3.13.12/python.exe -m venv C:/Users/AHS/.workbuddy/binaries/python/envs/default`
  注意：用 `/c/Users/...` 会被原生 Windows Python 忽略（exit 0 但不建目录）。
- 装依赖：
  `pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
  需 `dangerouslyDisableSandbox: true` 并加 `--no-cache-dir`（沙箱内 safe-delete/回收站不可用会导致安装失败）。
- 纯标准库脚本（只用 `sys` / `re` / `pathlib`）**不需要建 venv**，直接用受管解释器跑即可。
- 验证四连：
  1. import 检查（脚本所需库均可导入）
  2. `py_compile scripts/*.py` 全部通过（node 脚本用 `node --check`）
  3. **用真实输入跑一次脚本**，不能只跑 `--help`：
     `python quality_check.py ~/.workbuddy/skills/xxx/examples/某示例/SKILL.md`，
     看输出是否为**真实统计/评分**（实测女娲 `quality_check.py` 输出 4/6 通过、`merge_research.py` 输出 53 个来源与一手占比 61/96 —— 这才叫跑通）。
  4. **外部资源核验（浏览器类 / 模型类技能必做）**：`pip install` 成功 ≠ 资源就位。
     必须确认资源目录真实存在并统计大小，再跑一次**真实功能调用**：
     - 浏览器类：`%LOCALAPPDATA%\ms-playwright\` 下应见 `chromium-*` / `chromium_headless_shell-*`（合计数百 MB），
       并且要**真抓一个网页 / 真截一张图**，不能只看 import 通过。
     - 模型类：权重目录存在且大小符合预期。
     - 教训（2026-09-14）：Scrapling 技能 `pip install` 全成功、`import` 也过，但 `ms-playwright` 内核缺失，
       直到真抓取才暴露 —— 只验 import 会把"假就绪"判成"已就绪"。
- **Playwright 内核版本不匹配（本机已复现 + 已解）**：
  装最新 `playwright-core` 后 `launch()` 报
  `Executable doesn't exist at ...\ms-playwright\chromium_headless_shell-1243\...`，而本机 `ms-playwright` 只有 `1234`。
  **不要为此重下 150MB+ 内核**，直接复用本机已有内核：
  ```js
  pw.chromium.launch({ executablePath:
    'C:/Users/<用户>/AppData/Local/ms-playwright/chromium_headless_shell-<rev>/chrome-headless-shell-win64/chrome-headless-shell.exe' })
  ```
  实测 r1234 可正常渲染截图（1800x2485 2x 高清）。
  注：`chromium_headless_shell-<rev>/chrome-headless-shell-win64/chrome-headless-shell.exe` 是 headless shell；
  完整内核在 `chromium-<rev>/chrome-win/chrome.exe`。排查顺序：先 `ls %LOCALAPPDATA%\ms-playwright` 拿到真实 rev，再决定复用还是下载。
- node 依赖装在**技能自己的 `scripts/` 目录**（`cd scripts && npm install <pkg>`），
  这样脚本里 `createRequire(import.meta.url)` 能直接解析，不必依赖 `NODE_PATH`。

## 四、复用坑速查（必读）

- **并行编辑同一文件会丢更新**：在同一条消息里对**同一个文件**发多个 Edit，只有部分生效（2026-09-15 实测：连发 4 个 Edit，仅 2 个落地，
  且工具**每个都报 Successfully**，极具迷惑性）。**同一文件的多处修改必须串行**（一条消息一个 Edit），
  或直接 `Read` 全文 → `Write` 整体重写。不同文件之间并行安全。
- **git clone 被注入代理打断**：报 `Empty reply from server`，剥离代理即通 —— 见步骤 2 的命令。
- **venv 路径用 Windows 风格** `C:/Users/...`；`/c/...` 会被原生 Python 忽略。
- **pip install 关沙箱 + 清华镜像 + `--no-cache-dir`**，否则沙箱内失败。
- **run_script.sh 内用 `cygpath -w -a`** 把脚本目录转成原生 Windows 路径，避免 Git Bash 的 MSYS 把 `/c/...` 参数误转成 `C:\c\...`。
- **中文乱码**：Edit 工具写中文 frontmatter 偶发损坏成 U+FFFD，安装后用 Python 复查并修复。
- **字体缺失警告**（仿宋/楷体可能未装）不影响功能，仅 `.docx` 排版回退。
- **"假就绪"陷阱**：`pip install` 成功 + `import` 成功 **不等于** 技能可用。带外部资源（浏览器内核、模型权重、词典、字体包）的技能，
  必须核验资源目录是否存在、跑一次真实功能调用，否则只会在实际使用时才暴露。
- **系统代理会污染抓取类技能**：WorkBuddy 会给子进程注入 `http_proxy`，导致部分站点 `502 CONNECT tunnel failed`。
  抓取测试前剥离：`env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY <python> ...`
- **本机账户 `AHS` 属于 Administrators 组**，但 WorkBuddy 进程运行在 UAC 过滤令牌（标准权限）下，
  `IsUserAnAdmin()` 返回 False。**绝大多数技能安装（含 pip / 浏览器内核）不需要提权**；
  遇到疑似权限问题时先定位真实原因，不要靠提权绕过。
- 纯提示词型技能（无 scripts、无依赖）只需做步骤 1–5，并跳过依赖安装。

## 五、给用户的回复要点

完成后告知：技能名、来源仓库、安装位置、能力简介、触发方式、依赖状态、审计结论（P2/需确认项）、以及使用提示
（例如"在对话里说：帮我根据这份招标文件写投标书"）。同时说明**审计结论**与**被剔除的物料**（若是仓库自带宣传资产）。
