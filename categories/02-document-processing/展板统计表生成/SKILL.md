---
name: 展板统计表生成
description: 生成「藏青+米金」商务展板风格的统计表（序号/类目/数量/占比 + 合计行 + 说明框），输出高清 PNG 可直接插入标书/报告。当用户说「做一个类似这张图的数据表」「做个统计表」「XX 分布表」「按 XX 维度统计」，或提供一张表格截图要求照样式做时使用。支持数据驱动换维度（省份/品牌/月份/状态/类目等），也支持从生产库只读聚合取真实数据。
agent_created: true
---

# 展板统计表生成

把「数据」变成一张**藏青+米金**的展板级统计表，输出 2x 高清 PNG（可直接插标书、报告、大屏）。

## 何时用

- 用户发来一张统计表截图，说「做一个类似这个的数据表」
- 用户说「做个 XX 统计表 / XX 分布表 / 按 XX 维度统计」
- 需要把库里的数据聚合成一张对外展示的表格图

## 视觉规范（必须严格照此，别自创）

| 元素 | 规格 |
|---|---|
| 页面 | 宽 780px，内边距 38px 40px 34px，白底 |
| 主色 navy | `#1b3a5e`（表头底色 / 类目名 / 标题 / 徽标值） |
| 深 navy | `#14304f`（合计行文字） |
| 金 gold | `#c8a24a`（徽标左边框 / 说明框左边框）；文字用 `#b0872c` |
| 米白 cream | `#fbf3e2`（合计行底）；`#fdf8ec`（说明框底）；`#f5f2ea`（徽标底） |
| 线 | 行分隔 `#ecebe6`；列分隔 `#f1efea`；外框 `#e3dfd4` |
| 字号 | 标题 26px/800；副标题 13px；表头 14px/700；表体 14px；合计 14.5px/800；说明 12.8px |
| 表头行高 | 46px，白字，列间 1px 白色半透明分隔 |
| 表体行高 | 34px，居中；序号列 12.5px 灰 `#9c978a`；类目列 14.5px/700 navy |
| 合计行 | 米白底，`合计` 横跨「序号+类目」两列并居中 |
| 说明框 | 米白底 + 左侧 4px 金边，标题「说明：」navy/700，条目 `1.` 缩进悬挂；**关键短语用金色 `<em>` 高亮** |

结构顺序：**标题 → 副标题 → 统计口径徽标 → 表格 → 说明框**。列宽（5 列：64/196/142/142/156）。

## 标准流程

### 1. 先问维度（除非用户已指明）
一张表只表达一个维度。常见维度：省份/区域、品牌/类目、月份、状态。用 AskUserQuestion 给 4 个选项让用户选，推荐最贴合业务的（如「按省份区域」）。

### 2. 取真实数据（用户重视"真数"，别编）
如果数据在库里，写**只读**诊断脚本聚合，不要手填：
- 车拍拍生产库（wuhanhgh06 / `hg_` 表）：见 `references/chepaipai-db.md`
- 聚合 SQL 模式：`SELECT <维度> AS k, COUNT(*) cnt, SUM(CASE WHEN status='已成交值' THEN 1 ELSE 0 END) deal FROM <表> WHERE <范围> GROUP BY <维度> ORDER BY cnt DESC`
- 用 `grp()` 输出时**记得读 `$r['k']`**（SQL 里 `xxx AS k`，不是 `AS <原列名>`，否则标签取出来全是 null —— 这个坑踩过）
- 脚本 `error_reporting(0)` + `Content-Type: application/json`，输出 JSON 便于本地解析

### 3. 生成 HTML
复制 `templates/table_template.html`，**只改顶部 `DATA` 块**：
- `title` / `subtitle` / `scopeValue` / `head`（列名）
- `rows`：`{cat, cnt, deal, ratio}`；ratio 留空则按 `deal/合计deal` 自动算
- `total`：合计行
- `notes`：说明数组，`<em>…</em>` 内会渲染成金色高亮

**占比口径**：与参考图一致 —— `占比 = 该行 成交/数量 ÷ 合计成交/数量`，保留两位小数，合计 100.00%。

### 4. 出高清 PNG
```bash
python scripts/shot.py <html路径> [out.png] [宽度px]
```
脚本自动：找 Playwright 的 chromium headless shell → `--force-device-scale-factor=2` 渲染 → PIL 裁掉底部白边。
- 本机内核：`C:/Users/AHS/AppData/Local/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe`
- 截图宽度按 `--window-size=780,<足够高>`，高度会被裁掉，不用精确
- **必须裁白边**：headless 按窗口高截图，不裁会有大片空白

### 5. 自检 + 交付
- 用 Read 工具**读一遍 PNG**确认：配色对、数据对、无溢出/截断、说明框金色高亮正常
- `present_files` 同时给 `.html` 与 `.png`（HTML 会自动开实时预览）

## 坑位清单

1. **headless 截图带白边** → 必须用 PIL 从底往上扫非白行裁剪，保留 68px（2x）下边距。
2. **JSON 标签为 null** → 聚合 SQL 用了 `AS k` 却读 `$r['原列名']`，改读 `$r['k']`。
3. **占比基数**：是「合计成交」不是「合计上拍」，别搞混（参考图用的是前者）。
4. **说明框第 3 条**（占比公式）与最后一条的关键短语要金色高亮，这是参考图的辨识特征。
5. 中文文件名在 Windows + FTP 上易乱码；上传到服务器时优先用 ASCII 文件名。
