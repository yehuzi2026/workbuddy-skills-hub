# JSON 输出 Schema 完整定义

## 顶层结构

```json
{
  "meta": {},           // 元信息
  "A_basic_info": {},   // 项目基础信息
  "B_procurement_requirements": {}, // 采购需求
  "C_star_clauses": [], // ★ 实质性条款
  "D_scoring_standard": {}, // 评分标准
  "E_business_conditions": {}, // 商务条件
  "F_legal_references": [], // 法规引用
  "G_key_numbers": {}, // 关键数字
  "H_locations": []    // 楼栋/地点
}
```

## meta — 元信息

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| extraction_date | string | ✅ | 提取日期 YYYY-MM-DD |
| source_file | string | ✅ | 原始文件名 |
| source_format | string | ✅ | "pdf" 或 "docx" |
| total_pages | int | ✅ | 总页数 |
| has_amendments | bool | ❌ | 是否含更正文件 |
| amendment_files | string[] | ❌ | 更正文件名列表 |
| warnings | string[] | ❌ | 提取过程中的警告信息 |
| uncertain_fields | string[] | ❌ | 不确定的字段列表 |

## A_basic_info — 项目基础信息

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| project_name | string | ✅ | 逐字提取，不得改动任何字符 |
| project_number | string | ✅ | 逐字提取 |
| package_number | string | ❌ | 如"包1""标段2" |
| procurement_method | string | ✅ | "公开招标"/"竞争性磋商"/"竞争性谈判"/"询价"/"单一来源" |
| purchaser_full_name | string | ✅ | 逐字提取 |
| purchaser_address | string | ❌ | — |
| agency_full_name | string | ✅ | 逐字提取 |
| agency_address | string | ❌ | — |
| budget_amount | string | ❌ | 含单位，如"500万元" |
| max_price | string | ❌ | 最高限价 |
| sme_only | bool | ❌ | 是否专门面向中小企业 |
| bid_bond | string | ❌ | 投标保证金 |

## B_procurement_requirements — 采购需求

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| summary | string | ✅ | ≤200字 |
| equipment_list | Equipment[] | ❌ | 设备清单 |
| total_equipment_count | int | ❌ | 设备总数 |
| technical_params_table | string | ❌ | Markdown 格式的技术参数表 |
| deployment_locations | string[] | ❌ | 安装/交付地点 |
| service_years | string | ❌ | 服务年限（BOT类项目） |
| other_requirements | string | ❌ | 其他特殊要求 |

### Equipment 对象

```json
{
  "seq": 1,
  "name": "设备名称",
  "spec": "规格型号",
  "brand_required": false,
  "qty": 100,
  "unit": "台",
  "note": "备注",
  "is_star_item": false
}
```

## C_star_clauses — ★实质性条款

### Clause 对象

```json
{
  "id": "C01",
  "text": "★条款逐字原文（不截断）",
  "chapter": "章节名",
  "page": 17,
  "marker_type": "star_symbol",  // "star_symbol" | "triangle" | "bold_underline" | "keyword_match"
  "category": "技术"  // "技术" | "商务" | "资格"
}
```

## D_scoring_standard — 评分标准

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| scoring_summary | ScoringSummary | ✅ | 评分类别和分值 |
| subjective_items | SubjectiveItem[] | ✅ | 主观分项列表 |
| objective_items | ObjectiveItem[] | ❌ | 客观分项列表 |
| total_subjective_score | float | ✅ | 主观分总分 |
| total_objective_score | float | ❌ | 客观分总分 |
| original_scoring_text | string | ✅ | 评分标准原文（保留完整） |

### ScoringSummary

```json
{
  "price": {"max_score": 30, "weight": "A1", "formula": "报价得分计算公式"},
  "technical": {"max_score": 55, "weight": "A2"},
  "business": {"max_score": 15, "weight": "A3"}
}
```

### SubjectiveItem

```json
{
  "seq": 1,
  "name": "评分项名称（逐字原文）",
  "score": 10,
  "category": "技术部分",
  "requirements_summary": "≤100字摘要",
  "requirements_full": "完整评分要求原文",
  "suggested_chapter_title": "建议的一级标题名（=评分项名称）"
}
```

### ObjectiveItem

```json
{
  "seq": 1,
  "name": "评分项名称",
  "score": 5,
  "category": "商务部分",
  "type": "certificate",  // "certificate" | "report" | "commitment" | "performance" | "personnel"
  "requirement": "要求描述"
}
```

## E_business_conditions — 商务条件

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| delivery_period | string | ❌ | 工期/交货期 |
| warranty_period | string | ❌ | 质保期 |
| payment_terms | string | ❌ | 付款方式 |
| performance_bond | string | ❌ | 履约保证金 |
| bid_bond | string | ❌ | 投标保证金 |
| contract_summary | string | ❌ | 合同主要条款摘要 |
| penalty_clauses | string[] | ❌ | 违约/罚款条款 |

## F_legal_references — 法规引用

### LegalRef 对象

```json
{
  "id": "F01",
  "full_name": "完整法规名称（含编号/年份/文号）",
  "short_name": "简称",
  "location": "P5 投标人须知",
  "category": "政府采购"  // "政府采购" | "产品质量" | "节能环保" | "安全生产" | "行业专项" | "其他"
}
```

## G_key_numbers — 关键数字

此对象为扁平结构，key 为数字的中文描述，value 为带单位的字符串：

```json
{
  "设备总量": "358台",
  "洗衣机数量": "206台",
  "吹风机数量": "134台",
  "烘干机数量": "18台",
  "安装工期": "10个工作日",
  "合作年限": "8年",
  "预算金额": "500万元",
  "罚款金额（超期）": "5000元/天",
  "响应时限": "2小时",
  "大物洗单价": "4元/次",
  "标准洗单价": "3元/次"
}
```

## H_locations — 楼栋/地点

### Location 对象

```json
{
  "id": "H01",
  "name": "楼栋名称（逐字）",
  "campus": "所属校区",
  "usage": "用途",
  "equipment_count": 95
}
```

## I_timeline — 关键时间线（v0.2.0 新增）

按项目生命周期 P0~P8 共 9 个阶段组织，是主观分方案的硬约束输入。

### Timeline 对象

```json
{
  "P0_pre_bid": {
    "bid_deadline": "ISO datetime 或原文",
    "bid_opening": "ISO datetime 或原文",
    "bid_validity_days": "90天",
    "qa_deadline": "ISO datetime 或原文"
  },
  "P1_delivery": {
    "field_name": "招标文件中的原始字段名",
    "value": "具体数值（带单位）",
    "has_penalty": false,
    "alias_found": "在招标文件中实际出现的叫法"
  },
  "P2_installation": {
    "field_name": "安装工期",
    "value": "10个工作日",
    "has_penalty": true,
    "penalty_detail": "超1天罚5000元，超3天罚15000元，超7天解约",
    "alias_found": "部署时间"
  },
  "P3_service": {
    "field_name": "服务期",
    "value": "8年",
    "renewal_mode": "固定期限 | 1+1续签 | 年度续签",
    "alias_found": "合作期限"
  },
  "P4_warranty": {
    "field_name": "质保期",
    "value": "3年",
    "has_penalty": false,
    "alias_found": "保修期"
  },
  "P5_response": {
    "response_time": "2小时",
    "repair_time": "48小时",
    "on_site_time": "到场时间（如有）",
    "has_penalty": true,
    "alias_found": "售后响应时限"
  },
  "P6_payment": {
    "field_name": "结算周期",
    "value": "每月结算",
    "alias_found": "付款期限"
  },
  "P7_acceptance": {
    "field_name": "验收期限",
    "value": "安装完成后7个工作日",
    "alias_found": "验收时间"
  },
  "P8_penalty": {
    "penalty_gradient": [
      {"threshold": "1天", "penalty": "5000元", "type": "罚款"},
      {"threshold": "3天", "penalty": "15000元", "type": "罚款"},
      {"threshold": "7天", "penalty": "解约", "type": "废标"}
    ],
    "termination_trigger": "超期7天",
    "has_penalty": true
  },
  "project_type": "BOT投资运营类 | 纯设备供货类 | 服务配送类 | 设备+服务混合类",
  "timeline_priority": ["P2", "P3", "P5", "P8"],
  "cross_validation_warnings": [
    "P1：无可用的交货期数据",
    "P3：服务期未找到，可能为BOT项目无明确服务年限"
  ]
}
```

### 阶段类型说明

| 阶段 | 含义 | 常见于 |
|------|------|--------|
| P0 | 投标流程时间 | 所有项目 |
| P1 | 货物/服务交付时间 | 设备供货、食材配送 |
| P2 | 现场安装/施工时间 | 设备供货、BOT建设 |
| P3 | 长期服务/运营时间 | BOT、服务配送 |
| P4 | 质保到期时间 | 设备供货 |
| P5 | 运维响应时间 | 服务配送、BOT |
| P6 | 款项结算时间 | 服务配送 |
| P7 | 完工验收时间 | 设备供货、施工 |
| P8 | 违约触发时间 | 所有含罚款项目 |

## 数据质量标记

对于无法确定的数据，使用以下格式标记：

```json
{
  "field": "⚠️ 无法确定 — 请人工核实（原因：招标文件未明确标注）",
  "uncertain": true
}
```

对于可能存在多种理解的数据，提供备选值：

```json
{
  "field": "500万元",
  "alternatives": ["500万元（招标公告）", "480万元（投标人须知）"],
  "recommended": "500万元（以招标公告为准）",
  "uncertain": true
}
```
