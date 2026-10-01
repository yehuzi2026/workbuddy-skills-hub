---
name: workbuddy-migration-repair
description: 修复「换电脑迁移后 WorkBuddy 空间/工作区列表变空、空间里对话全空、自动化任务全失效」的事故，以及把迁移包「合并」进已有安装（去重不覆盖、不丢本机新增数据）。当用户说"空间里面什么也没有了""项目列表空了""之前的工作区不见了""空间在但对话一条都没有""旧记录点开是空的""自动化任务不跑了""迁移后数据丢失""重新导入迁移包/再导入一次/重复的修复一下"，或发现 ~/.workbuddy/workbuddy.db 旁存在 workbuddy.db.corrupt-* 文件时使用。覆盖诊断、备份、automations 路径修复、workspaces 索引重建、盘符大小写归一、会话正文(projects)搬迁、迁移包二次导入合并、WAL 加固等环节。
agent_created: true
---

# WorkBuddy 迁移后数据修复（workbuddy-migration-repair）

## 症状对照表

| 用户描述 | 真实病因 | 可恢复性 |
|---|---|---|
| "空间/工作区列表空了" | `workbuddy.db` 被判定损坏后重建为空库，`workspaces` 表被清空 | ✅ 可从磁盘目录重建 |
| "项目都不见了" | 同上，但**文件通常都在** `C:\Users\<新用户>\WorkBuddy\` | ✅ 文件未丢 |
| "自动化任务不跑了" | `automations.cwds` 和 `prompt` 里仍是老机器绝对路径（`C:\Users\<老用户>\...`） | ✅ 可批量替换 |
| "会话历史没了" | `projects/*/*.jsonl` 未随迁移包带走 | ❌ 无本地副本则不可恢复 |
| **"一使用就蹦"/报错** | 老路径引发的 `EPERM: operation not permitted, mkdir 'C:\Users\<老用户>'`——自动化任务、会话登记都会踩 | ✅ 改路径后消失 |
| **"旧记录点开是空的"** | `projects/` 目录名由 cwd 派生（`c-Users-<用户>-WorkBuddy-<工作区>`），老 jsonl 未随迁移带走 | ❌ 无本地副本不可恢复 |
| **"空间都在，但每个空间里一条对话都没有"** | `workspaces.path` 盘符是小写 `c:`、`sessions.cwd` 是大写 `C:`——**SQLite 精确匹配大小写敏感**，客户端按 cwd 反查会话命中 0 条 | ✅ 统一盘符大小写即可（见 6.7）|
| **"又拷了一份完整的包，重新导入/重复的修复一下"** | 包里 `restore-new-pc.sh` 会**整库覆盖 + 覆盖技能 + 不解压改名**，对已有数据的机器是灾难 | ✅ 走第七步「合并」，不要跑那个脚本 |
| **"导入后空间变多了，有重复的"** | 包内老用户名路径与本机新用户名路径**主键不同**，被当新行插入 | ✅ 见 7.4 去重清理 |
| **"导入后对话还是打不开"** | 解压 `projects/` 后**没按新用户名改目录名**，正文与 cwd 对不上 | ✅ 见 7.5 |
| **"任务改不了/报 not found"** | `automations` 的 `owner_user_id` 被写成了字符串 `confirmed`（字段整体错位一格） | ✅ 见第六步 |

**核心判断**：先分清「索引丢了」还是「文件丢了」。绝大多数情况是**索引丢了，文件完好**——先别慌，更别让用户重装。

## 第零步：一键自检（推荐先跑，30 秒定位问题）

```bash
# 本机 Git Bash 缺 coreutils，务必用受管 Python 绝对路径
export PYTHONIOENCODING=utf-8
"C:/Users/<用户>/.workbuddy/binaries/python/versions/3.13.12/python.exe" \
  "C:/Users/<用户>/.workbuddy/skills/workbuddy-migration-repair/scripts/selfcheck.py"
```

输出 `[OK]/[BAD]/[WARN]/[i]` 四级标记 + 汇总；**退出码 0 = 健康，1 = 有需修复项**（可接自动化）。
覆盖六项：数据库健康 / 老路径残留全库扫描 / workspaces 索引 / sessions 登记文件 /
automations 配置体检 / 崩溃与 EPERM 统计（含「近 30 分钟是否仍在发生」，自动区分历史记录）。

自检报 `[BAD]` 后再按下方第一~六步修复。

## 第一步：诊断（只读，不要动任何东西）

```python
# 用 managed python 绝对路径执行，不要用 bash 里的 python -c（见「坑」章节）
import os, time
BASE = os.path.join(os.environ['USERPROFILE'], '.workbuddy')
for f in sorted(os.listdir(BASE)):
    if 'corrupt' in f or f.startswith('workbuddy.db'):
        p = os.path.join(BASE, f)
        print('%-70s %10d  %s' % (f, os.path.getsize(p),
              time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(p)))))
```

关键信号：

1. **存在 `workbuddy.db.corrupt-<ISO时间戳>Z`** → 主库曾被判定 malformed 并隔离重建。
   文件名里的 UTC 时间戳就是事故时刻（+8 换算本地时间）。
2. **主库 `workbuddy.db` 只有 4096 字节** → 空库（只有一个空页）。
3. **`workbuddy.db-wal` 却有几 MB** → 数据全悬在 WAL 里，主库没落盘。**这是损坏的温床**。
4. 读 `logs/Crash-Log/.processed-crashes.json` 与 `logs/Crash-Log/crash-report-*.json`
   → 事故前后是否有 daemon / sidecar 崩溃。
5. 对比新旧机器用户名：`automations` 表里的路径指向哪个用户目录，该目录是否存在。

```python
# 确认老机器用户名是否已不存在
print(os.path.exists('C:' + chr(92) + 'Users' + chr(92) + '<老用户名>'))
```

## 第二步：备份（改任何东西之前必须做）

```python
import os, sqlite3, json, shutil, datetime
U = os.environ['USERPROFILE']
BASE = os.path.join(U, '.workbuddy')
bk = os.path.join(BASE, '_backup-pre-repair-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
os.makedirs(bk, exist_ok=True)

# 1) 文件级
for f in ['workbuddy.db', 'workbuddy.db-wal', 'workbuddy.db-shm']:
    p = os.path.join(BASE, f)
    if os.path.exists(p):
        shutil.copy2(p, os.path.join(bk, f))

# 2) 逻辑级（在线 backup API，能正确合并 WAL）
uri = 'file:' + os.path.join(BASE, 'workbuddy.db').replace(chr(92), '/') + '?mode=ro'
src = sqlite3.connect(uri, uri=True)
dst = sqlite3.connect(os.path.join(bk, 'logical-backup.db'))
src.backup(dst); dst.close(); src.close()

# 3) 业务数据导出 JSON（便于人工核对与回滚）
con = sqlite3.connect(os.path.join(bk, 'logical-backup.db')); con.row_factory = sqlite3.Row
out = {}
for t in ['automations', 'workspaces', 'sessions', 'session_usage', 'migration_meta']:
    try:
        out[t] = [dict(r) for r in con.execute('select * from "%s"' % t)]
    except Exception as e:
        out[t] = 'ERR ' + str(e)
con.close()
open(os.path.join(bk, 'data-export.json'), 'w', encoding='utf-8').write(
    json.dumps(out, ensure_ascii=False, indent=1))
print('备份完成:', bk)
```

## 第三步：修 automations 的失效路径

**必须走 `automation_update` 工具，禁止用 SQL 直接改 `automations` 表。**

```python
# 先读全部任务，算出哪些字段含老用户名
import sqlite3, os
con = sqlite3.connect(os.path.join(os.environ['USERPROFILE'], '.workbuddy', 'workbuddy.db'))
con.row_factory = sqlite3.Row
for r in con.execute('select id, name, cwds, prompt from automations'):
    print(r['name'], '| cwds命中:', (r['cwds'] or '').count('<老用户名>'),
          '| prompt命中:', (r['prompt'] or '').count('<老用户名>'))
```

然后逐条 `automation_update(mode="update", id=..., cwds=..., prompt=...)`：

- **`update` 模式只传要改的字段，未传的字段会原样保留**（已实测：只传 `cwds` 时 `prompt` 完整保留）。
  所以只改 `cwds` 的任务就**不要**传 `prompt`，避免手抄出错。
- 含老用户名的 `prompt` 才传，内容是原文把老用户名替换成新用户名。
- `cwds` 参数传 **逗号分隔的单个路径字符串**，不是 JSON 数组：
  `cwds="C:\Users\<新用户>\WorkBuddy\<项目目录>"`

**顺带必查两项**（迁移常伴随这两处坏数据）：

1. `status` 是否为 `PAUSED` —— 迁移后任务可能被整体暂停，修好路径也不会跑。
   是否恢复 `ACTIVE` 必须问用户，不要擅自激活。
2. `rrule` 是否被写坏 —— 典型是原本 DAILY 变成了 `FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=31`
   （每年只跑一次）。发现即报告，改动前确认。
3. `validUntil` 是否已过期 —— 如 `2026-09-06`，过期后任务静默不触发。

## 第四步：重建 workspaces 索引

`workspaces` 表结构极简：`path TEXT PRIMARY KEY, last_opened_at INTEGER NOT NULL`。

**必须把脚本写成 `.py` 文件再执行**（原因见「坑」章节），核心逻辑：

```python
import os, sqlite3, re
U = os.environ['USERPROFILE']
ROOT = os.path.join(U, 'WorkBuddy')       # 用 os.path.join，不要硬编码反斜杠
DB   = os.path.join(U, '.workbuddy', 'workbuddy.db')

def norm(p):                              # 与既有记录一致：盘符小写 + 全反斜杠
    p = p.replace('/', os.sep)
    if len(p) > 1 and p[1] == ':':
        p = p[0].lower() + p[1:]
    return p

TS = re.compile(r'^20\d\d-\d\d-\d\d-\d\d-\d\d-\d\d$')
con = sqlite3.connect(DB, timeout=20); con.execute('pragma busy_timeout=20000')

# 先清掉格式错误的旧记录（含正斜杠的）
for (p,) in list(con.execute('select path from workspaces')):
    if '/' in p:
        con.execute('delete from workspaces where path=?', (p,))
con.commit()

ins = skip = 0
for n in sorted(os.listdir(ROOT)):
    fp = os.path.join(ROOT, n)
    if not os.path.isdir(fp):
        continue
    if not (TS.match(n) or n.startswith('automation-') or n == '<业务目录名>'):
        continue
    key = norm(fp)
    if con.execute('select 1 from workspaces where path=?', (key,)).fetchone():
        skip += 1
        continue
    con.execute('insert or ignore into workspaces(path,last_opened_at) values(?,?)',
                (key, int(os.stat(fp).st_mtime * 1000)))
    ins += 1
con.commit()
print('新增', ins, '跳过', skip)
```

要点：

- **路径格式必须与既存记录完全一致**（实测既存格式为 `c:\Users\...` 全反斜杠 + 小写盘符）。
  混合斜杠会导致主键不匹配 → 同一工作区出现两条记录。
- `insert or ignore` + 先查重，避免重复。
- `last_opened_at` 用目录 mtime（毫秒），列表排序才合理。
- **跳过乱码目录名**（老机器中文名被按 GBK 解释成 `ÞÂàþ«ù...` 之类），
  它们通常与一个正常中文名目录**内容重复**，属重复数据，只报告不删。

写完立刻复核：`pragma integrity_check`、`workspaces` 计数、重复路径检测。

## 第五步：WAL 加固（防止再次损坏）

数据全悬在 WAL、主库只有 4096 字节时，异常退出极易再次损坏。落盘：

```python
con = sqlite3.connect(DB, timeout=30); con.execute('pragma busy_timeout=30000')
print(con.execute('pragma wal_checkpoint(TRUNCATE)').fetchone())  # (busy, log, checkpointed)
con.close()
```

成功后主库从 4KB 涨到 ~160KB、`-wal` 归零，`integrity_check` 应返回 `ok`。
**这一步是关键的加固动作，务必执行。**

最后让用户**重启 WorkBuddy**：数据库索引已更新，但客户端有内存缓存，不重启看不到 36 个工作区。

## 第六步：全量残留清理（实测必做，前三步盖不住）

只改 `automations` + `workspaces` 是**不够的**。老用户名散落在至少 7 处，漏一处就会出现
"列表正常但一用就报错"。全部用 managed python 写成 `.py` 执行。

### 6.1 先做全库扫描，确认范围

```python
import sqlite3, os
con = sqlite3.connect(os.path.join(os.environ['USERPROFILE'], '.workbuddy', 'workbuddy.db'))
for (t,) in con.execute("select name from sqlite_master where type='table'"):
    cols = [r[1] for r in con.execute('pragma table_info("%s")' % t)]
    for c in cols:                      # 逐列 like 扫描，BLOB/数字列会抛异常，吞掉即可
        try:
            n = con.execute("select count(*) from \"%s\" where \"%s\" like '%%Administrator%%'"
                            % (t, c)).fetchone()[0]
            if n: print('%-30s %-22s %d' % (t, c, n))
        except Exception: pass
```

实测命中面（以 Administrator → AHS 为例）：

| 位置 | 规模 | 处理 |
|---|---|---|
| `workspaces.path` | 10 条死路径 | 去重/改写（第四步） |
| `sessions.cwd` + `plugin_context_json` | 464 + 12 | SQL replace |
| `sessions/<pid>.json` **文件** | 754 / 846 | 改 cwd；孤儿归档 |
| `automations.cwds` / `prompt` | 9 + 5 | 走 `automation_update` |
| `automation_runs.runs_json` | 214 | **双反斜杠**，见 6.3 |
| `automation_runtime_state.last_error` | 1 | 记录的是旧 EPERM，改路径后应清空 |
| 工作区 `.workbuddy/skills/**/SKILL.md` | 若干 | 文本替换 |

### 6.2 `sessions/` 目录：单独处理，且要区分「活/死」

`~/.workbuddy/sessions/*.json` 是**每个 CLI 会话进程的登记文件**（`pid` / `lastHeartbeat` /
`cwd` / `url`），正常应在进程退出时清理。迁移后大量残留，客户端加载时踩老 cwd 报错。

```python
import os, json, glob, ctypes, shutil, re, time
SESS = os.path.join(os.environ['USERPROFILE'], '.workbuddy', 'sessions')
ARCH = SESS + '-orphan-archive-' + time.strftime('%Y%m%d-%H%M%S')
k32 = ctypes.windll.kernel32
alive = lambda pid: bool(k32.OpenProcess(0x1000, False, int(pid)) and k32.CloseHandle(
                       k32.OpenProcess(0x1000, False, int(pid))) or False)
RX = re.compile(r'(?<=Users)(\\+|\/+)Administrator')      # 关键：反斜杠数量不确定，必须正则
for f in glob.glob(os.path.join(SESS, '*.json')):
    d = json.load(open(f, encoding='utf-8', errors='ignore'))
    if d.get('pid') and not alive(d['pid']):
        os.makedirs(ARCH, exist_ok=True)
        shutil.move(f, os.path.join(ARCH, os.path.basename(f)))   # 归档，不删
    else:
        t = open(f, encoding='utf-8').read()
        open(f, 'w', encoding='utf-8', newline='').write(RX.sub(lambda m: m.group(1)+'AHS', t))
```

**务必归档而非删除**——归档目录可回退，且用户能自己翻。

### 6.3 `automation_runs.runs_json`：反斜杠是**双写**的

该列存的是 JSON 文本再被序列化，路径形如 `C:\\Users\\Administrator\\...`（**字面两个反斜杠**）。
只替换单反斜杠形式会"报成功但残留不动"。四种形式都要替换：

```python
for a, b in [('Users\\\\Administrator\\\\', 'Users\\\\AHS\\\\'),   # 双反斜杠（主）
             ('Users\\Administrator\\',   'Users\\AHS\\'),
             ('Users//Administrator/',    'Users//AHS/'),
             ('Users/Administrator/',     'Users/AHS/')]:
    con.execute("update automation_runs set runs_json=replace(runs_json,?,?) where runs_json like ?",
                (a, b, '%Administrator%'))
```

末尾**没有反斜杠**的残留（如 `mkdir 'C:\Users\Administrator'`）replace 抓不到 →
用 Python 读出该行、正则 `(?<=Users)(\\+|\/+)Administrator` 替换后写回。

### 6.4 `automations.owner_user_id` 字段错位 —— 会让 `automation_update` 彻底失联

**症状**：`automation_update(mode="update", id=...)` 返回
`Error: Automation not found: automation-xxxx`，但该 id 明明在库里。

**病因**：`owner_user_id` / `owner_status` / `owner_source` 三列的值**整体错位一格**：

| 字段 | 正常 | 错位后 |
|---|---|---|
| `owner_user_id` | `8bf33bb1-...`（UUID） | `confirmed` |
| `owner_status` | `confirmed` | `created` |
| `owner_source` | `created` | `NULL` |

工具按 `owner_user_id == 当前用户 UUID` 过滤 → 永远匹配不上 → 报 not found。
**这是工具自身已无法触达的死锁，只能用 SQL 修元数据**（改的是归属字段，不是任务内容）：

```python
GOOD = con.execute("select owner_user_id from automations "
                   "where owner_user_id like '%-%-%-%-%' limit 1").fetchone()[0]
for aid in BAD_IDS:
    con.execute("update automations set owner_user_id=?, owner_status='confirmed', "
                "owner_source='created' where id=?", (GOOD, aid))
```

修完立刻重试 `automation_update`，即可正常改 `cwds`。

### 6.5 归档「已了结」的损坏标记

数据库已 `quick_check=ok` 后，这两类文件只剩副作用（每次启动记一条无意义日志）：

- `workbuddy.db.corrupt-<ISO>Z` / `-shm` / `-wal`（**救不出东西**，见坑 4）
- **`workbuddy.db.recovery-pending`**（`state: PARTIAL`, `walReplayed: false`）
  → 会触发跨重启恢复流程，把它 `shutil.move` 到归档目录即可

### 6.6 `projects/` 目录名 = cwd 派生，不要手工改名

`projects/c-Users-AHS-WorkBuddy-2026-08-06-11-23-49/` 这种名字是把 cwd 的非字母数字换成 `-`。
老机器派生的是 `c-Users-Administrator-...`。**改数据库 cwd 不会迁移 jsonl**，
两者要分别核对：先看 `projects/` 有几个目录，再判断历史正文到底在不在。

**搬迁工具（本技能自带，2026-09-14 新增）：**

```bash
export PYTHONIOENCODING=utf-8
PY="C:/Users/<用户>/.workbuddy/binaries/python/versions/3.13.12/python.exe"
SC="C:/Users/<用户>/.workbuddy/skills/workbuddy-migration-repair/scripts/repair_conversation_bodies.py"

"$PY" "$SC" --dry-run                 # 1) 先看：哪些工作区缺正文、各缺多少会话
"$PY" "$SC" --src "D:/老机器/.workbuddy/projects"   # 2) 从老机器目录导入并改名归位
"$PY" "$SC"                          # 3) 无 --src 时只做「本机改名归位」
```

- 逻辑：把 DB 里每个 `sessions.cwd` 派生成 `c-Users-<用户>-WorkBuddy-<工作区>` 目录名，
  与 `projects/` 下实际目录比对；老用户名目录（`c-Users-Administrator-...`）**改名**成新用户名，
  外部目录用 `--src` 拷进来后同样改名归位。
- **只改名/拷贝，从不删 jsonl**；改动前自动备份 `projects` 到 `_backup-projects-<时间戳>`。
- 实测（2026-09-14）：DB 里 56 个工作区，本机只有 5 个有正文目录，**51 个缺**——
  其中 tender-crawler 一个就缺 294 个会话。这正是「标题能看到、点进去空的」的直接证据。

### 6.7 盘符大小写不匹配 —— 「空间都在但对话全空」的真凶

**症状**：空间/工作区列表**正常显示**，可点进任何一个空间，**会话列表空**。

**病因**：SQLite 的 `=` 在字符串比较上**大小写敏感**。迁移后常见两种写法混存：

| 表 | 列 | 实测值 |
|---|---|---|
| `workspaces` | `path` | `c:\Users\AHS\WorkBuddy\...`（**小写盘符**）|
| `sessions` | `cwd` | `C:\Users\AHS\WorkBuddy\...`（**大写盘符**）|

客户端按 `sessions.cwd == workspaces.path` 精确匹配取会话 → **0 命中** → 空间里一条对话都没有。
（注意：写路径时若误用 `where path like 'c:%'` 验证会**假阳性**——SQLite `LIKE` 默认大小写**不敏感**，
必须用 `substr(path,1,1)='c'` 这类精确判断。）

**修复**（统一为大写盘符）：

```python
import sqlite3, os
DB = os.path.join(os.environ['USERPROFILE'], '.workbuddy', 'workbuddy.db')
con = sqlite3.connect(DB, timeout=20); con.execute('pragma busy_timeout=20000')
# 盘符归一为大写（只动首字母，不碰其余部分）
con.execute("update workspaces set path = upper(substr(path,1,1)) || substr(path,2) "
            "where substr(path,1,1) between 'a' and 'z'")
con.execute("update sessions set cwd = upper(substr(cwd,1,1)) || substr(cwd,2) "
            "where substr(cwd,1,1) between 'a' and 'z'")
con.commit()
# 复核：两表小写盘符都应为 0；再验精确匹配率
print('workspaces 小写:', con.execute(
    "select count(*) from workspaces where substr(path,1,1) between 'a' and 'z'").fetchone()[0])
print('sessions   小写:', con.execute(
    "select count(*) from sessions where substr(cwd,1,1) between 'a' and 'z'").fetchone()[0])
con.execute('pragma wal_checkpoint(TRUNCATE)')   # 顺手落盘
con.close()
```

实测修复后：41/41 工作区全部精确命中，并救回 2 条被标 `error`/`deleted` 的会话。
**做完让用户重启客户端**——索引已好，但 UI 有缓存。

> 归一并顺带发现：`sessions.status` 里若有 `error`/`deleted` 但 cwd 正确，
> 说明这条会话曾因老路径报错，改盘符后可一并恢复为正常态。


## 第七步：把迁移包「合并」进已有安装（二次导入，去重不覆盖）

**触发场景**：用户把另一台电脑的**完整迁移包**（v3.0 结构，含 `05-对话记录` / `06-产物与工件` /
`07-项目工作区`）拷到桌面，说"重新导入，必须要有所有的任务和空间以及对话记录和产物；
之前导入过一次，重复的要修复、不能重复"。

### ⛔ 第一条铁律：不要跑包里的 `restore-new-pc.sh`

那个脚本是给**干净新机**设计的，对已有数据的机器会：
- `cp workbuddy.db → $H/workbuddy.db`：**整库覆盖**，丢掉本机导入后新增的会话/空间；
- `cp -rf skills/* → $H/skills/`：**覆盖本机更新版技能**（本机刚修的 bug 会被盖回去）；
- `unzip conversations.zip`：**不改目录名**，旧用户名目录与 cwd 对不上号，正文照样打不开。

必须自己按下面 7 步做「合并」。

### 7.1 先盘点，别急着写

```python
# 1) 包内特征：结构 / 老用户名 / 各表行数
#    典型包：01-身份与记忆 02-技能库 03-配置与连接 04-自动化任务
#            05-对话记录(sessions/ + conversations-<日期>.zip)
#            06-产物与工件(artifacts-<日期>.zip) 07-项目工作区-可选
# 2) 包内 DB vs 当前 DB 的「主键集合」比对（不是比行数！）
```

**关键教训（实测踩过）**：比行数会误判。包内 `workspaces` 用
`C:\Users\<老用户>\...`，本机用 `C:\Users\<新用户>\...` —— **主键不同**，
所以包内 10 条会被当"新记录"插进来，造成**重复空间**。必须按路径内容比对：

| 表 | 主键 | 陷阱 |
|---|---|---|
| `workspaces` | `path` | 老用户名路径 ≠ 新用户名路径 → 会被当新行插入 |
| `sessions` | `id` | 是 UUID，跨机器相同 → 能正确去重 |
| `automations` | `id` | 同上 |
| `automation_runs` | `thread_id` | 同上 |

### 7.2 备份（改前必做）

备份 `workbuddy.db`（文件级 + `sqlite3.backup()` 逻辑级）、`projects/`、
`blobs/ file-history/ artifact-index/ changes-*/ clipboard-images/ appearance-resources/`、
身份文件与技能清单。实测 30MB 左右，几秒完成。

### 7.3 数据库：按主键「只补不清」

对包内每张表，逐行判断主键是否已存在，**只 INSERT 缺失行，绝不 UPDATE/DELETE**。
本技能打包脚本已随包提供 `04-自动化任务/merge_db.py`，可直接调用；
也可参考 `workbuddy-migration-repair/scripts/` 的思路自写。

插完后**立刻做 7.4 的去重清理**——否则就会出现重复空间。

### 7.4 清理合并引入的重复 / 死路径（必做）

```python
# 包内老用户名 workspaces 逐条处置
for p in [r for r in con.execute("select path from workspaces where path like '%<老用户>%'")]:
    new = p.replace('\\Users\\<老用户>\\', '\\Users\\<新用户>\\')
    if exists(new):   con.execute('delete from workspaces where path=?', (p,))   # 内容重复 → 删
    elif isdir(new):  con.execute('update workspaces set path=? where path=?', (new, p))
    else:             con.execute('delete from workspaces where path=?', (p,))   # 死路径 → 删
```
顺带复位 `automation_runtime_state` 里 `running=1` 的行、清 `last_error` 里的老路径。

### 7.5 对话正文：解压 + **按新用户名改目录名**

`projects/` 目录名由 cwd 派生：`C:\Users\<用户>\WorkBuddy\<工作区>` →
`c-Users-<用户名>-WorkBuddy-<工作区>`（**盘符小写、冒号被吃掉**）。
解压 `conversations-<日期>.zip` 后必须把 `c-Users-<老用户>-` 改成 `c-Users-<新用户>-`，
重名目录则合并（原件另存 `oldname-*`）。**只解压不改名 = 白导**。

> zip 里不只有 `.jsonl`：实测 561 个条目 = 479 `.jsonl` + 5 `.ndjson` + 6 `.json` +
> 70 `.txt` + 1 `.bash`，**全部照原样还原**，别只挑 jsonl。

### 7.6 产物 / 工作区：解压但**不覆盖已有文件**

`artifacts-<日期>.zip` 解到 `~/.workbuddy/`（`blobs` / `file-history` / `artifact-index` /
`changes-detail` / `changes-index` / `clipboard-images` / `appearance-resources`）；
`workbuddy-workspace-<日期>.zip` 解到 `~/`（解出 `WorkBuddy/`）。
两者都用**跳过已存在**策略 —— 本机文件可能是已修正过路径的更新版
（实测 `appearance-resources/*/skin.css`：本机是 `C:/Users/AHS/...`，包内还是
`C:/Users/Administrator/...`，**本机才对**）。

跳过 `local_server.pid` 这类运行时文件。

### 7.7 补建「有正文但没空间索引」的 cwd

`workspaces` 表驱动界面的空间列表；`sessions.cwd` 是会话归属。
**若某 cwd 的正文存在但 `workspaces` 里没这条 → 那些对话在界面上看不到。**

```python
present = set(os.listdir(os.path.join(H, 'projects')))
for cwd in distinct_sessions_cwd:
    if cwd in workspaces: continue
    if proj_key(cwd) not in present: continue      # 没正文就不用补
    os.makedirs(cwd, exist_ok=True)                # zip 不收录空目录，这里补建
    insert into workspaces(path, last_opened_at)
```
实测：**16 个 cwd 需要补**，其中 15 个物理目录不存在（zip 不收空目录）——
补建后空间从 41 → **57**，对话覆盖率 100%。

### 7.8 技能：**不导入**是常态，逐文件哈希比对才是关键

先按目录名比集合，再对同名技能**逐文件 MD5 比对**（只比文件数会漏判内容差异）。实测结论分布：

| 差异类型 | 数量 | 处理 |
|---|---|---|
| 只差 `_skillhub_meta.json` | 21 | 差异仅 `iconLocalPath` 里的用户名，**本机已是修正版** → 不动 |
| 本机多文件（如多 `_icon.png`） | 1 | 本机更全 → 不动 |
| 本机 SKILL.md 更长/更新 | 1 | 本机更新 → 不动 |
| **两边各有长处（真冲突）** | 1 | **必须人工合并**，见下 |
| 仅本机有 / 仅包内有 | 3 / 0 | 保留本机 |

**真冲突的处理原则**：以功能更强的那版为基底，把另一版独有的能力**逐项补回**，
并在 SKILL.md 用「打磨记录」写清谁并谁、补了什么。实测 `workbuddy-migration-pack`：
包内 v3.0 有"对话正文 zip + 产物 zip + 工作区 zip"但丢了本机 v2.2 的
"恢复端改名 / 不覆盖 / 不整库覆盖" → 以 v3.0 为基底补回三处，版本号升 v3.1。

顺手清 `skills/*/__pycache__`（打包/解压会带进来，属"多的不需要"）。

### 7.9 最终核验（缺一不可）

- [ ] `quick_check` = ok；`workspaces` 无重复 path、无老用户名、无小写盘符、无死路径
- [ ] `sessions.cwd` 无老用户名
- [ ] **每个空间都有正文目录**，且逐空间 `会话数 ≤ 正文 jsonl 数`
- [ ] 三个 zip **逐文件字节比对**：条目数一致、缺失 0
      （唯一允许的"大小不符"是"本机已修正过路径"的文件，要能解释清楚）
- [ ] 技能：无同基名多版本、无空目录、无 `__pycache__`
- [ ] 让用户**重启客户端**（索引已好，UI 有内存缓存）

## 坑（每条都实际踩过）

1. **不要用 `python -c "..."` 跑含 Windows 路径的脚本。**
   本机 Git Bash 的 MSYS 层会把参数里的 `C:\Users\...` 转成正斜杠，
   导致 `os.path.join` 拼出 `c:/Users/...\项目名` 这种混合斜杠写进主键。
   → **一律把脚本 Write 成 `.py` 文件再执行**，或改用 `os.path.join` + `os.environ['USERPROFILE']` 构造路径。

2. **本机 Git Bash 缺 coreutils**：`dirname`、`head`、`grep`、`cd` 全部 command not found，
   `2>/dev/null | grep` 这类管道会直接失败。**不要用管道做过滤**，在 Python 里过滤。

3. **PowerShell 工具在本机不返回 stdout**（exit code 0，输出为空）。
   诊断脚本**统一用 managed python 绝对路径**执行：
   `C:\Users\<用户>\.workbuddy\binaries\python\versions\<ver>\python.exe`

4. **`.corrupt-*` 文件救不出东西**：实测是 `database disk image is malformed`，
   连 `pragma page_count` 都拒绝。按字节扫描最多捞出 `automations` 的 prompt 文本
   （这些在新库里本来就有）。**不要在这上面浪费时间**，直接走「从磁盘重建索引」路线。

5. **automations 的绝对路径替换不要漏 `~/.workbuddy/skills/...` 里的 python 解释器路径**
   —— 老机器写的是 `C:/Users/<老用户>/.workbuddy/binaries/python/...`，也要一起换。

6. 改完 automations 后要**逐条回读校验**老用户名字符串出现次数为 0，不要凭工具返回的成功消息收工。

7. **`daemon.log` 里的 EPERM 要分种类，别一概而论**。实测同一份日志里至少三种：
   - `[AutomationRunRuntime] executeRun failed ... EPERM: mkdir 'C:\Users\<老用户>'`
     → **真病因，改路径即解**（本技能处理对象）。
   - `[conversations] diagnostic log write failed {"code":"EPERM","droppedLines":N}`
     → **与路径无关**的独立问题，daemon 丢弃日志后继续，不致命。实测 200+ 次仍在刷，
     且 `logs/Diagnostics` 目录 ACL 正常（`AHS:(I)(OI)(CI)(F)`）、实测可写。
     初步判断与沙箱/日志轮转锁定有关，**重启客户端后观察**，不要往路径问题上带。
   - `[BuiltinLocalMcpAppDiscovery] ... spawn node ENOENT` → node 不在 PATH，与本技能无关。

8. **管理员身份 ≠ 能写 `C:\Users\<老用户>`**。用户常问"我明明是管理员，是不是权限问题"。
   正确答案：**不是**。老账户目录是另一个用户的 profile，即使当前账户在 Administrators 组、
   进程是 UAC 过滤令牌时也会 `EPERM`。**排除法**：先 `icacls` 看 ACL + 实测写文件，
   ACL 正常就直接转向路径残留，别在权限上浪费时间。

9. **`automation_runs` 里可能残留"看起来是路径其实是正文"的行**。例如对话历史被存进
   `runs_json`，里面提到 `projects/c-Users-Administrator-...`。这属于历史记录，**不要改**，
   改了反而是篡改。判定方法：替换后仍残留且片段不含 `Users\` 形式 → 放过并说明。

10. **SQLite 的 `LIKE` 大小写不敏感，`=` 敏感** —— 这是「空间在、对话空」最易误判的点。
    用 `where path like 'c:%'` 去验证"是否还有小写盘符"会**假阳性**（大小写都算命中），
    必须用 `substr(path,1,1)='c'` 或 `GLOB 'c:*'`。修盘符时同理：只改首字母大小写，
    别整串 `lower()`/`upper()`，否则会把 `WorkBuddy`、项目名一起改坏。

11. **验证脚本自身的判定逻辑也会写错**。本次 `_fix_case.py` 的复核打印了
    "仍为小写盘符: 41 条（应为 0）" —— 其实是 `LIKE` 假阳性，真实是 0/41，
    差点误判修复失败。**修复脚本的复核语句要单独用第二种方法交叉验证**（见坑 10）。

## 收尾清单

- [ ] `pragma integrity_check` / `quick_check` = `ok`
- [ ] `workspaces` 计数 = 磁盘实际工作区数，无重复路径，无正斜杠残留，**无死路径**
- [ ] `sessions.cwd` / `plugin_context_json` 老用户名残留 = 0
- [ ] `sessions/*.json` 文件残留 = 0，孤儿登记已归档
- [ ] `automations` 的 `cwds` **和** `prompt` 老用户名残留 = 0，且 `owner_user_id` 是 UUID
- [ ] `automation_runs.runs_json` 残留清零（双反斜杠那批务必单独验）
- [ ] `automation_runtime_state.last_error` 已清空
- [ ] **`workspaces.path` 与 `sessions.cwd` 盘符大小写已统一**（两表小写盘符计数 = 0，
      精确匹配率 = 100%），且复核语句用 `substr(...)` 而非 `LIKE`（见坑 10）
- [ ] **`projects/` 正文目录已核对**：缺正文的工作区用 `repair_conversation_bodies.py --dry-run`
      列清单，能从老机器拿到 `projects` 目录的用 `--src` 导入
- [ ] `-wal` 已 checkpoint 归零（改完后再做一次）
- [ ] `corrupt-*` / `recovery-pending` 已归档
- [ ] 备份目录路径已告知用户
- [ ] 已提醒用户**重启 WorkBuddy**（客户端有内存缓存，不重启看不到效果）
- [ ] 已报告（只报告不擅改）：`PAUSED` 状态、过期 `validUntil`、异常 `rrule`、
      `scheduleType` 与 `rrule` 冲突（如 `once` + `HOURLY`）、乱码/重复目录
- [ ] 已明确告知：老会话**正文**（jsonl）若本机不存在则不可恢复，但会话**元数据**已修复

### 二次导入（第七步）额外必查

- [ ] **没有跑包里的 `restore-new-pc.sh`**（或跑之前已确认它是合并式版本）
- [ ] 包内三个 zip 都做了**逐文件字节比对**：缺失 0；唯一的"大小不符"能解释（本机版本更正确）
- [ ] 导入后 `workspaces` **无重复 path**、无老用户名、无小写盘符、**无死路径**
- [ ] **每个空间都有正文目录**，逐空间 `会话数 ≤ 正文 jsonl 数`
- [ ] 为「有正文但缺索引」的 cwd **补建了空目录 + workspace**（否则对话在界面上看不到）
- [ ] 技能**逐文件 MD5 比对**过（不是只比文件数）；真冲突项已合并并在打磨记录里写明
- [ ] `skills/*/__pycache__` 已清理，无同基名多版本技能
- [ ] 已告知用户：包内 `03-配置与连接`（凭据/连接器）与 `01-身份与记忆` **未覆盖**，
      因本机版本更新；如需启用旧机器的连接器配置需单独确认
