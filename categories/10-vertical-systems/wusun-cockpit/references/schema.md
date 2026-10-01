# 驾驶舱数据模型与接口契约（wusun-cockpit）

后端 `GET /api/dashboard`（`server.js` ~995–1227 行）聚合四张业务表。本文件记录关键字段、返回结构与隔离规则，改接口前先读。

## 一、业务表关键字段

### inquiries（询价 / 案件主表）
| 字段 | 含义 | 驾驶舱用途 |
|---|---|---|
| id | 主键 | 关联 quotations/cases_close/repairs |
| survey_amount | 定损金额（元） | 当前"询价"指标口径（原"开票"） |
| settlement_amount | — | 实际结案以 cases_close.settlement_amount 为准 |
| created_at | 创建时间 | 本月/本年/当日/趋势按月聚合 |
| status | 状态 | 在途指标：'待报价','招标中' 计 pendingInquiry |
| city | 城市 | 数据隔离（city 账号只看本城） |
| assignee_id | 负责人 | 数据隔离（region 账号） |
| accident_location | 出险地点文本 | 解析省份/城市用于地图（见第三节） |
| insurer | 保险公司 | 分平台卡片分组 |
| item_name | 询价标的 | 重点单品名称 |
| vehicle_no | 车牌 | 重点单品副标题 |
| case_type | 案件类型 | 品类兜底字段（无 repair_type 时用） |

### quotations（报价）
| 字段 | 含义 |
|---|---|
| inquiry_id | 关联 inquiries.id |
| status | '待审批','待审' → pendingQuote |
| total | 报价金额（早期"开票"口径，现大屏已改用 survey_amount） |

### cases_close（结案 / 纯销）
| 字段 | 含义 |
|---|---|
| inquiry_id | 关联 inquiries.id |
| settlement_amount | 结案金额 → 当前"纯销"指标 |
| created_at | 结案时间 |
| closed_at | 结案时间；NULL → pendingCase（待结案） |

### repairs（维修 / 在修）
| 字段 | 含义 |
|---|---|
| inquiry_id | 关联 inquiries.id |
| repair_type | 维修类型（品类首选字段，非空时用） |
| status | 非 '已完成','已结案' → inRepair（在修） |

## 二、/api/dashboard 返回结构

```jsonc
{
  "asOf": "YYYY-MM-DD",
  "kpi": {
    "monthInvoice": { "name":"本月询价", "value":<元>, "unit":"元",
      "yoy":<同比率|null>, "daily":<当日新增>, "rate":<完成率%>,
      "pending":{ "unmatch":<待报价+招标中单数>, "uninvoiced":<待审批报价数>, "today":<当日> },
      "prepaid":<在途定损金额> },
    "yearInvoice": { "name":"本年询价", "value":<元>, "unit":"元", "yoy":, "rate": },
    "monthNet":    { "name":"本月纯销", "value":<元>, "unit":"元", "yoy":, "daily":, "rate": },
    "yearNet":     { "name":"本年纯销", "value":<元>, "unit":"元", "yoy":, "rate": },
    "stock": { "name":"在途指标组", "pendingInquiry":, "pendingQuote":, "inRepair":, "pendingCase": }
  },
  "trend": { "months":["1月",...], "invoice":[<8月询价额>], "net":[<纯销额>],
             "rate":[<完成率%>], "yoy":[<同比%>] },
  "category": { "names":[<品类>], "invoice":[<额>], "net":[<额>], "rate":[<完成率%>], "yoy":[0,...] },
  "product":  { "names":[<标的（车牌）>], "invoice":[<额>], "net":[<额>], "rate":[<完成率%>], "yoy":[0,...] },
  "map": {
    "provinces": [ { "name":"湖北", "value":<定损额> }, ... ],      // 全国省级
    "stars": [ "湖北", "广东", ... ],                              // Top6 省（星星）
    "detail": { "湖北": [ { "name":"武汉市", "value":<额>, "rate":<占比%> }, ... ] }  // 省→城市
  },
  "platform": [ { "name":"<保险公司>", "actual":<询价额>, "settled":<结案额>, "rate":<完成率%> }, ... ]
}
```

- 完成率口径：`rate = min(150, round(纯销 / 询价 * 100, 1))`。
- 趋势：近 8 个月；同比用 `lastYearMonth(m)` 取去年同期询价额。

## 三、省份 / 城市解析正则

- `locationToProvince(loc)`：按 `server.js` 内 30+ 条正则（武汉|湖北→湖北、广州|深圳|广东→广东 …）匹配 `accident_location`；无匹配归 '其他'。
- `locationToCity(loc)`：`loc.match(/[一-龥]{2,8}?(?:市|区|县|盟|州|旗)/)` 取城市名；取不到则回退到省份。
- 地图聚合：先按 `accident_location` GROUP BY，再经上面两函数归并到省/市。**新增省份覆盖需在 `locationToProvince` 补正则，否则该地数据落入"其他"不显示于地图。**

## 四、数据隔离规则

`dashInqScope(admin)`：
- `role==='platform'` → `{ where:'', params:[] }`（全量）
- `role==='city'` → `{ where:' AND i.city = ?', params:[admin.city] }`
- 其他（region）→ `{ where:' AND i.city = ? AND i.assignee_id = ?', params:[admin.city, admin.id] }`

所有 SQL 必须 `... ${scope.where}` 并 `.get(...scope.params)` / `.all(...scope.params)`。涉及 `accident_location` 的查询用 `scope.where.replace(/ i\./g, ' i.')` 保持占位符一致。

## 五、前端渲染映射（dashboard.js）

| 区块 | 函数 | 数据源 |
|---|---|---|
| KPI 卡片 | initKpi / renderDashboard | DATA.kpi.* |
| 趋势图 | initTrend | DATA.trend |
| 品类图 | initCategory | DATA.category |
| 重点单品 | initProduct | DATA.product |
| 全国/省份地图 | initMap / chinaOption / renderProvince | DATA.map |
| 平台卡片 | initPlatform | DATA.platform |
| 星星+涟漪 | buildStarSeries | DATA.map.stars / 城市 Top6 |
| 返回全国 | #map-back → freshChart+renderChina | — |
