---
name: chepaipai-ops-playbook
description: 车拍拍(wuhanhonganghang.cn)线上运维排障实战手册——沉淀自 2026-08-13 一轮实战：业务闭环写操作验证(38/38 synthetic JWT)、FTP 非UTF-8连接与孤儿文件清理SOP、PDO两步式铁律与列名陷阱、鉴权双表机制、后台菜单角色权限bug。当用户要对该平台做端到端写验证、清理线上孤儿文件、定位PHP 500、或排障后台/会员登录时使用。
agent_created: true
---

# 车拍拍运维排障实战手册（chepaipai-ops-playbook）

> 配套总览见 `chepaipai-ops`（功能清单/登录入口/API 参数约定）。本 skill 只收**实战踩坑与可复用 SOP**。
> 平台速查：域名 `wuhanhonganghang.cn`；FTP 同域名；库 `wuhanhgh06` 前缀 `hg_`；JWT secret `honggang_php_platform_jwt_secret_2026`（HS256，仅验签名不查库）。

## 何时用本 skill
- 要做**带真实写操作**的业务闭环验证（新增车辆→审批→拍卖→出价→订单→保证金）。
- 要**清理线上孤儿/遗留 PHP 文件**（先备份再删）。
- 遇到 **PHP 500 / IIS 报错**要定位根因。
- 后台或会员端**登录/菜单异常**要排障。

## ⚠️ FTP 实战坑（2026-08-13 实测，必看）
1. **主机欢迎语含非 UTF-8 字节** → 标准 `ftplib.FTP()` 构造即 connect 会因 UTF-8 解码崩溃。
   正确姿势（两步构造）：
   ```python
   import ftplib
   f = ftplib.FTP()
   f.encoding = 'latin-1'   # latin-1 是 GBK/UTF-8 超集，最稳；GBK 也可但 latin-1 兜底最安全
   f.connect(host)
   f.login(user, pass)
   ```
   ❌ 不要 FTP 子类化覆盖 `getline` 再 `FTP(subclass)()` 构造——`__init__` 内部先 connect 仍走基类解码。必须"先建对象→设 encoding→再 connect"。
2. **PowerShell `Write-Host` 在 FTP 流操作下输出会被吞**（无 Stdout，连 `exit 1` 都看不到诊断）。→ 一律用 Python `ftplib` 写 FTP 脚本，输出稳定可见。
3. **始终带浏览器 UA**：WTS-WAF 拦截默认 UA → 403。HTTP/curl 验证务必 `curl -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"`。

## 孤儿文件清理 SOP（先备份再删，绝不裸删）
- 前提：确认**无当前前端引用** + **grep 部署清单**（`deploy_manifest.txt` / `deploy_a.txt` / `deploy_b.txt`）无该文件路径，否则下次部署会传回。
- 四步：
  1. 用 `ftplib` 下载备份到本地 `backups/<file>.bak`；
  2. `f.delete(remote_path)`（或 `DELE` 命令）→ 期望 `250 command successful`；
  3. 复验：`f.retrbinary`/下载应抛 `550 文件找不到` → 确认消失；
  4. `curl` 线上地址应 **HTTP 404** → 确认 Web 层也访问不到。
- 本轮已按此清理：`/api/login.php`（缺 `HG_DB_PASS` 常量 500）、`/wwwroot/api/services/api/login.php`（安全报告标"遗留端点·待清理"）。两者均为会员端/遗留孤儿，删后业务不受影响（会员走 `member_api.php`、后台走 `admin_login.php`）。

## 业务闭环写操作验证 SOP（38/38 通过）
- **绕过真实登录**：用已知 JWT secret 铸 synthetic member/admin token（`authenticate_token()` 只验签名不查库 → 可过 `bid.php`/`material_bid.php`/`m01` 鉴权；`admin_auth.php` 要求 payload `admin===1`）。
- **直传参数端点**：`m16_deposit_api.php` 完全不用 token，直接读 `user_id`（不存在自动建户）；`m03`/`m05`/`payment` 可直传 `user_id`。
- **驱动顺序（真实写操作，务必按此闭环）**：
  `M16 充值` → `M01 加车(admin)` → `M06 建拍(pending)` → `publish(active)` → `会员 bid 出价` → `end_auction 中标(冻结保证金)` → `M05 建订单(buyer_id)` → `payment notify 回调(mock,解冻)` → `M16 保证金账户`。
- **断言与稳健性**：每步断言 `code` + 数据真实落库；先确认连通性 0 个 500 再上写操作；`10054` 偶发 → `call()` 加重试；报告用 f-string（禁用 `%` 拼接含 `%` 的 CSS）。
- 测试脚本 `biz_loop_test.py` 即此模式的落地：用 synthetic JWT 串起全链路写操作。

## ⚠️ PDO 两步式铁律
- `$pdo->prepare($sql)->execute($params)->fetch()` 会 **500**（`execute` 返回 bool，无 `fetch` 方法）。**必须拆两步**：
  ```php
  $st = $pdo->prepare($sql);
  $st->execute($params);
  $row = $st->fetch();
  ```
- 该 IIS 主机**把 PHP 警告当致命错误** → 任何 `Undefined array key` / `Undefined constant` 都直接 500（不是 warning 而是 fatal）。

## 列名陷阱速查（避免再踩，已修 + 已验证）
- `hg_order`：`member_id`（非 `user_id`）、`update_time`（非 `updated_at`）。
- `hg_auction_bid`：无 `proxy_max_price`，只有 `is_proxy`；`real_name` 不在 `authenticate_token()` 返回数组（只有 id/username/phone/user_type/tenant_id）→ 用 `??` 兜底。
- `hg_payment` / `hg_deposit_account` / `hg_deposit_record`：用 `updated_at`。
- `hg_auction`：`update_time`（非 `updated_at`）。
- `m03 submit_quote`：`lastInsertId()` 该环境返回 **0** → 报价实际已入库，需回查真实 id：`SELECT id ... WHERE inquiry_id=? AND quoter_role=? ORDER BY id DESC LIMIT 1`，否则 `set_final_quote` 拿不到 `quote_id` 阻断「报价→终价」子链路。

## 鉴权实战（双会员表，不互通）
- `hg_user`（受管：`login.php` / JWT / payment / m03，字段 `role`=`user_type`/`tenant_id`）与 `hg_member`（`bid` / m06 / m07 / m14，字段 `id`/`real_name`/`phone`）**两表不互通**。
- **会员真实登录页是 `/login.html` 调 `/api/member_api.php`**（不是 `/api/login.php` 孤儿）。曾因：① 线上 `hg_db.php` 被覆盖成受管版（只定义 `hg_pdo()`、缺 `HG_DB_DSN`）→ 500；② `member_api.php:29` 用 `$_INPUT['username'] ?:` 在未定义键上触发警告 → 500。**修复**：部署 `deploy_src/api_member/hg_db.php` 超集（定义 `HG_DB_DSN/USER/PASS` + `hg_pdo`，零回归）+ 把 `?:` 改 `??`。现注册 200、真实手机号登录 200、错误密码 401。
- `/login.html:344` 有前端 mock 兜底（`catch` 里弹"登录成功（模拟）"），后端正常时已不触发，仅作错误兜底，未改。
- `m16_deposit_api.php` 完全不用 token，直接读 `user_id` 参数（不存在自动建户）。

## 后台菜单角色权限 bug 排障
- **症状**：后台进去只剩"数据看板"一个菜单，其余全消失。
- **根因**（旧版 `/admin/dashboard.html`）：有 `ROLE_PERMISSIONS` 系统，`getUserRole()` 从 localStorage 读 `user_info.role`，缺失 → 降级为 `'admin'` 角色（权限表仅 `dashboard:true`，其余全 `false`）→ 除数据看板外菜单全 `display:none`。
- **修复**：用新版 `admin.html`（Vue3 + Element Plus，13 菜单**全量显示、无角色隐藏逻辑**）覆盖 `/wwwroot/admin/dashboard.html` 与 `/wwwroot/admin.html` 两路径 → 两路径都成完整后台。
- **关键提醒**：用户访问路径可能与你部署路径不同（`/admin.html` 与 `/admin/dashboard.html` 是**两个独立文件**）。改菜单前先 `curl`/`grep` 确认线上实际生效的是哪个文件，否则会"改了 A 但用户看 B，以为没生效"。

## 注意（生产环境）
- 写操作进真实库，务必用测试标记（车牌 `端到端TEST001`、备注"E2E验证"）并事后清理，或在隔离测试库验证。
- M04 真资金流仍阻塞：①商户凭证(APPID/商户号/密钥)未填 ②主机仅 HTTP(80) 无 HTTPS，异步回调 notify_url 收不到支付成功通知。代码层去模拟化已完成（`payment_gateway.php` + `getPaymentConfig` 灰度 `real=false` 默认 mock），填凭证并把 `real` 置 true 即一键真接通。
- 详细功能清单/登录入口/API 参数见 `chepaipai-ops` skill。
