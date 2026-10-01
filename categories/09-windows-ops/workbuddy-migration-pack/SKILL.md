---
name: workbuddy-migration-pack
description: 生成「WorkBuddy 换电脑迁移包」v3.1——把 AI 助手的全部身份（SOUL/IDENTITY/USER/MEMORY）、技能库、记忆缓存、连接器配置、自动化任务库、会话索引**与对话正文**、**产物与工件**、项目工作区打包到桌面，供复制到新电脑一键恢复。当用户说"重新生成迁移包/打迁移包/换电脑迁移/备份我到新电脑/迁移包"时使用。
---

# WorkBuddy 换电脑迁移包（workbuddy-migration-pack）v3.1

## 触发场景
- "重新生成迁移包" / "打一版最新的迁移包"
- "我要换电脑，把这台机器上的你搬过去"
- "备份我的技能和记忆"

## 一句话用法
```bash
python <skill>/scripts/make_pack.py                      # 全量（对话+产物+工作区，约 5 分钟，~600MB）
python <skill>/scripts/make_pack.py --skip-workspace     # 不打项目工作区
python <skill>/scripts/make_pack.py --skip-artifacts     # 不打产物与工件
python <skill>/scripts/make_pack.py --skip-conversations # 不打对话正文
python <skill>/scripts/make_pack.py --clean-old-packs    # 清理桌面上其他日期的旧包
```
输出：桌面 `WorkBuddy迁移包-<YYYY-MM-DD>/`

## 包结构（固定契约）
```
WorkBuddy迁移包-<日期>/
├── ⭐先看这里-换电脑恢复指引.md       ← 用户入口
├── restore-new-pc.sh                 ← 命令行一键恢复
├── 双击我-一键恢复.bat                ← GBK 编码双击启动器（自动找 Git Bash）
├── 01-身份与记忆/    SOUL/IDENTITY/USER/MEMORY-最新完整档案/memory-缓存
├── 02-技能库/skills/  （~/.workbuddy/skills 全量）
├── 03-配置与连接/     connectors/credentials/automation-backups/local_storage + mcp.json/mcp-approvals.json/models.json
├── 04-自动化任务/     workbuddy.db（sqlite backup API 一致性备份）
│                     merge_db.py（★「只补不清」合并工具，恢复端有既有库时用）
├── 05-对话记录/       conversations-<日期>.zip（★对话**正文** projects/）+ sessions（索引）
├── 06-产物与工件/     artifacts-<日期>.zip（blobs/file-history/artifact-index/changes-*/clipboard-images/appearance-resources）
└── 07-项目工作区-可选/ workbuddy-workspace-<日期>.zip + 工作区目录清单.txt
```

> **⚠️ 05 的两半缺一不可**：`sessions/` 只是每个 CLI 会话进程的登记（pid/cwd/url），
> **真正的对话内容在 `projects/<cwd派生目录名>/<会话id>.jsonl`**。
> 历史上 `make_pack.py` 曾只打包 `sessions/`，导致迁移后"空间有、对话全空""标题可见、点进去空"。

## 恢复端必须做的三件事（v3.1 已内置）

1. **`projects/` 目录要按新用户名改名**：目录名由 cwd 派生（`c-Users-<用户名>-WorkBuddy-<工作区>`，
   冒号被吃掉、盘符小写）。旧机器 `Administrator` → 新机器 `AHS`，**必须改名**，
   否则正文与 `sessions.cwd` 对不上号，点进去还是空的。restore 脚本已内置 sed 改名 + 重名合并。
2. **技能恢复用 `cp -rn`（不覆盖）**：迁移包里是旧机器快照，若本机已有**更新版**技能
   （例如本机刚修过 bug），直接 `cp -rf` 会把修复盖掉。必须用 no-clobber。
3. **数据库不能整库覆盖**：`cp workbuddy.db → $H/workbuddy.db` 会丢掉本机导入后新增的会话/空间。
   应调用随包的 `merge_db.py`：按主键**只补不清**，再清掉包内带来的老用户名 workspaces。

## 关键坑（务必遵守，血泪教训）

1. **workbuddy.db 绝不能裸拷** —— 应用运行中有 -wal/-shm，裸拷会丢最近数据甚至损坏。
   必须用 `sqlite3.connect(src).backup(sqlite3.connect(dst))`。
2. **同一天重打前不删旧包就覆盖**：先删目标目录再建，避免残留旧文件。
3. **旧日期包要清理** —— 桌面同时存在两个包会让用户拷错（`--clean-old-packs`）。
4. **Git Bash PATH 坑**：WorkBuddy 更新后 bash 的 PATH 初始化可能失效
   （`dirname/ls/awk: command not found`）。解决办法：每条 bash 命令前加
   `export PATH="/c/Users/<用户>/.workbuddy/binaries/PortableGit/versions/1.2.0/usr/bin:$PATH"`。
   make_pack.py 是纯 Python，不受此影响。
5. **PowerShell 工具输出可能不回显**（命令执行成功但无 stdout）。校验 zip 用 Python 的
   `zipfile.testzip()`，别依赖 PowerShell 的 Compress-Archive 回显。
6. **bat 必须 GBK 编码**（`encoding="gbk", newline="\r\n"`），否则 cmd 下中文乱码。
   bat 内传参只用 ASCII 文件名（`restore-new-pc.sh`），用 `%~dp0` 定位，避免中文参数。
7. **Git Bash 不用单独装**：WorkBuddy 自带 PortableGit
   (`~/.workbuddy/binaries/PortableGit/versions/<ver>/bin/bash.exe`)。bat 启动器按
   current → 通配版本 → 系统 Git 顺序探测。
8. **restore 脚本要自带 PATH 自愈**：开头 `export PATH="/usr/bin:/bin:$PATH"`。
9. **记忆档案的"最新"版本**：`~/.workbuddy/MEMORY.md` 常落后于
   `~/.workbuddy/memory/<uuid>_memory.md`（服务端同步的用户记忆档案，头部有 `Version` 与
   `Last updated`）。打包时把后者作为 `MEMORY-最新完整档案-<其 Last updated 日期>.md`。
10. **绝不能只打 `sessions/` 不打 `projects/`**。判断方法：打完后数一下包内
    `projects/**` 的文件数，**为 0 就是错的**。
11. **`05-对话记录` 的两半要分别校验**，只验目录存在不够——`sessions/` 有几十个文件
    却 `projects/` 空空，同样是坏包。
12. **workspace zip 里不含空目录**：一个"只被开过一次、没产生文件"的工作区，
    它的目录不会被 zip 收录。恢复端要为这类 cwd 补建空目录 + 补 workspace 索引，
    否则那些对话在界面上看不到（见 `workbuddy-migration-repair` 的合并章节）。
13. **大 zip 用后台跑**：200MB / 5000+ 文件的压缩或解压会超过前台命令超时（120s），
    必须 `run_in_background`；脚本要写成幂等（跳过已存在文件），中断后可直接重跑。

## 交付后必做校验
```python
z = zipfile.ZipFile(zip_path); assert z.testzip() is None   # CRC 全检
# 核对 01-身份与记忆/SOUL.md、04-自动化任务/workbuddy.db、README、restore、bat 均存在
# 核对 包内技能目录数 == 源技能目录数
# ★核对 05-对话记录：sessions/ 文件数 > 0 且 conversations zip 内 projects/** 文件数 > 0
# ★核对 06-产物与工件：artifacts zip 内 blobs / file-history 均非空
```

## 恢复端（写进README的流程，5 步）
1. 新电脑装 WorkBuddy → **登录原账号** → 打开一次（生成 ~/.workbuddy，云端记忆才会同步）
2. 整个文件夹拷过去
3. 完全退出 WorkBuddy
4. 双击 `双击我-一键恢复.bat`（或 `bash restore-new-pc.sh`）
5. 重开 → 连接器管理页重新点「信任」GitHub/CloudBase/邮箱 → 检查自动化任务

> ⚠️ **若新电脑并非"干净环境"（已有本机数据）**，不要直接跑 restore 脚本：
> 它虽然已改成合并不覆盖，但**最稳的做法**是走
> `workbuddy-migration-repair` 技能里的「二次导入（合并去重）」流程。

## 安全
包内含凭据/令牌与**全部聊天记录**。交付时**必须提醒用户**：只走 U盘/私人网盘/加密压缩，
不发公共群或聊天工具。

## 打磨记录
- 2026-09-09 首版（58 技能 / 8 自动化 / 221M 工作区）
- 2026-09-14 v2.1：加 PATH 自愈、双击 bat 启动器、模板化生成器；技能 60、自动化 9
- **2026-09-14 v2.2（重大修复）**：`make_pack.py` 曾只打包 `sessions/` 会话索引、漏了 `projects/`
  对话正文 → "空间有、对话全空"。补上 `projects/` + restore 端改名。
- **2026-09-15 v3.0**：新增 `05-对话记录`（对话正文 zip）、`06-产物与工件`（blobs/file-history/
  artifact-index/changes-*/clipboard-images/appearance-resources）、`07-项目工作区`；
  加 `--skip-*` 开关、自校验（zip CRC）、只读属性清除、原子落地。
- **2026-09-15 v3.1（合并修复）**：v3.0 丢掉了 v2.2 的恢复端改名与不覆盖策略，本次补回：
  ① restore 脚本对 `projects/` 按当前用户名 **sed 改名**（重名则合并，原件存 `oldname-*`）；
  ② 技能恢复改 `cp -rn` **不覆盖本机较新版本**，并清理 `__pycache__`；
  ③ 数据库恢复改 `merge_db.py` **只补不清**，先备份再合并，清老用户名 workspaces，
     为有正文缺索引的 cwd 补 workspace。**教训：两条线并行开发会互相丢改进，合并时要逐项对差异。**
- 统计技能数务必用 Python `iterdir()`，`ls -d */` 会漏数（实测 59 vs 60）
