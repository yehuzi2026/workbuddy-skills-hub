#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WorkBuddy 环境一键自检（workbuddy-migration-repair 技能配套）

检测项：
  1. 数据库健康（quick_check / 表计数 / WAL 悬空）
  2. 老用户路径残留（全库逐列扫描）—— 迁移后 "一使用就蹦" 的头号原因
  3. workspaces 索引（死路径 / 重复 / 与磁盘对账）
  4. sessions 目录登记文件残留
  5. automations 配置体检（PAUSED / 过期 validUntil / 异常 rrule / 类型冲突 / owner 字段错位）
  6. 崩溃与 EPERM 统计（区分「真病因」与「无关噪音」）

用法（务必用受管 Python 绝对路径，且本机 Git Bash 缺 coreutils）：
  set PYTHONIOENCODING=utf-8
  "C:/Users/<用户>/.workbuddy/binaries/python/versions/3.13.12/python.exe" selfcheck.py
退出码：0 = 全部健康；1 = 发现问题（详见输出）
"""
import io, os, sys, re, json, time, glob, sqlite3, collections, datetime

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

U = os.environ.get('USERPROFILE') or os.path.expanduser('~')
BASE = os.path.join(U, '.workbuddy')
DB = os.path.join(BASE, 'workbuddy.db')
ROOT = os.path.join(U, 'WorkBuddy')
CUR_USER = os.path.basename(U)          # 当前用户目录名，如 AHS
TS = re.compile(r'^20\d\d-\d\d-\d\d-\d\d-\d\d-\d\d$')

problems = []          # 需修复
warnings = []          # 只报告
notes = []

def sep(t):
    print('\n' + '=' * 76)
    print('  ' + t)
    print('=' * 76)

def ok(msg):   print('  [OK]   ' + msg)
def bad(msg):  print('  [BAD]  ' + msg); problems.append(msg)
def warn(msg): print('  [WARN] ' + msg); warnings.append(msg)
def info(msg): print('  [i]    ' + msg)

# ─────────────────────────── 1. 数据库 ───────────────────────────
sep('1. 数据库健康')
if not os.path.exists(DB):
    bad('找不到 %s' % DB)
    con = None
else:
    for f in ['workbuddy.db', 'workbuddy.db-wal']:
        p = os.path.join(BASE, f)
        if os.path.exists(p):
            info('%-20s %d B' % (f, os.path.getsize(p)))
    w = os.path.join(BASE, 'workbuddy.db-wal')
    if os.path.exists(w) and os.path.getsize(w) > 8 * 1024 * 1024:
        warn('WAL 已达 %.1f MB，建议 checkpoint：pragma wal_checkpoint(TRUNCATE)' % (os.path.getsize(w) / 1048576))
    con = sqlite3.connect(DB, timeout=30)
    con.execute('pragma busy_timeout=30000')
    try:
        r = con.execute('pragma quick_check').fetchone()[0]
        (ok if r == 'ok' else bad)('quick_check = %s' % r)
    except Exception as e:
        bad('quick_check 异常: %s' % e)
    for f in os.listdir(BASE):
        if 'corrupt' in f:
            warn('残留损坏备份 %s（数据库已健康则可归档）' % f)
        if f == 'workbuddy.db.recovery-pending':
            warn('存在 workbuddy.db.recovery-pending（恢复未了结标记，建议归档）')

# ─────────────────── 2. 老用户路径残留（全库扫描） ───────────────────
sep('2. 老用户路径残留（全库逐列扫描）')
RESID = 0
if con:
    tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    for t in tabs:
        cols = [r[1] for r in con.execute('pragma table_info("%s")' % t)]
        for c in cols:
            try:
                n = con.execute('select count(*) from "%s" where "%s" like \'%%users%%\''
                                % (t, c)).fetchone()[0]
            except Exception:
                continue
            if not n:
                continue
            # 找出非当前用户的 Windows 用户目录引用
            hits = collections.Counter()
            try:
                for (v,) in con.execute('select distinct "%s" from "%s" where "%s" like \'%%users%%\' limit 200'
                                        % (c, t, c)):
                    for m in re.finditer(r'[Cc]:[\\/]+[Uu]sers[\\/]+([A-Za-z0-9_.\-]+)', str(v)):
                        if m.group(1).lower() != CUR_USER.lower():
                            hits[m.group(1)] += 1
            except Exception:
                pass
            for user, cnt in hits.items():
                bad('%s.%s → 引用了非当前用户目录 C:\\Users\\%s（%d 处）' % (t, c, user, cnt))
                RESID += 1
    if RESID == 0:
        ok('全库无老用户路径残留')

# ──────────────────── 3. workspaces 索引 ────────────────────
sep('3. workspaces 索引导航')
if con:
    rows = list(con.execute('select path from workspaces'))
    dead = [p for (p,) in rows if not os.path.isdir(p.replace('/', os.sep))]
    dup = con.execute('select path, count(*) c from workspaces group by path having c>1').fetchall()
    slash = [p for (p,) in rows if '/' in p]
    info('共 %d 条' % len(rows))
    if dead:
        bad('死路径 %d 条（目录不存在）：%s' % (len(dead), dead[:3]))
    else:
        ok('无死路径')
    if dup:
        bad('重复路径 %d 条' % len(dup))
    else:
        ok('无重复')
    if slash:
        warn('含正斜杠路径 %d 条（会与主键不匹配）' % len(slash))
    if os.path.isdir(ROOT):
        disk = [n for n in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, n))]
        valid = [n for n in disk if TS.match(n) or n.startswith('automation-')]
        exist = {os.path.normcase(p) for (p,) in rows}
        miss = [n for n in valid if os.path.normcase(os.path.join(ROOT, n)) not in exist]
        info('磁盘工作区 %d（有效命名 %d），索引缺失 %d' % (len(disk), len(valid), len(miss)))
        if miss:
            warn('未入索引（新工作区会自动加入，非错误）：%s' % miss[:4])

# ─────────────────── 4. sessions 目录登记文件 ───────────────────
sep('4. sessions 目录登记文件')
SESS = os.path.join(BASE, 'sessions')
if os.path.isdir(SESS):
    files = glob.glob(os.path.join(SESS, '*.json'))
    hierr = 0
    for f in files:
        try:
            t = open(f, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        for m in re.finditer(r'[Cc]:[\\/]+[Uu]sers[\\/]+([A-Za-z0-9_.\-]+)', t):
            if m.group(1).lower() != CUR_USER.lower():
                hierr += 1
                break
    info('共 %d 个登记文件' % len(files))
    if hierr:
        bad('%d 个文件含非当前用户路径（客户端加载会话时会报错）' % hierr)
    else:
        ok('无老路径残留')
    if len(files) > 200:
        warn('登记文件偏多（%d 个），可能堆积了已退出进程的孤儿，可归档' % len(files))
else:
    info('sessions 目录不存在')

# ───────────────────── 5. automations 体检 ─────────────────────
sep('5. automations 配置体检')
if con:
    cols = [r[1] for r in con.execute('pragma table_info(automations)')]
    today = time.strftime('%Y-%m-%d')
    for r in con.execute('select * from automations order by created_at'):
        d = dict(zip(cols, r))
        name = d.get('name') or '?'
        tags = []
        uid = d.get('owner_user_id') or ''
        if uid.count('-') != 4:
            tags.append('owner_user_id 错位(= %r)' % uid)
        if (d.get('status') or '') == 'PAUSED':
            tags.append('已暂停')
        vu = d.get('valid_until') or ''
        if vu and vu[:10] < today:
            tags.append('validUntil 已过期(%s)' % vu[:10])
        rr = d.get('rrule') or ''
        if 'YEARLY' in rr and re.search(r'每日|每天|每小时', name):
            tags.append('rrule 异常(每年一次)')
        if (d.get('schedule_type') or '') == 'once' and 'HOURLY' in rr:
            tags.append('类型冲突(once + HOURLY)')
        blob = (d.get('cwds') or '') + (d.get('prompt') or '')
        if re.search(r'[Cc]:[\\/]+[Uu]sers[\\/]+(?!%s)[A-Za-z0-9_.\-]+' % re.escape(CUR_USER), blob):
            tags.append('路径残留')
        if tags:
            warn('%-34s %s' % (name[:32], ' / '.join(tags)))
        else:
            ok('%-34s 正常' % name[:32])

# ─────────────────── 6. 崩溃与 EPERM 统计 ───────────────────
sep('6. 崩溃与 EPERM 统计（区分真病因与噪音）')
dlog = os.path.join(BASE, 'logs', 'daemon.log')
if os.path.exists(dlog):
    kinds = collections.Counter()
    recent = collections.Counter()      # 近 30 分钟
    last = {}
    now = time.time()
    with open(dlog, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            for key, pat in [('自动化任务 EPERM（真病因：路径残留）', 'AutomationRunRuntime] executeRun failed'),
                             ('诊断日志写失败 EPERM（噪音，无关路径）', 'diagnostic log write failed'),
                             ('MCP discovery 失败', 'discovery failed for custom-mcp'),
                             ('node 不在 PATH (ENOENT)', 'spawn node ENOENT')]:
                if pat in line:
                    kinds[key] += 1
                    m = re.match(r'\{"timestamp":"([^"]+)"', line)
                    if m:
                        last[key] = m.group(1)
                        try:
                            t = datetime.datetime.fromisoformat(
                                m.group(1).replace('Z', '+00:00')).timestamp()
                            if now - t < 1800:
                                recent[key] += 1
                        except Exception:
                            pass
    if not kinds:
        ok('无相关错误')
    for k, c in kinds.most_common():
        still = recent.get(k, 0)
        mark = 'BAD' if ('真病因' in k and still) else 'i'
        print('  [%s]   %-42s 累计%4d 次  近30分%3d 次  最后 %s'
              % (mark, k, c, still, last.get(k, '?')[:19]))
    if kinds.get('自动化任务 EPERM（真病因：路径残留）') and not recent.get('自动化任务 EPERM（真病因：路径残留）'):
        ok('自动化 EPERM 为历史记录（近 30 分钟未再发生）—— 若已改路径，忽略即可')

crash = os.path.join(BASE, 'logs', 'Crash-Log')
if os.path.isdir(crash):
    cnt = collections.Counter()
    newest = ''
    for f in glob.glob(os.path.join(crash, 'crash-report-*.json')):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        cnt[d.get('processName', '?')] += len(d.get('entries', []))
        newest = max(newest, d.get('launchedAt', ''))
    info('崩溃报告累计：%s（最近一次启动 %s）' % (dict(cnt), newest[:19]))

if con:
    con.close()

# ─────────────────────────── 汇总 ───────────────────────────
sep('体检汇总')
print('  需修复 (BAD) : %d' % len(problems))
for p in problems:
    print('      - %s' % p)
print('  需关注 (WARN): %d' % len(warnings))
for w in warnings:
    print('      - %s' % w)
print()
if problems:
    print('  结论：发现问题，建议运行修复流程（见 SKILL.md 第二~六步）。')
elif warnings:
    print('  结论：无阻塞性问题，存在需关注的配置项。')
else:
    print('  结论：环境健康。')
print()
sys.exit(1 if problems else 0)
