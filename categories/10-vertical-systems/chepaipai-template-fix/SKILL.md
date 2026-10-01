---
name: chepaipai-template-fix
description: 车拍拍(wuhanhonganghang.cn)前端 HTML in-DOM Vue 模板「自闭合 Element Plus 组件 /> 吞掉后续兄弟节点」坑的根治 skill。覆盖：现象识别、marker 二分定位法、批量改写为显式闭合（引号排除正则，防灾难性回溯）、逐面板 Playwright 上线验证、FTP 部署 + curl 回归。当用户要修复「Vue 代理数据正常但页面某区块不渲染、且零 JS 报错」、或对 dashboard.php / insurance/app.js 等前端做模板标签规范化扫描时使用。
agent_created: true
---

# 车拍拍前端模板自闭合吞节点 · 根治 skill（chepaipai-template-fix）

> 配套：`chepaipai-ops`（功能清单/登录入口/API 约定）、`chepaipai-ops-playbook`（FTP/PDO/列名/鉴权坑）。
> 本 skill 只收**这一个特定但极隐蔽的坑**：HTML in-DOM 模板下，自闭合的 Element Plus 组件会把后面的兄弟节点「吞掉」。

## 何时用本 skill
- 页面某区域**明明数据/逻辑正常（Vue 代理里有值），但 DOM 里整块不出现**，且浏览器 console **零报错**。
- 要对接手的老 `dashboard.php` / `insurance/admin/app.js`（巨型单文件前端）做**模板标签规范化**或上线前体检。
- 这类 bug 在车拍拍项目里已经实打实踩过两次：**保证金流水表整张 el-table 消失**（8 小时定位）、以及后续「创建拍卖会」按钮无反应是另一类绑定/重名坑（见末尾附录）。

## ⚠️ 根因（必读，否则无从下手）
车拍拍后台 `dashboard.php` 是 **HTML in-DOM 模板**：浏览器先按 HTML 规则解析 `<div id="app">` 内的标签，再交给 Vue 编译。
- HTML 解析规则下，**非 void 的自定义元素（如 `<el-alert>`、`<el-divider>`、`<el-input>`）的 `/>` 并不会自闭合**。
- 于是 `<el-alert ... />` 被当成**未闭合的开始标签**，会把后面所有兄弟节点（如 `el-divider`、`h4`、整张 `el-table`）**吞成它的子节点**。
- 若该组件带 `v-if=false`（如「未找到会员」提示），被吞内容连同它一起**静默消失，且无任何 JS 报错**（被 `app.config.errorHandler` 吞掉）——表现就是「数据在、DOM 没有、控制台干净」，极难排查。

> 对照：写在 JS 里的 **Vue 字符串 template**（`app.js` 的 `template: \`...\``，vue.global 完整版编译）里 `<el-x/>` 是**合法写法、不会吞节点**。保险子系统 `app.js` 就是这种——改它只为规范统一，并非修活跃 bug。判别方法：看标签是写在 `.php` 的 `<div id="app">` 内（in-DOM，危险）还是 `.js` 的 ``template:`...` `` 内（字符串模板，安全）。

## 诊断 SOP（数据在、DOM 没有、零报错时）
1. **先排除其它常见原因**（都确认不是再怀疑吞节点）：
   - 数据问题？用后端 admin synthetic JWT 或直接查库确认数据存在。
   - 部署问题？`curl` 线上文件，grep 关键代码特征确认已上线。
   - 渲染报错？临时覆盖 `app.config.errorHandler` 打印错误，确认捕获 0 条。
   - v-if 切换？确认面板 `currentMenu` 真的切过去了（真实点击侧边栏 `li`）。
2. **确认是「结构性吞节点」**：用 Playwright 取 `#app` 下目标 `el-card` 的 `outerHTML`，如果卡片**在目标区块之前截断**（如正好停在某个 `</template>` / `</div>` / `<!--v-if-->` 之后就闭合），而 Vue 代理数据正常 → 锁定吞节点。
3. **marker 二分定位法（定位到具体哪一行吞的）**：在疑似区块前后插入诊断 `<div style="color:#f0f">MK_XXX</div>` 标记，部署后用 Playwright 检查哪个 marker 还在 DOM、哪个之后的内容没了——边界即「自闭合后紧跟兄弟开始标签」的位置。定位完**务必删除 marker**。
4. **dump 卡片尾部**：`page.eval_on_selector` 取卡片 `outerHTML` 写文件，grep `el-table`/`操作人`/目标文案，确认元素彻底缺失而非隐藏。

## 系统性修复 SOP（根治，而非只修一处）
> 与其逐个判断「是否危险」，不如**把所有自闭合 el 组件统一改成显式闭合**：显式闭合在 HTML 解析下永远正确，对原本靠 provide/inject 注册的 `el-option`/`el-step`/`el-table-column` 行为完全不变，只对真正危险的「吞节点」情形完成修复。

1. 用本 skill 附带的 `scripts/fix_self_close.py`（**引号排除正则**，线性无回溯）：
   ```bash
   python scripts/fix_self_close.py deploy_src/admin/dashboard.php          # 改写+dump统计
   python scripts/fix_self_close.py deploy_src/insurance/admin/app.js       # 保险子系统同理
   python scripts/fix_self_close.py <file> --check                         # 只统计不改写
   ```
   - 正则 `<(el-[A-Za-z0-9-]+)((?:"[^"]*"|'[^']*'|[^>'"])*?)\s*/>` 把 `<el-x .../>` → `<el-x ...></el-x>`。
   - ⚠️ **绝不能用** `"[^"]*"|'[^']*'|[^>]` 这种 `[^>]` 能吞引号的分支——长行上会**灾难性回溯卡死**（本 skill 作者踩过，3.5 分钟无输出）。必须排除引号。
   - 自动生成 `.bak_selfclose_*` 备份。
2. **平衡校验**（改完必须跑）：逐类型核对 `开标签数 = 显式闭合数 + （自闭合数应为0）`，`html.parser` 末态未闭合栈应为空。本 skill 的校验 one-liner 见下方「校验片段」。
3. **顺手修掉其它真实缺陷**：改写后若发现某类型 `开 ≠ 闭`（如 `el-option` 差 1），多半是原始代码里有**空 `<el-option>` 裸开标签**误写（复制残留），直接删掉。

## 部署 + 上线验证 SOP
1. **FTP 部署**（主机 `wuhanhonganghang.cn`，user `wuhanhgh06`，密码走 `FTP_PASS` 环境变量；WAF 拦截默认 UA → 必带浏览器 UA）：
   ```bash
   FTP_PASS=<FTP密码> python -c "import sys;sys.path.insert(0,'.');from ftp_put_robust import put_one;put_one('deploy_src/admin/dashboard.php','wwwroot/admin/dashboard.php')"
   ```
   - 保险：`wwwroot/insurance/admin/app.js`；主站：`wwwroot/admin/dashboard.php`。
2. **curl 线上校验**（确认文件真的更新、自闭合残留 0）：
   ```bash
   curl -s -A "Mozilla/5.0" "http://wuhanhonganghang.cn/admin/dashboard.php" -o t.php
   grep -oE "<el-[A-Za-z0-9-]+[^>]*/>" t.php | wc -l   # 期望 0
   ```
3. **逐面板 Playwright 验证**（本 skill 附带 `scripts/verify_panels.py` / `verify_insu.py`）：
   - 登录 `admin/admin123`（按钮文字是「登 录」带空格，选择器用 `button:has-text("登 录"), button:has-text("登录")`）。
   - 真实点击 16 个侧边栏 `li`，断言：面板切换（`currentMenu===key`）+ 主内容区出现 `.el-card/.el-form/.el-table` 任一（>0）+ **全局 JS 错误为 0**。
   - 保险后台 `verify_insu.py` 同理遍历 12 个菜单。
   - Vue 挂载判定：`document.querySelector('#app').__vue_app__._instance.proxy` 读响应式字段；`page.evaluate` 传**箭头函数表达式**（`() => {...}`），不要裸 `return`（非法）。

## 校验片段（改完即用）
```python
import re
for SRC in ["deploy_src/admin/dashboard.php"]:
    t=open(SRC,encoding="utf-8").read()
    rem=re.findall(r'<el-[A-Za-z0-9-]+[^>]*/>',t)
    bad=[]
    for tag in sorted(set(re.findall(r'<(el-[A-Za-z0-9-]+)',t))):
        op=len(re.findall(r'<%s(\s|>)'%re.escape(tag),t))
        cl=len(re.findall(r'</%s>'%re.escape(tag),t))
        sc=len(re.findall(r'<%s[^>]*/>'%re.escape(tag),t))
        if op-cl-sc!=0: bad.append((tag,op,cl,sc))
    print(SRC,"残留自闭合=",len(rem),"不平衡=",bad or "无")
```

## 铁律（写进记忆，下次直接遵守）
- **车拍拍前端模板（in-DOM 部分）新增任何 Element Plus 组件，一律写显式闭合 `</el-x>`**，禁止 `/>` 自闭合。
- 改完巨型前端文件，**必须 Playwright 验证目标区块真实出现在 DOM**（不只看 Vue 代理数据）——代理有值 ≠ 页面渲染了。

## 附录：另一类「同现象不同根因」坑（创建拍卖会按钮无反应）
同样的「点击某功能毫无反应 / 报错」，还可能是：
- **函数重名覆盖**：同一 `setup()` 作用域内两个 `createAuction`（拍卖会模块 vs 物资模块）重名，后者覆盖前者 → 按钮调用错版本（读不存在的 `aucForm`）→ 报错失效。
- **return 漏暴露**：模板引用的 `openAuctionCreate`/`pauseAuction` 等未在 `setup` 的 `return` 暴露 → 模板访问不到，点击无反应。
排查法：扫描模板 `@click` / `:xxx` 引用的标识符，与 `return` 暴露集合做 diff（可用 `analyze_missing_return.py` 双向扫描）。
