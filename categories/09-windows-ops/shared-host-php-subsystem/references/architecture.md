# 架构蓝图与范式（受限共享主机 PHP 子系统）

提炼自 `cn.wuhanhonganghang.cn` 保险报价系统（17 表、全套业务跑通）。

## 1. 目录结构（线上 = deploy_src 镜像到 wwwroot 子目录）

```
deploy_src/insurance/               # 单一部署真源，重部署只推这一组
├── admin/
│   ├── index.html                  # 登录页（host 守卫跳入）
│   ├── dashboard.php               # 看板 SPA 壳（CDN 引入 + 缓存防护 + 登录态门）
│   └── app.js                      # Vue3 + Element Plus 内联模板 SPA（~1400 行）
├── api/
│   ├── index_router.php            # 前端统一入口（action 翻译 → require 模块）
│   ├── _db.php                     # 独立 PDO 连接（hg_insu_pdo()）
│   ├── _auth.php                   # JWT 鉴权 insu_current_user() / require_admin
│   ├── _helpers.php               # 函数集（取参/CORS/PDO封装/PDF/审计）
│   ├── lib/insu_pdf.php           # 纯 PHP CJK PDF 生成器（InsuPDF + insu_generate_quote_pdf）
│   ├── login.php vehicle.php quote.php vehicle_image.php external.php system.php ...
│   └── storage/uploads/            # 图片落盘（按 vehicleId md5 前两字符分桶）
└── sql/                            # 建表 + 种子 DDL（幂等）
```

**铁律**：绝不改主站已存在文件；子系统用独立前缀（如 `hg_insu_`）+ 独立子目录，与主站/其他子系统零冲突。

## 2. 统一路由 index_router.php（模块零改动核心）

前端所有读写 POST `{action:'quote_submit', ...}` 到该文件，路由把前缀 action 翻译成裸 action 后 `require` 模块：

```php
<?php
require_once __DIR__ . '/_auth.php';
require_once __DIR__ . '/_helpers.php';
insu_cors();
$rawAction = insu_get_post('action', $_GET['action'] ?? '');
$route = [
    'quote_list'    => ['quote.php', 'list'],
    'quote_submit'  => ['quote.php', 'submit'],
    'image_upload'  => ['vehicle_image.php', 'upload'],
    'login'         => ['login.php', 'login'],
    // ... 每个前端 action => [模块文件, 模块内部裸 action]
];
if (isset($route[$rawAction])) {
    [$file, $bare] = $route[$rawAction];
    $GLOBALS['INS_ROUTED_ACTION'] = $bare;
    $_REQUEST['action'] = $bare;          // 让模块内 insu_get_post('action') 读到
    require_once __DIR__ . '/' . $file;
    exit;
}
echo json_encode(['code' => 400, 'msg' => '未知 action: ' . $rawAction], JSON_UNESCAPED_UNICODE);
```

模块文件内部结构（裸 action 分发）：

```php
<?php
require_once __DIR__ . '/_auth.php';
require_once __DIR__ . '/_helpers.php';
insu_cors();
$action = insu_get_post('action', $_GET['action'] ?? '');   // 被路由注入为裸 action
if ($action === 'list') { /* ... */ exit; }
if ($action === 'submit') {
    $user = insu_current_user();
    // 角色限制写在这里，不要依赖前端 v-if（见 P6）
}
```

## 3. 数据库：单库前缀隔离 + 软删

```sql
-- 所有业务表带 is_deleted 软删 + created_at；幂等可重复执行
CREATE TABLE IF NOT EXISTS hg_insu_quote (
  id INT AUTO_INCREMENT PRIMARY KEY,
  vehicle_id INT NOT NULL,
  admin_id INT NOT NULL,
  quote_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  remark VARCHAR(500),
  is_final TINYINT DEFAULT 0,
  is_deleted TINYINT DEFAULT 0,
  created_at DATETIME, updated_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- 删除一律 `UPDATE ... SET is_deleted=1`（物理删除在共享主机易误伤）。
- DB 入口只用 `hg_insu_pdo()`（每个子系统独立连接配置，**不复用**主站 `config/database.php`）。

## 4. 前端 SPA：CDN 无构建范式（dashboard.php 头部）

```html
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">  <!-- P4 缓存防护 -->
<!-- 主源 jsdelivr + 兜底 bootcdn；URL 锁版本 ?v= -->
<script src="https://cdn.jsdelivr.net/npm/vue@3.4.21/dist/vue.global.min.js"></script>
<script>if(typeof window.Vue==='undefined'){document.write('<script src="https://cdn.bootcdn.net/ajax/libs/vue/3.4.21/vue.global.min.js"><\/script>');}</script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/element-plus@2.7.0/dist/index.css">
<script src="https://cdn.jsdelivr.net/npm/element-plus@2.7.0/dist/index.full.min.js"></script>
<script>if(typeof window.ElementPlus==='undefined'){document.write('<script src="https://cdn.bootcdn.net/ajax/libs/element-plus/2.7.0/index.full.min.js"><\/script>');}</script>
```

- `app.js` 用 `Vue.defineComponent({ props, setup() { ... return {...} }, template: '...' })` 内联模板。
- **setup 的 return 必须包含模板引用的所有顶层变量**，否则 `reading 'xxx'` TypeError；Vue errorHandler 会"吞掉"渲染错误造成假象 → 改完用 `node --check` + Playwright 验证。
- 所有路径绝对化（`/insurance/api/...`、`/insurance/storage/...`）。
- 登录态门：`dashboard.php` 顶部读 `localStorage.insu_token`，无则 `replace('index.html?redirect=...')`。

## 5. 子域根直达（不碰主站 web.config）

主站 `wwwroot/index.php` 或 `wwwroot/home.html` 加 host 守卫：

```php
if (strpos($_SERVER['HTTP_HOST'] ?? '', 'cn.') === 0) {
    readfile(__DIR__ . '/insurance/admin/index.html');   // 跳保险登录页
    exit;
}
```

根默认文档顺序把 `home.html` 设为跳转页最稳，主站品牌官网零影响。若要让 `cn.` 根直达子系统看板，需西部数码控制台把子域主机目录绑到 `/wwwroot/insurance/admin/`（方案 A，零风险）。

## 6. 鉴权（_auth.php 要点）

- JWT 签发（登录成功）：payload 写 `admin=1` / `role`。密钥单点常量。
- `insu_current_user()`：解码 JWT → 返回用户数组（id/role/real_name）。
- `require_admin` 开关：super_admin 放行，普通管理员按 `created_by` 归属校验（如只能给自建车辆上传图）。

## 7. PDF 生成器（lib/insu_pdf.php）—— 零依赖中文 PDF

- 纯 PHP 实现（不依赖 FPDF/composer），引用阅读器内置 **Adobe-GB1** 中文字体（UniGB-UCS2-H），**无需嵌入字体文件**，体积小。
- 用法：`insu_generate_quote_pdf($vehicle, $quotes, $decider, $mode)` → 返回 `['pdf_url'=>...]`；或直接 `new InsuPDF()` 调 `text/kv/table/paragraph/output`。
- CJK 编码：`utf8ToUcs2Hex()` 把 UTF-8 转 UCS2-BE hex 喂给 Adobe-GB1。
- 输出目录建议 `storage/pdfs/`，URL 拼 `INSU_SITE . '/insurance/storage/pdfs/xxx.pdf'`。
