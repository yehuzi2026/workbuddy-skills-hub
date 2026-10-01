# 车拍拍生产库取数备忘（做统计表用）

## 环境

| 项 | 值 |
|---|---|
| FTP | `wuhanhonganghang.cn`，用户 `wuhanhgh06`，**密码会轮换，以用户当次提供为准** |
| 临时脚本目录 | `/wwwroot/_seed2025/`（只放诊断/一次性脚本，已存在） |
| 库 | MySQL 5.7，库名 `wuhanhgh06` |
| 库配置 | `/wwwroot/api/config/database.php`（`$cfg['master']`） |
| 保险子系统 | `cn.wuhanhonganghang.cn`，**同库不同表**，用 `hg_insu_` 前缀；页面 JWT secret `honggang_php_platform_jwt_secret_2026`，默认 admin/admin123 |

**本机没有 PHP / MySQL / Docker** → 取数只能：写 PHP 脚本 → FTP 上传 → HTTP 触发（`curl`）。

## 连接片段（照抄）

```php
function hg_pdo() {
    $cands = [__DIR__ . '/../api/config/database.php', __DIR__ . '/../../api/config/database.php'];
    $cfg = null;
    foreach ($cands as $c) { if (file_exists($c)) { $cfg = require $c; break; } }
    $conn = $cfg['master'] ?? ($cfg['connections']['admin'] ?? null);
    $dsn = sprintf('mysql:host=%s;port=%s;dbname=%s;charset=%s',
        $conn['host'] ?? 'localhost', $conn['port'] ?? 3306,
        $conn['dbname'] ?? $conn['database'], $conn['charset'] ?? 'utf8mb4');
    return new PDO($dsn, $conn['username'], $conn['password'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
}
```

## 关键表 / 字段

- `hg_vehicle` — 车辆主表
  - `vehicle_no` = **车牌**（如 `湘A6044B`，唯一）；`brand` 品牌；`location` = **省份**（仅省，无市）
  - `status`：`auction_success` 成交 / `auction_failed` 流拍 / `auctioning` 在拍
  - `create_time` 上拍时间；`deal_price` 成交价；另有 `series/model/year/mileage/owner_*/vin/regist_no/engine_no` 等
- `hg_auction` — 拍卖会（`auction_no` 唯一，`winner_id`→会员，`final_price`）
- `hg_auction_bid` — 出价（`status='active'` 才是前端 bid_count 统计口径）
- `hg_order` — 订单（`order_no` 唯一）
- `hg_member` — 会员（`level`：NORMAL / VIP / SVIP；手机号唯一）
- `hg_insu_vehicle` — 保险系统车辆（`vehicle_no` 格式 `INSU+yyyymmdd+序号`，`plate_no` 存车牌，`status=pending_quote`）

## 2025 全年 500 台数据集（已成事实，可直接引用）

- `create_time` 落在 2025-01-01 ~ 2025-12-31 的车辆 = **500 台**
- 状态：成交 400 / 流拍 70 / 在拍 30
- 省份：湖北 138(110) / 湖南 85(65) / 河南 84(69) / 江西 74(61) / 四川 64(52) / 广东 20(14) / 江苏 11(10) / 福建 9(7) / 浙江 8(6) / 山东 7(6)（括号内为成交数）
- 月度（上拍）：1月36 2月39 3月39 4月55 5月46 6月48 7月43 8月42 9月34 10月39 11月41 12月38
- 品牌 Top：丰田26 吉利22 长城22 比亚迪20 宝马19 别克18 日产18 现代18 本田17 领克16 大众16 …
- 保险系统侧：同一批 500 台已写入 `hg_insu_vehicle`（5→505），`is_winning=1` 400 台

## 一键取数脚本

`diag_stats.php`（已上传 `/wwwroot/_seed2025/`），输出按 品牌/省份/状态/月份 四维聚合的 JSON：

```bash
curl -s "http://wuhanhonganghang.cn/_seed2025/diag_stats.php"
```

改维度只需改里面的 `GROUP BY`；**注意 `grp()` 必须读 `$r['k']`**（SQL 是 `xxx AS k`）。
