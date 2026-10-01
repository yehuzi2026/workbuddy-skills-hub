---
name: wusun-cockpit
description: 维护与迭代 wusun-auction 项目「商务销售全局驾驶舱」大屏（ECharts 数据看板）的专用技能。当用户要求修改驾驶舱的指标口径（如把「开票/报价」改成「询价/纯销」等真实业务口径）、地图星星与涟漪、省份点击下钻市级地图、平台卡片网格、趋势图，并按生产流程部署到 root@<阿里云服务器公网IP>（pm2 wusun-app）、用 browser-act 实拍验证时使用。本项目强约束：大屏数据必须基于真实后端业务逻辑聚合，禁止 mock。
agent_created: true
---

# 商务销售全局驾驶舱（wusun-cockpit）

维护 wusun-auction 管理后台「仪表盘 / 商务销售全局驾驶舱」大屏迭代 + 部署 + 验证的完整工作流。

## 何时使用

- 用户发来参考图，要求「做一个同款驾驶舱大屏」或「调整大屏的某个模块」。
- 用户要求改指标口径：如「开票数据改成询价数据」「纯销改成结案金额」「单位改成元 / 件」。
- 用户要求改地图（星星大小/涟漪、点省份下钻城市、返回全国）、平台卡片、趋势图、品类图、重点单品图。
- 用户要求部署到生产并截图验证。

**铁律**：大屏所有数字必须来自后端 `/api/dashboard` 对真实业务表的聚合，严禁前端写死 mock 数据。参照样例图只能学视觉，数据口径必须对齐本项目数据库。

## 项目位置与结构

- 项目根目录：当前工作区内的 `wusun-auction/`（用 Glob 确认；历史路径形如 `C:\Users\Administrator\WorkBuddy\<日期>\wusun-auction`）。
- 关键文件：
  - `server.js` — Express 后端，含 `GET /api/dashboard`（约 955–1227 行）聚合接口。
  - `public/dashboard.js` — 大屏前端渲染（KPI、地图、平台卡片、品类、重点单品、趋势）。
  - `public/index.html` — 大屏 DOM 结构与 CSS（深蓝磨砂卡片、荧光青绿 #00f2ff、橙 #ff9f1c、黄星 #ffd60a）。
  - `public/vendor/china.json` — 全国 GeoJSON（已内置，避免外网依赖）。
  - `public/vendor/geo/<adcode>_full.json` — 33 省市级 GeoJSON（下钻用）。
- 生产：Alibaba Cloud `root@<阿里云服务器公网IP>`，`/opt/wusun-app`，pm2 进程 `wusun-app`（端口 3000），nginx 反代 `https://ws.aicnpor.cn/`。

## 架构总览

- 数据流：浏览器 `dashboard.js` → `fetch('/api/dashboard')` → `server.js` 聚合 `inquiries / quotations / cases_close / repairs` 四张表 → 返回 JSON → 前端 ECharts 渲染。
- 表结构与接口字段契约见 `references/schema.md`，改接口前先读。
- 权限隔离：`requireAdmin` 中间件注入 `req.admin`；`dashInqScope(admin)` 按 `role` 自动加 WHERE：
  - `platform` → 全量；`city` → `WHERE i.city=?`；`region` → `WHERE i.city=? AND i.assignee_id=?`。**所有查询必须套用 `scope.where` + `scope.params`**，否则越权。

## 常见改动模式

### 1. 改 KPI 口径（如「开票 → 询价」）
- 后端在 `server.js` 的 `/api/dashboard` 内：把 SQL 源表/字段/列名改掉，并同步改 `kpi.*.name` 文案与 `unit`。
- 当前实现：本月/本年「询价」用 `SUM(i.survey_amount)`（inquiries 定损金额），「纯销」用 `SUM(c.settlement_amount)`（cases_close 结案金额），单位 `元`。
- 若用户要「询价单数（件）」而非金额，则改 `COUNT(*)` 并去掉 `unit:'元'`、把"定损金额"相关文案改"单数"。
- 前端 `dashboard.js` 的 KPI/趋势/品类/平台卡片标题里若残留「开票」字样，一并替换（grep `开票` 全量检查）。

### 2. 地图星星 + 涟漪
- 星星用 `type:'scatter', symbol:'star'`（**不能用 effectScatter+'star'，会变方块**）。
- 叠加 `type:'effectScatter'` 做涟漪，`rippleEffect:{brushType:'stroke',scale:3.2}`。
- 由 `buildStarSeries(name, data, size)`（dashboard.js ~195 行）统一生成；改大小只调 `size` 参数（全国 4.5 / 城市 8）。
- 星星坐标来自 `CITY_COORDS`（省份中心点，~383 行）；缺失省份需补坐标否则不显示。

### 3. 省份点击下钻市级地图
- `initMap()` 加载 `/vendor/china.json` 后建 `PROV_ADCODE`（省简称→adcode）与 `PROV_SHORT`（全名→简称）。
- `onMapClick` 仅在全国视图（`mapMode==='map'`）响应，调 `renderProvince(short)`。
- `renderProvince` fetch `/vendor/geo/<adcode>_full.json` → `echarts.registerMap` → 用 `DATA.map.detail[<省>]` 渲染城市 map + 星星。
- 返回全国：`#map-back` 按钮 → `freshChart()` + `renderChina()`。**`freshChart()` 必须先 `mapChart.dispose()` 再 `init`，否则返回后画布空白**（已踩坑）。
- 深链验证：`?drill=湖北` 进入后自动下钻（绕过 canvas 点击限制）。

### 4. 平台卡片网格
- `initPlatform()`（~423 行）把保险公司渲染为可滚动卡片网格（`.hex-wrap` 圆角矩形，含名称/实际值元/已结案元/进度条/完成率%）。
- 数据来自 `DATA.platform`（后端按 `i.insurer` 分组，actual=询价额、settled=结案额）。后期保险公司多，保持可滚动，不要改回固定六边形。

## 部署流程

1. 在 `wusun-auction/` 改完代码后，打包（排除 node_modules/.git）：
   ```
   cd <wusun-auction>; tar -czf ../wusun-app-deploy.tar.gz --exclude=node_modules --exclude=.git .
   ```
2. 运行 `scripts/deploy_cockpit.py`（自包含：上传 + 解压到 `/opt/wusun-app` + `npm install --omit=dev` + `pm2 restart wusun-app`，保留 uploads/wusun.db 与既有口令）。
3. 脚本读取环境变量 `SSH_PW`（**不要硬编码密码**）。运行前：`export SSH_PW="<root口令>"`（口令存于用户记忆，按需取用）。
4. 脚本末尾自动 `curl` 验证本地 3000 与公网 `https://ws.aicnpor.cn/` 的 HTTP 状态。

> 全量重装（清 node_modules、跑 server-setup.sh、重置口令）用 `deploy_run.py`；日常迭代用 `deploy_update.py`/`scripts/deploy_cockpit.py` 增量更新。

## 验证流程（browser-act 实拍）

- 用 browser-act 打开 `https://ws.aicnpor.cn/dashboard.html`（或管理后台仪表盘入口），登录后截图核对。
- 坑：browser-act daemon 重启会清空 Allow Full Access 授权，导致 230331；需用户在 WorkBuddy 手动重开授权（关→开）。**细化（2026-08-12 实测）**：开会话 + 登录通常可用，但登录 `eval` 触发 `location.reload()` 后，后续 `eval`（含 `fetch` 的复杂命令）/ `screenshot` 会**间歇性**被 230331 拦截；疑似授权态随 reload 失效或会话命令配额。属**环境级**问题，非代码缺陷。区域管理员视图实拍截图因此未能完成，但其前端逻辑与市管理员**同源同路径**（`isPlatform()===false`），数据隔离已由 API 严格证明，可不阻塞交付。
- 登录表单不稳定时，用 `eval` 注入账号密码 + `location.href` 跳转，比 `input/click` 可靠。
- canvas 省份点击无法用坐标触发，验证下钻用 `?drill=省份` 深链。
- 至少验证：全国视图渲染、星星+涟漪、点省份下钻、返回全国不空白、平台卡片完整滚动、KPI 数字来自真实数据。

## 已知坑（必看）

1. **地图外网加载失败**：曾用 `geo.datav.aliyun.com` 被拒 → 改内置 `/vendor/china.json` + `/vendor/geo/<adcode>_full.json`。新增省份下钻务必先确认该省 GeoJSON 已落地。
2. **黄星方块**：`effectScatter` 不支持 `symbol:'star'` → 拆成 `scatter`(star) + `effectScatter`(涟漪) 两层。
3. **返回全国空白**：`freshChart()` 未 dispose 旧实例 → 渲染到失效 canvas。先 `mapChart.dispose()` 再 `init`。
4. **平台卡片截断**：固定六边形只露 3 个 → 改可滚动卡片网格（见上文）。
5. **数据隔离**：任何新查询都要接 `scope.where/params`，否则 platform 账号能看到别的城市数据。
6. **数字必须真实**：前端任何 `value:` 都来自 `/api/dashboard` 返回值，禁止写死。
7. **地图省份不上色/「点击没反应」**：后端 `map.provinces[].name` 是**简称**（湖北），而 GeoJSON 区域名是**全称**（湖北省）。`type:'map'` series 的 `data.name` 必须精确等于 GeoJSON 区域名才能按值分级着色 + hover 高亮，否则整图回落 `outOfRange` 色（深蓝）、看起来"没变化"。**点击下钻逻辑本身没坏**（`onMapClick` 用 `shortProv()` 兜底，点返回全名/简称都能解析下钻）。修复：前端用 `PROV_FULL`（简称→全称）把 series data.name 对齐 GeoJSON；`initMap` 遍历 china.json 时填充 `PROV_FULL` 并补 `PROV_SHORT[short]=short`。改 `map.provinces` 命名口径时务必同步此映射。
8. **部署脚本验证 URL 过时**：`deploy_cockpit.py` 末尾验证 `dashboard.html` 在生产返回 404（真驾驶舱在 `/index.html`，无 dashboard.html 文件）。验证用 `https://ws.aicnpor.cn/index.html` 返回 200 + 引用 `dashboard.js?v=N` 版本号即可，404 属误报。
9. **sql.js 本地副本库序列化丢数据**：用 `db.export()` 生成副本 DB 再 `fs.writeFileSync` 时，`Buffer.from(db.export())` 在 export 返回带 `byteOffset` 的 Uint8Array 时会**丢失写入内容**（文件里只剩部分表）。必须用 `const e=db.export(); Buffer.from(e.buffer, e.byteOffset, e.byteLength)`。本地验证务必在写盘后**单独进程读回校验**用户/数据行数。
10. **地图自动聚焦读 `DATA.map.provinces[0].name`，绝非 `VIEWER.city`**：`inquiries.city` / `sys_user.city` 存的是**城市名**（如「武汉市」），而后端 `map.provinces[].name` 是**省份简称**（如「湖北」）且已按 scope 过滤。非平台视图 `startChina()` 应下钻到 `DATA.map.provinces[0].name`；若拿 `VIEWER.city`（"武汉市"）去匹配 `PROV_ADCODE`（按省建）会匹配不到、地图不聚焦。
11. **本地样例库 `wusun.db` 可能为空**：源库不一定有 inquiry 数据（实测 0 条 inquiries、1 用户）。做隔离验证需自建隔离副本库并注入样例工单（武汉市含 `assignee_id` 指派 + 福州市用于证明跨市隔离），且 DB 路径用 `DB_PATH` 环境变量指向副本，端口用 `PORT` 隔离，绝不碰生产/原库。

## 参考文件

- `references/schema.md` — 四张表关键字段、`/api/dashboard` 完整返回结构、数据隔离规则、省份/城市解析正则。
- `scripts/deploy_cockpit.py` — 自包含增量部署脚本（读 `SSH_PW` 环境变量）。
