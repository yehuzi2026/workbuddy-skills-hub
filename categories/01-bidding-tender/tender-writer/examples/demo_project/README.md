# Demo Project — 虚构脱敏示例

> **本目录下的所有内容均为虚构,不对应任何真实项目、真实单位或真实人员。**
>
> 所有城市名(A市、B区)、公司名(XX科技)、人名(张三、李四)、
> 项目编号、金额、日期均为示例数据。

## 用途

展示 tender-writer 五阶段工作流的完整产出链:

```
input/招标文件_virtual.md        ← 虚构招标文件(阶段 1 输入)
    ↓
output/tender_brief.md           ← 阶段 1 产出:招标解读简报
output/scoring_matrix.csv        ← 阶段 2 产出:评分矩阵
output/outline.md                ← 阶段 3 产出:标书提纲
output/chapter_01_sample.md      ← 阶段 4 产出:第一章样例
output/compliance_report.md      ← 阶段 5 产出:合规终审报告
```

## 建议阅读顺序(3 分钟看完)

1. **先扫读** [`input/招标文件_virtual.md`](input/招标文件_virtual.md) — 了解输入长什么样(一份典型的政府采购招标文件,扫读即可)
2. **重点看** [`output/scoring_matrix.csv`](output/scoring_matrix.csv) — 阶段 2 的产物,**这是本工具最核心的价值载体**:把评分办法拆成 11 行矩阵,每一分对应到具体应答章节和证据材料,杜绝漏答
3. **再看** [`output/compliance_report.md`](output/compliance_report.md) — 阶段 5 的合规闭环:70/70 覆盖度、★条款逐条核查、废标风险扫描,这就是"工程化"和"让 AI 随便写"的区别
4. **按需查阅** 其他文件(`tender_brief.md` → `outline.md` → `chapter_01_sample.md`),观察每个阶段的产出如何被下一阶段引用

## 注意事项

- 本示例仅展示产出格式和阶段衔接逻辑,**不代表最终标书质量**
- 实际项目中,每个阶段的产出都需要人工审查和补充
- chapter_01 只是第一章样例,完整标书通常有 6-7 章
