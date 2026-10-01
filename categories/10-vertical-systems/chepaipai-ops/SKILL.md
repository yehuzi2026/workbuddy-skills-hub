---
name: chepaipai-ops
description: 车拍拍车辆拍卖平台（武汉宏刚行科技 wuhanhonganghang.cn）的运维、后台登录验证与端到端功能/业务链路测试。当用户要登录 wuhanhonganghang.cn 管理后台、对车辆拍卖系统做功能冒烟测试，或做端到端写操作验证（新增车辆→审批→拍卖→出价→订单→保证金）时使用。
---

# 车拍拍运维与测试（chepaipai-ops）

## 项目关键事实（务必先看）
- 公司：武汉宏刚行科技发展有限公司
- 平台：车拍拍（车辆拍卖 / 损余物资拍卖）
- 主域名：**wuhanhonganghang.cn**（拼写：wu+han+hong+ang+hang；⚠️ 不是 honggang；不是 wuhanhonghang）
- 技术栈：PHP（原生，非完整 ThinkPHP 框架落地）+ 原生 HTML/JS 前端 + IIS + Windows + MySQL 5.7.44；虚拟主机 vhostgo.com
- 线上部署根：FTP `/wwwroot/`；管理后台 `/wwwroot/admin/*.html`；API `/wwwroot/api/*.php`
- 登录入口：`http://wuhanhonganghang.cn/admin/login.html`（新版也可 `admin/index.html`）
- 会员入口：`http://wuhanhonganghang.cn/member/index.html`
- 测试账号（默认密码 123456）：
  - 超管后台：`test_super_admin / 123456`
  - 会员：`testbid1 / 123456`
  - ⚠️ 登录页默认预填 `admin / admin123`（疑似真实超管账号，慎改慎删）
- FTP 凭据、数据库信息等敏感配置**见项目 MEMORY.md（2026-05-08-task-16/.workbuddy/memory/MEMORY.md），本 skill 不硬编码**

## ⚠️ IIS 虚拟主机关键坑（必读）
- `php://input` 不可用 → POST JSON body 读不到。所有写操作必须：数据走 **URL 查询参数** + 请求头加 `Content-Length: 0`。
- 前端用 `apiPostUrl()` 这类封装发 URL 参数请求。
- HTTP 访问必须带 `User-Agent`，否则 403（curl/urllib 需 `-H "User-Agent: Mozilla/5.0"`）。

## 能力一：登录后台并冒烟测试全部功能
用 browser-act（chrome 本地模式，无需 Key）：
1. `browser-act daemon restart`
2. `browser-act --session <名> browser open chrome_local_110551285826060520 <登录页或dashboard url> --allow-restart-chrome`
3. 若跳登录页：填 `test_super_admin` / `123456` 登录；dashboard 直访通常靠 localStorage 持久化登录态（daemon 重启清 session 但 profile 保留登录态）。
4. 提取全部菜单链接：
   `eval JSON.stringify([...document.querySelectorAll('a[id^=menu],.menu-item')].map(a=>({t:a.innerText.replace(/\s+/g,'').trim(),h:a.getAttribute('href')})))`
5. 遍历每个 `admin/<href>`：navigate → wait stable → eval 提取 `document.body.innerText` 长度 + 错误关键词（错误/Error/undefined/加载失败/404）。

13 个功能页面（2026-08-06 实测均可用）：dashboard, vehicle-list, vehicle-audit, auction-list, quote-list, order-list, member-list, deposit-list, finance, user-list, insurance-config, baosi-jianguan, settings。

冒烟结果已知问题（供回归比对）：
- finance.html 在今日/本月收入均为 ¥0 时仍显示「较昨日 +12%」「较上月 +8%」——疑似占位数据，需确认是否接真实统计。
- 车辆审批页右上角显示角色名「超级管理员」，其余页显示账号「test_super_admin」——角色/账号显示不一致。
- 「保证金管理」菜单图标在不同页面渲染为 💰 / 🏦 不一致（视觉，不影响功能）。

## 能力二：端到端写操作验证（业务链路打通）
目标链路：**新增车辆 → 审批通过 → 创建拍卖 → 会员出价 → 成交生成订单 → 保证金冻结/解冻**。
- 全程用明显测试标记（如车牌 `端到端TEST001`、备注"E2E验证"）便于事后清理。
- 每一步后用 `network requests --type xhr,fetch` 抓取 API 响应，确认 `code===0/200` 且数据真实入库（再回到列表页核对新增行）。
- 重点确认（05-18 开发时遗留、验证时优先查）：
  - 手动车辆（insurance_company=manual）审批通过后 status → `auctioning`（直通拍卖）。
  - 拍卖创建 API、初始 status（即将开始/拍卖中）、起止时间字段、关联车辆字段。
  - 会员出价是否冻结保证金（表 / 金额来源）。
  - **订单何时生成**：手动"结束/确认成交"按钮？cron？还是未实现（05-18 时订单结算链路是待办）。这是端到端最容易断链点，优先确认触发入口。
- 验证后清理：删除测试车辆/订单/拍卖（注意外键），恢复数据干净。

## 线上真实 API 参数约定（2026-08-07 实测，curl 直调验证）
本项目线上 API 均为 **POST + URL 查询参数 + `Content-Length: 0` 头**（IIS 兼容，php://input 不可用）。**线上 wwwroot 是运行态真源（部署产物）**：本地 `2026-05-08-task-16/honggang-php-platform/api/` 与线上 `wwwroot/api/` 核心文件 MD5 一致（m06/m02/member_api/vehicle 等），本地是完整 monorepo 源码真源；线上 `wwwroot/honggang-php-platform/` 是一套废弃副本，**勿同步**。
- **新增车辆**：`POST /api/vehicle.php?vehicle_no=&vin=(17位,除I/O/Q)&brand=&model=&year=&vehicle_type=&insurance_company=manual&source=manual&estimate_price=` → `{success:true,data:{vehicle_id,status:"pending_audit"}}`
- **审批**：`POST /api/vehicle_audit.php?action=approve&vehicle_id=<id>`（⚠️参数名是 `vehicle_id` 不是 `id`）→ 手动车 status→`auctioning`
- **删除车辆**：`POST /api/vehicle_delete.php?id=<id>`
- **拍卖会 M06**（`m06_auction_api.php`）：`create_auction`(vehicle_id,start_price,min_increment,start_time,end_time→返回id)；`publish&id=`→active；`end_auction&id=`→ended(返回winner_id/final_price)；`update_auction_status&id=&status=`(pending/active/ended/settled/cancelled，**无物理删除，仅可取消**)；`place_bid`(**auction_id+bid_price**；`member_id`/`bidder_id`/`user_id` 三者兼容，必传其一否则拒绝出价；**已修复**：bid_id 返回真实值、bidder_id 正确落库 hg_auction_bid)；`list_auction`/`auction_detail&id=`
- **竞价引擎 M02**（`m02_bidding_engine.php`）：`bid` 参数名未探明（四种传参均报"拍卖会ID和出价不能为空"）；`settle_auctions&auction_id=` 结算已结束拍卖生成订单（需 winner_id≠0 才有产出）；`active_auctions`/`bid_list`
- **会员**：`/api/member_admin.php?action=list`→`data.items[]`(含 id/deposit_balance)；`/api/member_api.php` 直接访问 **HTTP 500（线上 bug）**
- **状态机**：拍卖会 `pending→active→ended→settled`，可 `cancelled`。

## 能力三：FTP 拉取 / 部署线上真源
- 主机即域名 `wuhanhonganghang.cn`（西部数码虚拟主机，FTP 欢迎语含非 UTF-8 字节）。`ftplib` 必须**两步构造**：`f=ftplib.FTP(); f.encoding='latin-1'; f.connect(); f.login()`（**latin-1** 是 GBK/UTF-8 超集最稳；构造即连会在读欢迎语时 UTF-8 解码崩溃，故必须先建对象再设 encoding 再 connect）。PowerShell 的 `Write-Host` 在 FTP 流下会被吞，一律用 Python `ftplib` 写 FTP 脚本。
- 工作区 `ftp_sync.py`：`list <远程目录>` / `sync <远程目录> <本地目录> [--dry] [--all]`（默认跳过 uploads/images/大文件）/`put <本地文件> <远程文件>`（上传部署）。
- 密码经环境变量 `FTP_HOST/FTP_USER/FTP_PASS` 传入，脚本不硬编码。
- 线上 wwwroot 完整快照已拉到工作区 `live_snapshot/`（322 文件/4.2MB）；改后 `put` 上传即部署（live_snapshot 原版即备份）。

## 注意
- 这是**生产环境**，写操作会进真实库。务必用测试标记并事后清理，或在隔离测试库验证。
- browser-act daemon 重启会清掉 session（session 由 daemon 托管）；重开会话后 localStorage 登录态通常仍在（profile 持久化）。
