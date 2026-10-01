# 致命坑详解与修正方法（受限共享主机 PHP 子系统）

提炼自 `cn.wuhanhonganghang.cn` 落地过程。每个坑都附「现象 → 根因 → 修正 → 验证」。

---

## P1 · WTS-WAF 剥离 multipart/form-data 字段 → 上传一律 base64 JSON

**现象**：前端 `FormData` 上传图片，后端 `$_FILES` 全空，`$_REQUEST['action']` 连 URL query 都拿不到；curl 隔离测试证明 GET/JSON 模式正常，唯 multipart 下全空。

**根因**：本环境 WTS-WAF 对 multipart 请求做了字段剥离（连 query string 的 action 都抽掉），整个 multipart 文件上传不可用。历史"验收"其实没真测 multipart。

**修正**：上传改用 **JSON + base64** 通道（与 login 同通道，WAF 不剥离）。
- 前端：`FileReader` 把 File 读成 base64 → `{action:'image_upload', vehicle_id, image_type, images:[{name, data:base64}]}` → POST JSON 到 `index_router.php`。
- 后端（vehicle_image.php upload 分支）：**模式 A 优先解析 base64 数组**，`base64_decode($item['data'], true)` 写盘；保留模式 B multipart 兼容但不依赖。

```php
// 后端 upload 模式A（推荐通道）
$rawImages = insu_get_post('images', null);
if (is_array($rawImages) && count($rawImages) > 0) {
    foreach ($rawImages as $item) {
        $name = $item['name'] ?? ('upload.' . ($item['ext'] ?? 'jpg'));
        $ext = strtolower(pathinfo($name, PATHINFO_EXTENSION));
        if (!in_array($ext, ['jpg','jpeg','png','gif','webp'])) continue;
        $bin = base64_decode($item['data'] ?? '', true);
        if ($bin === false || strlen($bin) === 0) continue;
        if (strlen($bin) > 10 * 1024 * 1024) continue;       // 10MB 上限
        $subDir = substr(md5($vehicleId), 0, 2);
        $dir = UPLOAD_BASE . '/' . $subDir;
        if (!is_dir($dir)) mkdir($dir, 0777, true);
        $fname = $vehicleId . '_' . time() . '_' . rand(1000,9999) . '.' . $ext;
        if (file_put_contents($dir . '/' . $fname, $bin) === false) continue;
        // 入库 url / local_path ...
    }
}
```

**验证**：Playwright 真浏览器多选 2 张图 → 上传队列显示「✅ 成功」→ 图片网格 0→2 → 无 console 错误。

---

## P2 · WTS-WAF 剥离 JSON/raw POST 体 → 入站写操作走 form-encoded

**现象**：前端 `fetch` 发 `application/json` 或 `fetch(..., {body: JSON.stringify})`，后端 `php://input` 为空，`insu_get_post` 拿不到任何字段。

**根因**：WAF 只对 `application/x-www-form-urlencoded` 可靠投递；JSON/raw 体被剥离。

**修正**：所有**入站写操作 / 推送接收**用 form-encoded。前端 `URLSearchParams` 或 `key=val&key2=val2` 字符串，`Content-Type: application/x-www-form-urlencoded`。**出站**（如推送给 PICC/第三方）不受影响，可按对方要求用 JSON。

**验证**：curl 用 `-X POST -d "action=xxx&token=...&k=v"`（带浏览器 UA）能正常拿到字段；同样内容用 `-H "Content-Type: application/json" -d '{"action":..."}'` 后端收空。

---

## P3 · FTP cwd=`/` 而 IIS 根=`wwwroot/` → manifest 远程路径加前缀

**现象**：`ftp_put_robust.py` 输出 `OK -> insurance/admin/app.js`，但 web 仍是旧版（IIS 读 `wwwroot/insurance/admin/app.js` 大小未变）；curl 校验线上文件缺新标识。

**根因**：FTP 用户登录后 cwd 是 `/`，不是 `/wwwroot/`。`STOR insurance/admin/app.js` 落到 `/insurance/admin/`（孤立目录），IIS 服务根仍是 `/wwwroot/`。

**修正**：manifest 远程路径**必须以 `wwwroot/` 前缀**。

```
# manifest 格式：本地相对路径<空格>远程路径(含 wwwroot/ 前缀)
insurance/admin/app.js    wwwroot/insurance/admin/app.js
insurance/api/quote.php   wwwroot/insurance/api/quote.php
```

**验证**：部署后 `curl -A "浏览器UA" http://域名/insurance/admin/app.js | grep -c "新版本关键标识"`，必须为 1，**不能只信 ftp 脚本的 OK 输出**。

---

## P4 · CDN 缓存 / 浏览器缓存 → 改完页面仍是旧版（空白/旧逻辑）

**现象**：部署新 `dashboard.php`/`app.js`，浏览器打开仍空白或旧逻辑；Vue 红错覆盖全屏。

**根因**：(a) 浏览器/WAF 缓存了旧版含 `vue@4.1.2` 的页面，Vue4 与 EP2.x provide/inject 不兼容导致 el-form 渲染崩塌；(b) 没加缓存防护头。

**修正**：**缓存三重防护**——
1. PHP 响应头：`header('Cache-Control: no-store, no-cache, must-revalidate');`
2. HTML `<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">`
3. 所有 CDN URL 加 `?v=x.y.z` 锁版本：`vue@3.4.21` + `element-plus@2.7.0`（**Vue 锁 3.x 不要 4.x**）。

**验证**：浏览器 **Ctrl+Shift+R 强刷**；curl 看响应头含 `no-store`；CDN URL 带 `?v=`。

---

## P5 · PDO 链式调用 500 → 两步式

**现象**：`$pdo->prepare($sql)->execute($params)->fetch()` 直接 500（execute 返回 bool，无 fetch 方法）。

**修正**：必须两步式。

```php
$st = $pdo->prepare($sql);
$st->execute($params);
$row = $st->fetch();          // 或 fetchAll()
```

`lastInsertId()` 该环境常返回 0 → 插入后回查真实 id（`ORDER BY id DESC LIMIT 1` 或 `WHERE 唯一键`）。

---

## P6 · 角色隔离画太死 → 某角色看不到功能入口

**现象**：超级管理员登录后看不到报价输入框（当时截图反馈"没有可以报价的端口"）——输入框被 `<div v-if="!isSuper">` 屏蔽，只剩超管的"汇总对比"。但后端 `quote.php::submit` **根本无角色限制**，纯前端 v-if 误挡。

**修正**：
- 前端 `v-if` 角色隔离**前先 grep 后端对应 action 是否真有限制**。若后端无限制，就别在 UI 层硬屏蔽。
- 超管常需自己也能用某功能（演示 / 审价 / 覆盖定价）——把"通用能力"放永远渲染区，"汇总/定标/仲裁"等超管专属放 `v-if="isSuper"`。

```html
<!-- 通用区：所有登录用户都能报价 -->
<el-card><el-input v-model="quoteForm.quote_amount" type="number"/>...<el-button @click="submitQuote">提交报价</el-button></el-card>
<!-- 超管专属：汇总对比 + 终选 + 中标 + 对外API -->
<div v-if="isSuper"> ... </div>
```

**验证**：用三种角色 token（super_admin / 普通管理员 / 报价员）各跑一遍 API 确认都能走通对应动作。

---

## P7 · 临时脚本 / 测试数据残留 → 安全与数据污染

**现象**：临时清理脚本、迁移脚本留在 web 目录可公网访问；测试数据污染生产。

**修正**：
- 临时脚本（迁移/seed/cleanup）通过 FTP put 上传 → 跑完用 **ftplib `encoding='latin-1'`** 删线 → `curl` 验 404 → 删本地 + 部署清单。
- 业务数据删除用软删 `UPDATE ... SET is_deleted=1`（DB 入口 `hg_insu_pdo()`，非 `insu_db`）。
- FTP 删除必须用 latin-1（欢迎语含非 UTF-8 字节，否则 `'utf-8' codec can't decode`）。

```python
import ftplib, os
f = ftplib.FTP(timeout=30); f.encoding = 'latin-1'
f.connect('wuhanhonganghang.cn', 21); f.login(FTP_USER, FTP_PASS)
f.delete('/wwwroot/insurance/api/_cleanup_xxx.php')   # 注意 /wwwroot/ 前缀
f.quit()
```

**验证**：`curl -s -o /dev/null -w "%{http_code}"` 应为 404。

---

## P8 · 初始账号表空 → 登录失败

**现象**：install 脚本只建表未插初始管理员 → 登录报"用户不存在"。

**修正**：用 `INSERT IGNORE` 幂等种子脚本补齐初始账号（admin / 普通账号），密码用 `md5('默认密码')` 与主站约定一致；跑完即删种子脚本。

---

## P9 · 函数未定义 / 重复声明 → FATAL

**现象**：`Call to undefined function`（路由 require 模块时偶发）、`Cannot redeclare successResponse()`。

**根因**：
- 辅助函数塞在文件末尾 `if(!function_exists){...}` 块，被路由 require 时作用域/顺序疑虑导致偶发未定义。
- 根 `helpers.php` 与模块内 `helpers.php` 都 define 同名函数，require 顺序反了 → redeclare。

**修正**：
- 模块需要的辅助函数**裸定义于文件顶部**（如 `reindex_files`），不要塞进 `if(!function_exists)` 块。
- require 顺序：先 require 根公共 helpers，后 require 带 `function_exists` 守卫的鉴权文件；反序即 redeclare。

---

## P10 · Vue 版本不兼容 → 红色错误覆盖全屏

**现象**：`Cannot read properties of undefined (reading 'rules')`，el-form 渲染崩塌，整页空白。

**修正**：锁定 **Vue 3.4.21 + Element Plus 2.7.0**。Vue4 与 EP2.x 的 provide/inject 不兼容；CDN URL 必须带 `?v=` 锁版本（见 P4）。校验顺序：先 node --check 语法 → 再用 Playwright 真浏览器看 console 无错。

---

## P11 · 前端 `api()` JSON.stringify 对象参数 → 后端收到字符串（数组/对象解析陷阱）

**现象**：前端 `api('member_assign', { material_ids: [1,2,3] })` 或 `api('sheet_forward', { recipients: ['a@b.com'] })` 发出后，后端 `wsbj_get_post('material_ids')` 拿到的是**字符串** `"[1,2,3]"` / `"[\"a@b.com\"]"`，不是数组。`is_array` 判假 → 直接 `$ids = []` 或 `filter_var` 全失败 → 「分配后会员看不到物资」「确认转发报收件邮箱无效」。E2E 里若用 `urllib.parse.urlencode` 发 Python list，则会被扁平化为 `material_ids=1`（单元素）或 `material_ids=1&material_ids=2`（多元素，PHP 收为字符串）——同样不是数组。

**根因**：统一 `api()` 助手把所有 params 对象 `JSON.stringify` 后再塞进 form 字段走 form-encoded（见 P2 为何走 form-encoded）。`wsbj_get_post` 只读 `php://input` 解码后的 JSON 或 `$_REQUEST`，返回**原始值**，不会把 `"[1,2,3]"` 自动解成数组。

**修正**：凡后端接收「数组/对象」型入站参数，先尝试 `json_decode`，失败再兜底。统一范式：

```php
$ids = wsbj_get_post('material_ids', []);
if (!is_array($ids)) {
    $dec = json_decode($ids, true);            // 前端 JSON.stringify 来的字符串
    $ids = is_array($dec) ? $dec : array_filter(array_map('trim', explode(',', (string)$ids)), fn($x)=>$x!==''); // urlencode 扁平串兜底
}
$ids = array_values(array_unique(array_filter(array_map('intval', $ids), fn($x)=>$x>0)));

// 收件人数组同理
$recipients = wsbj_get_post('recipients', []);
if (!is_array($recipients)) {
    $dec = json_decode($recipients, true);
    $recipients = is_array($dec) ? $dec : [$recipients];
}
```

**验证**：E2E 同时覆盖「前端 JSON.stringify 字符串」与「urlencode 扁平串」两种入站（或直接发 `json.dumps([...])`），断言关联表写入行数 / `filter_var` 通过数 > 0。

**教训**：共享主机 PHP 子系统里，前端 `api()` 传的任何对象/数组，后端都必须做「JSON 字符串 → 数组」兜底解码，不能假设 `is_array` 成立。

---

## P12 · Vue3 模板 `v-for` + `v-if` 同位 → 整页白屏 (`item is undefined`)

**现象**：dashboard / 任一 SPA 页面登录后整页空白（`#app` 完全空），但 Vue mount 本身成功、无 4xx，**`pageerror` 报 `Cannot read properties of undefined (reading 'xxx')`**。`console` 警告 `[Vue warn]: Property "item" was accessed during render but is not defined on instance`。

**根因**：Vue3 官方明确：**`v-if` 优先级高于 `v-for`**。所以下面的写法是错的：

```html
<!-- ❌ 错：v-if 在 v-for 之前求值，item 还未生成 → undefined.roles 抛错 → SPA 全崩 -->
<div v-for="item in m.items" :key="item.key"
     v-if="!item.roles || item.roles.includes(me.role)" ...>
```

**修正（vue3 推荐写法）**：

```html
<!-- ✅ 对：用 <template v-for> + 子节点 v-if，循环变量在 v-if 子作用域中可见 -->
<template v-for="item in m.items" :key="item.key">
  <div v-if="!item.roles || item.roles.includes(me.role)" ...>
    ...
  </div>
</template>
```

或把过滤抽成 `computed`（推荐，可缓存、可读性更好）：

```js
const visibleItems = (m) => (m.items || []).filter(it => !it.roles || it.roles.includes(me.role));
```

```html
<div v-for="item in visibleItems(m)" :key="item.key">...</div>
```

**诊断 SOP（共享主机/普通 Windows 服务器都适用）**：

1. 当 SPA 白屏时，先用 `playwright`（或类似 headless）+ 真实 `wsbj_token` 注入 `storage_state` 进 dashboard。
2. `page.on("pageerror", ...)` + `page.on("console", ...)` 抓所有错误 —— 一次 `pageerror` 通常就给出 Vue compile error 或 render function crash 的真因。
3. 不要被 Vue 的 `errorHandler` 沉默骗了，**`pageerror` 监听器** 才能稳定捕获。
4. 修完后用同一个 playwright 脚本走通「dashboard → 物资列表 → 详情」全路径，断言 `innerText` 非空、`pageerror` 为 0。

**教训**：Vue3 模板里**绝对禁止** `v-for` 与 `v-if` 写在同一标签上。CDN 模式下更无 build-time 警告兜底，必手动审视。

---

## P13 · 子域根直达子系统（web.config 按 Host rewrite，门户零改动）

**现象**：门户（车拍拍）+ 多个子系统（保险 / 物资 / 损余）共享同一 wwwroot。想让 `cn.wuhanhonganghang.cn/`（根）直接呈现某个子系统（如保险登录页 `insurance/admin/index.html`），但门户是独立网站、文件一点不能动。直接覆盖 `index.html`/`index.php` 必然破坏门户。

**根因**：根域名只能有一个默认文档行为。门户入口其实是 `wwwroot/index.php`（按 HTTP_HOST 分发的根路由，默认分支 `readfile(brand.html)` → 车拍拍门户），所有子域共享此文件。IIS 默认文档顺序是 `index.php` 优先于 `index.html`——所以误传的 `index.html` 不会生效（门户仍由 index.php 提供）。按"改默认文档 / 覆盖 index"思路必动门户。

**修正（门户零改动）**：在 `wwwroot/web.config` 的 `<rewrite><rules>` 里加一条**按 Host 条件**的规则，只匹配根路径，内部重写（Rewrite，非 Redirect，地址栏仍是干净的 `cn.wuhanhonganghang.cn/`）到子系统入口静态页。门户主域不匹配，照常走 index.php → brand.html。

```xml
<rule name="cn-insurance-entry" stopProcessing="true">
  <match url="^$" />
  <conditions>
    <add input="{HTTP_HOST}" pattern="^cn\.wuhanhonganghang\.cn$" ignoreCase="true" />
  </conditions>
  <action type="Rewrite" url="/insurance/admin/index.html" />
</rule>
```

- `match url="^$"` 只匹配根（空路径），`/insurance/...`、API 等深层路径不受影响。
- 子系统登录页/前端资源须用**绝对路径**（如 `/insurance/api/login.php`、`/favicon.ico`、CDN `https://`），否则重写后相对路径会 404。
- 规则放最前 + `stopProcessing="true"`，避免与现有 wsbj 等子域规则冲突。
- 此模式可照搬：`wsbj.wuhanhonganghang.cn` 就是用同样写法 `Rewrite url="/wsbj/{R:1}"` 实现子域隔离。

**验证（缺一不可）**：
- `curl http://cn.wuhanhonganghang.cn/` → 返回子系统页（grep 子系统特征串，如「武汉宏刚行科技」），且**不含**门户串（如「车拍拍」）。
- `curl http://主域/` → 仍返回门户（title 不变、未误变子系统）。
- `curl -o /dev/null -w '%{http_code}'` 根/主域均 200（web.config 语法错会全站 500）。

**教训**：共享主机多子系统共存时，"二级域名直接到某子系统"用 web.config 按 Host rewrite 最干净——门户零改动、地址栏不变、深层路径正常。绝不要覆盖 `index.php` / `brand.html` / 任何门户文件。

---

## P14 · 登录页明文暴露默认 admin/admin123 → 等于公开钥匙挂在门上

**现象**：登录页底部小字写着 "初始账号：admin / admin123（超级管理员）" 或类似。访客任意访问登录页即可看到默认凭据，等于把管理员钥匙挂在门上——任何搜索引擎蜘蛛/扫端口的脚本都能直接看到，凭它就能登入。

**根因**：开发时为了让客户/测试方便，把默认账号写在登录页提示里，**没有意识到登录页对所有未登录访客都是公开可见的**。默认凭据只能在 SQL 初始化脚本注释、DBA 文档、运维 wiki 等**非公开渠道**出现。

**修正**：登录页（含子系统的"登录对话框"——如 dashboard 内 token 失效跳出的对话框）禁止明文显示默认账号密码，改为中性提示：

```html
<!-- ❌ 危险：暴露凭据 -->
<div class="login-tip">初始账号：admin / admin123（超级管理员）</div>

<!-- ✅ 正确 -->
<div class="login-tip">忘记密码？请联系系统管理员重置</div>
```

**自检命令**（新建子系统部署后**必跑**）：

```bash
grep -rn "初始账号\|admin / admin123\|admin/admin123" deploy_src/
# 预期：除 SQL 初始化脚本注释外，其余残留 = 必须清理
```

**检查清单**：
- 登录页底部 tip 区
- 登录对话框（dashboard 内 token 失效弹窗）
- 子系统会员登录页（wsbj 等）
- README/技术文档里也尽量避免明文（用占位符如 `<your-admin-password>`）

**教训**：默认凭据只在**第一次部署运维交接时**明文说一次，之后任何对外可见的页面（登录页/注册页/帮助页）都不能再写明文。要么中性提示"请联系管理员"，要么引导用户走"忘记密码"流程。

