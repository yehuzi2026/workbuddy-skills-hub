---
name: 驾驶舱规范
description: wusun-auction「商务销售全局驾驶舱」的硬性规范与契约（布局/财务闭环状态机/询价状态流/指标口径/导航注入/验证部署）。当用户修改驾驶舱、财务页、导航、询价状态，或复用本项目的财务状态机/回款率/导航注入写法时使用。与 wusun-cockpit（大屏视觉迭代+部署）互补——本技能只管规范与契约，不动视觉。触发词：驾驶舱规范、驾驶舱布局、财务闭环、回款率、回款凭证、状态流转、导航注入、系统设置、询价状态流、挂账、结案回款。
agent_created: true
---

# 驾驶舱规范（wusun-auction）

本项目（wusun-auction 物损拍卖/商务销售系统）驾驶舱相关开发的**强制规范与契约**。
任何改动不得违反以下规则，否则会破坏已上线的 P2（财务闭环）/P3（统计看板）/P4（状态流）闭环。

> **互补关系**：需要实际迭代大屏视觉/地图/部署看 `wusun-cockpit`。本技能只管**规范与契约**，不改视觉。

## 一、布局规范（铁律）

1. **大屏底部必须完全干净**：驾驶舱 `public/index.html` 底部禁止任何「系统维护」折叠条、底部 `padding-bottom` 占位、或任何遮挡大屏的元素。用户明确拒绝底部遮挡（截图反馈过）。
2. **系统维护 → 系统设置**：数据库备份功能必须抽成**独立页面** `public/system.html`（承载 `public/backup.js`），从左侧导航进入，**禁止**嵌入驾驶舱 DOM。
3. 导航顺序（nav.js 注入，固定）：`修改密码(settings.html)` → `系统设置(system.html)` → `中标归档(archive.html)`。

## 二、导航注入规范（public/nav.js）

- 所有入口用 `document.createElement` + `appendChild` **幂等注入**：每种入口先 `navEl.querySelector('a[href="xxx.html"]')` 判重，已存在则跳过（防重复）。
- 当前页高亮：`cur = location.pathname.split('/').pop() || 'index.html'`，匹配 `a.getAttribute('href') === cur` 加 `.active`。
- 注入顺序固定：会员管理(members.html) → 账号管理(accounts.html, 仅 platform 可见) → 修改密码(settings.html) → 系统设置(system.html) → 中标归档(archive.html)。
- **新增/调整导航项时**：必须加幂等判重分支 + 对应的 `cur===` 高亮分支，否则刷新会重复出现入口。

## 三、财务闭环状态机（server.js，铁律）

状态四态固定，顺序不可跳级：

```
挂账 → 待审批 → 已回款 → 结案回款
```

- 定义：`FIN_FLOW = { '挂账':'待审批', '待审批':'已回款', '已回款':'结案回款' }`（server.js ~836），`FIN_STATES` 同上四值。
- 状态流转端点 `POST /api/finance/:id/flow`：
  - 仅允许按 `FIN_FLOW` 顺序推进；越级返回 `状态流转不合法：当前「X」只能流转到「Y」`。
  - 流转到 `已回款` 或 `结案回款` 前，`receipt_photo` 必须非空，否则返回 `回款 / 结案回款前必须先上传回款凭证`。
  - 数据隔离：需 `inqInScope(req.admin, rec.inquiry_id)`，否则 403。
- **回款凭证端点 `POST /api/finance/:id/receipt`（关键坑，已修）**：
  - 只 `UPDATE finance SET receipt_photo=?, updated_at=datetime('now') WHERE id=?` —— **绝不改 status**。
  - 原代码曾直接置 `status='已回款'`，绕过「待审批」破坏闭环（已修复）。凭证可逗号拼接多张。
  - 文件校验：`<100MB`、扩展名 `jpe?g|png|gif|webp|bmp`，否则 `回款凭证需为图片` / 未收到文件返回 400；越权 `safeUnlink` 后 403。
- 编辑金额/备注 `PUT /api/finance/:id`：仅接受 `amount` / `remark` 字段，否则返回 `无可更新字段`（流转不可用 PUT）。
- **审批自动挂账 `ensureFinanceRecord(caseId, by)`**（server.js ~128）：结案审批通过时幂等生成 `挂账` 记录（amount=settlement_amount, status='挂账', created_by=by）。已有则跳过。
- **backfill**（`db.js init()`）：对历史 `cases_close` 中 `approval_status='已通过'` 且无 finance 记录者补挂账（created_by='backfill'），**防数字回退**。
- `kpi.finance` 字段（`GET /api/dashboard`）契约：
  - `pending` 挂账金额 / `pendingApproval` 待审批金额 / `received` 已回款 / `closed` 结案回款 / `total` 应收总额 / `rate` 回款率(%)。
  - **`received = status IN ('已回款','结案回款')`** 累计已收现（`closed` 单列结案回款，不并入 received 以免双计——按业务口径）。
  - `total = pending + pendingApproval + received`（应收 = 未收 + 已收）。
  - `rate = total>0 ? Number(((received/total)*100).toFixed(1)) : 0`。

## 四、驾驶舱指标渲染规范（public/dashboard.js + public/index.html CSS）

- 财务区 `getEl('platform-finance')` 渲染 6 行：应收总额 / 挂账 / 待审批 / 已回款 / 结案回款 / 回款率 + `.fin-bar` 进度条（`width: Math.min(100, rate)%`）。
- **回款率颜色阈值**（dashboard.js ~584）：`rate>=80 → fin-good(绿)` / `>=50 → fin-warn(黄)` / `<50 → fin-bad(红)`。新增指标沿用此三色阈值约定。
- 必需样式类（缺则补）：`.fin-title .fin-row .fin-label .fin-rate .fin-bar .fin-good .fin-warn .fin-bad`；`.stat-card.good` / `.warn` / `.money` 也需存在（曾缺 `.warn` 已补）。
- 数字单位统一 `元`，用 `fmtMoney()` 格式化。

## 五、询价状态流规范（public/inquiry.js）

- `STATUSES = ['待报价','待开标','已开标','驳回','报价失败','报价失效']`。
- **`报价失效` 与 `报价失败` 同义、向后兼容**（旧数据保持「报价失败」不迁移）；`canReject` / `FLOW_IDX` / `rejected` 同步包含两者。
- 后端 `POST /api/inquiries/:id/status` 接受任意字符串 status（无白名单）；前端负责展示契约。
- `public/search.html` 状态筛选 `<option>` 需同步加「报价失效」。

## 六、验证与部署规范（复用 wusun-cockpit 流程）

- **本地验证**：起独立测试库避免污染生产：
  `DB_PATH=/abs/path/_verify_test.db PORT=3999 node server.js`；改完对所有改动文件跑 `node --check`。
- **sql.js 跨进程内存坑**：直接用 `require('./db')` 插入的数据在 HTTP 服务端**不可见**（各进程独立内存 DB）。测试必须走**纯 HTTP 通道**（注册→审核→建单→设 owner→审批→查 API）。
- **Windows curl 中文乱码**：`decision:"通过"` 经 curl 会变乱码 → `非法的审批决定`。改用 Node `http` 模块发 UTF-8 Buffer，或 bash 内联 `python -c` 发请求。
- **登录**：`POST /api/admin/login`（`{username,password}`），返回 `Set-Cookie: admin_token`；受保护 API 带 `Cookie: admin_token=xxx`。
- **部署**：
  - 增量：`scripts/deploy_cockpit.py`（读 `SSH_PW` 环境变量，上传 + 解压到 `/opt/wusun-app` + `npm install --omit=dev` + `pm2 restart wusun-app`，保留 `uploads/wusun.db`）。
  - 全量重装：`deploy_run.py`（清 node_modules、跑 `deploy/server-setup.sh`、重置口令）。
  - 打包排除：`--exclude=node_modules --exclude='*.db' --exclude=uploads --exclude=backups --exclude=.git`。
  - `SSH_PW` 从 `HKCU:\Environment` 注册表读取（PowerShell `Get-ItemProperty -Path 'HKCU:\Environment' -Name SSH_PW`），写到临时文件用后即时删，**不要硬编码**。
- **上线验证**：`pm2 wusun-app online`；公网 `https://ws.aicnpor.cn/<file>` 返回 200；受保护 API 返回 401（鉴权生效）。

## 七、已知坑（必看，已踩）

1. receipt 端点曾直接置 `已回款` 破坏闭环 → 已改为只存凭证不改状态。
2. finance 用 PUT 传部分字段会被拒 → 流转用 `POST /flow`，编辑用 `PUT` 仅 amount/remark。
3. received 原只统计 `已回款` 漏掉 `结案回款` → 改 `IN ('已回款','结案回款')`（dashboard 与 server 一致）。
4. 大屏底部遮挡 → 系统维护移出成独立 `system.html`。
5. nav 注入不幂等会重复入口 → 必须 `querySelector` 判重。
6. sql.js 跨进程内存 → 测试走纯 HTTP。
7. Windows curl 中文乱码 → 用 Node http 发 UTF-8。

## 参考文件

- 后端：`server.js`（`/api/finance*`、`/api/dashboard`、`ensureFinanceRecord`、`FIN_FLOW`）、`db.js`（finance/notifications 表 + backfill）。
- 前端：`public/nav.js`、`public/dashboard.js`、`public/finance.html`+`finance.js`、`public/inquiry.js`、`public/system.html`（系统设置/备份）、`public/index.html`（大屏 CSS）。
- 互补技能：`wusun-cockpit`（大屏视觉/地图/部署迭代）。
