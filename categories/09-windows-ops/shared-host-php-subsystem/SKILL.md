---
name: shared-host-php-subsystem
description: "Guidance for building a self-contained business subsystem (admin SPA plus PHP backend) on a constrained shared hosting environment such as Western Digital IIS virtual host with PHP 8.2, a single MySQL database using prefix-based logical isolation, and a WTS-WAF that strips multipart and JSON POST bodies. Use this skill when scaffolding a new isolated web app, backend module, or admin dashboard on such a host, or when hitting characteristic pitfalls like FTP wwwroot path offset, WAF field stripping, CDN cache poisoning, PDO two-step, and role-gating UI bugs."
agent_created: true
---

# 受限共享主机 · PHP 子系统构建方法论

## 适用环境特征（命中即用）

在以下受限环境从零搭建独立业务子系统（后台管理 + 前端 + 数据库）时，加载本技能：

- **主机**：西部数码 IIS 虚拟主机，PHP 8.2，**web root = `/wwwroot/`**，仅 HTTP(80)，跑不了 Java / 常驻进程 / Redis / Swoole / ES。
- **数据库**：与已有系统**共享同一 MySQL 实例与库**（如 `wuhanhgh06`），只能靠**表前缀逻辑隔离**（如 `hg_insu_`），不能物理分库。
- **WAF**：WTS-WAF 会**剥离 multipart/form-data 字段**与**剥离 JSON/raw POST 体**，只把 `application/x-www-form-urlencoded` 可靠投递给 PHP。
- **部署**：仅能通过 FTP 上架文件，FTP 登录后 cwd 是 `/`（不是 `/wwwroot/`）。
- **前端**：无构建工具，直接用 **Vue3 + Element Plus 的 CDN**（不带打包器）。

> 案例佐证：本方法论提炼自 `cn.wuhanhonganghang.cn` 独立保险报价系统的完整落地（17 张表、登录/建档/多管理员报价/终审定标/PDF/中标/对外API/系统设置 全套跑通）。

## 何时使用

- 用户说"在现有主机上再做一个 XX 系统/后台/小程序管理端"、"搭一个独立的 XX 模块"。
- 用户在受限 IIS 主机上开发 PHP 应用，遇到上传失败、部署后仍是旧版、页面空白、POST 收不到参数等典型症状。
- 需要纯 PHP 零依赖生成中文 PDF（无法装 composer 包）。

## 核心架构蓝图（详见 references/architecture.md）

构建时遵循这套分层，避免与生产系统冲突：

1. **文件包隔离**：所有代码放在独立子目录（如 `deploy_src/insurance/` → 线上 `/wwwroot/insurance/`），绝不改动主站已有文件。
2. **后端公共库**：`_db.php`（独立 PDO 连接）、`_auth.php`（JWT 鉴权 + 当前用户）、`_helpers.php`（函数集：取参 `insu_get_post`、PDO 封装、CORS、`insu_cors`、PDF、审计）。
3. **业务模块**：每个领域一个 `.php`（如 `vehicle.php` `quote.php`），内部用裸 `insu_get_post('action')` 分发。
4. **统一路由 `index_router.php`**：前端单一入口，把前缀化 action（`quote_submit`）翻译为裸 action（`submit`）后 `require` 模块文件——**模块零改动**。
5. **前端 SPA**：`admin/index.html`（CDN 引入 + 缓存防护）+ `admin/app.js`（Vue3 `defineComponent` 内联模板，所有路径绝对化）。
6. **存储与 PDF**：图片落 `storage/uploads/`（按 vehicleId md5 分桶）；PDF 用纯 PHP CJK 生成器（引用 Adobe-GB1，零字体嵌入）。

## 完成流程（按此顺序，不要跳步）

1. **数据库设计**：画 ER + 写幂等 DDL（所有业务表带 `is_deleted` 软删、`created_at`）。选好前缀（如 `hg_insu_`）。
2. **公共库**：先写 `_db.php` / `_auth.php` / `_helpers.php`。鉴权函数设 `--requireAdmin` 开关。
3. **业务模块**：按领域写 php，每个 action 显式校验角色（super_admin / 普通），避免"后端无限制却被前端 v-if 误挡"（见坑 P6）。
4. **统一路由**：把所有前端 action 映射到 `[模块文件, 裸action]`。
5. **前端 SPA**：CDN 用锁定版本（`vue@3.4.21` + `element-plus@2.7.0`）+ 双源 fallback（jsdelivr 主 + bootcdn 兜底）+ **缓存三重防护**（见坑 P4）。
6. **PDF / 存储**：纯 PHP 生成器 + base64 上传通道（见坑 P1）。
7. **子域/根直达**：用主站 `index.php`/`home.html` 的 host 守卫跳转到子系统登录页（避免改主站 web.config）。
8. **部署**：FTP 上架（manifest 远程路径**必须含 `wwwroot/` 前缀**，见坑 P3）+ curl 校验线上含新标识。
9. **验证**：API 端到端（带浏览器 UA）+ 浏览器强刷（Ctrl+Shift+R）。测试数据用临时清理脚本软删（见坑 P7）。

## 致命坑速查（完整修正方法见 references/pitfalls.md）

| ID | 现象 | 修正 |
|----|------|------|
| **P1** | 文件上传 500 / `$_FILES` 全空 / action 拿不到 | WAF 剥离 multipart → **上传一律走 JSON+base64**（前端 FileReader 转 base64，后端优先解 base64 写盘） |
| **P2** | JSON POST 后端收不到任何字段（`php://input` 空） | WAF 剥离 JSON/raw 体 → 入站写/推送改 `application/x-www-form-urlencoded` |
| **P3** | FTP 报 OK 但 web 仍是旧版 | FTP cwd=`/`，IIS 根=`wwwroot/` → manifest 远程路径加 `wwwroot/` 前缀 |
| **P4** | 改完页面浏览器仍是旧版（空白/旧逻辑） | 缓存三重防护：PHP `header('Cache-Control: no-store')` + `<meta>` + 所有 CDN URL 加 `?v=x.y.z` 锁版本 |
| **P5** | PDO 链式 `$pdo->prepare()->execute()->fetch()` 500 | **两步式**：`$st=$pdo->prepare(); $st->execute(); $row=$st->fetch();` |
| **P6** | 某角色看不到功能入口（如超管无法报价） | 前端 `v-if` 角色隔离前，**先 grep 后端 action 是否真有限制**；超管常需自己也能用（演示/审价） |
| **P7** | 临时脚本残留 / 测试数据污染 | 用 FTP latin-1 删 + curl 验 404；数据软删 `is_deleted=1`；DB 入口 `hg_insu_pdo()` |
| **P8** | 登录失败（用户表空） | install 只建表未插初始数据 → 用 INSERT IGNORE 种子脚本 |
| **P9** | "Call to undefined function" / "Cannot redeclare" | 路由 require 顺序（先根 helpers 后 auth）；辅助函数裸定义于文件顶部，勿塞进 `if(!function_exists)` 块 |
| **P10** | Vue 红色错误覆盖全屏（el-form 崩） | 锁定 Vue3（非 Vue4）+ EP2.x，Vue4 与 EP2 provide/inject 不兼容 |
| **P11** | 分配/转发「收不到数组」→ 会员看不到物资 / 收件邮箱无效 | 前端 `api()` 把对象 `JSON.stringify` 成字符串发来 → 后端 `wsbj_get_post` 收到**字符串**，必须 `json_decode` 兜底再解（见下） |
| **P12** | dashboard/SPA 整页白屏、`pageerror: Cannot read properties of undefined (reading 'roles')` | Vue3 模板 **`v-for` 与 `v-if` 禁止同位**！`v-if` 优先级高于 `v-for`，item 在 v-if 求值时还是 undefined → render 全崩。用 `<template v-for>` + 子节点 `v-if`，或抽成 `computed` 过滤 |
| **P13** | 子域根直达子系统（如 `cn.`→保险页），门户零改动 | web.config 加按 Host 的 Rewrite 规则（`match url="^$"`）→ 内部重写到子系统静态页；不要覆盖 `index.php`/`brand.html` |
| **P14** | 登录页底部"初始账号：admin / admin123"明文暴露 | **登录页/登录对话框禁止明文默认凭据**——访客任意可看=公开钥匙挂门上。改"忘记密码？请联系系统管理员重置"；`grep -rn` 全仓库自检 |

## 如何用本技能

- 构建新子系统时，先读 `references/architecture.md` 拿目录骨架与路由/DB/CDN 范式，再从 `references/snippets.md` 复制可复用代码块（路由、base64 上传、PDF 调用、cleanup 模板）。
- 部署用自带 `scripts/ftp_put_robust.py`（逐文件独立连接 + latin-1 + 重试），manifest 格式为 `本地相对路径<TAB或空格>远程路径(含wwwroot/前缀)`。
- 遇到上传/POST/部署/缓存/500 等异常，先查 `references/pitfalls.md` 对应 P 编号，按修正方法改，不要凭直觉重写。
- 验证纪律：部署后必须 `curl -A "浏览器UA"` 校验线上文件含新版本关键标识；临时脚本跑完即删并 404 验证；测试数据按纪律软删。

## 验证清单（交付前自检）

- [ ] 所有业务表带 `is_deleted` + `created_at`，DDL 幂等可重复跑。
- [ ] 写操作后端有鉴权；前端角色隔离前已核对后端限制。
- [ ] 上传通道是 base64 JSON（非 multipart）；入站写操作是 form-encoded。
- [ ] FTP manifest 远程路径含 `wwwroot/`；curl 校验线上含新标识通过。
- [ ] CDN 锁版本 + 页面有缓存防护头；已提示用户强刷。
- [ ] PDO 全部两步式；辅助函数无重复声明 / 未定义。
- [ ] 临时脚本已删 + 404；测试数据已软删。
