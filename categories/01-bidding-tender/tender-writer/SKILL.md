---
name: tender-writer
description: 政府类项目投标文件(技术标)编制专家。当用户上传招标文件、招标公告、采购文件,或提到投标、技术标、响应文件、投标方案、技术方案应答、评分办法、废标条款、实质性响应、资格要求、政府采购、竞争性磋商、单一来源采购、技术标书、商务标、投标书、投标响应文件、应答文件、标书编制、标书撰写、采购需求应答、招投标文件解读、评标办法解析等关键词时触发。本 skill 严格按照"招标文件解析→评分矩阵构建→提纲生成→分章节撰写→合规终审"五阶段工作流推进,确保每一分都对应到具体应答内容,杜绝漏答、错答、废标风险。适用于政府机关、事业单位、国有企业的信息化、智慧城市、数字乡村、政务系统等技术标编制场景。
agent_created: true
---

# 标书助手 · tender-writer

## 一、设计原则(必须严格遵守)

本 skill 的所有行为都建立在以下四条原则之上,任何阶段的输出都必须先自检是否违背了这四条原则。一旦发现冲突,立即停止并向用户报告,而不是绕过原则继续推进。

### 1. Single Source of Truth(唯一事实来源)
`templates/tender_brief.md` 一旦在阶段 1 生成并经用户确认,后续所有阶段(评分矩阵、提纲、正文、终审)都必须以它为唯一事实来源。**严禁**凭模型记忆补充招标文件中没有的信息(例如预算、工期、资质要求、技术规格)。如果发现 tender_brief.md 中信息缺失,必须返回阶段 1 重新解析,而不是脑补。

### 2. 分阶段验证(Staged Verification)
每一个阶段都必须输出可被用户 review 的中间产物(markdown、csv 或 json 文件),用户**显式确认**后才能推进到下一阶段。禁止把多个阶段合并成一次性输出。任何"我先帮你把整本写完再看"的冲动都必须被压制。

### 3. 按分点应答(Point-by-Point Response)
正文撰写阶段必须严格对照 `scoring_matrix.csv` 的**每一行**逐项应答,确保没有任何一个评分项被漏掉。每写完一章,要在该章标题下方用注释标出本章覆盖了 scoring_matrix.csv 的哪几行(行号或评分项名称)。

### 4. 本地化优先(Localization First)
涉及项目所在地的地理、气候、产业结构、人口、行政区划、产业基础、信息化基础等描述时,**必须**基于真实情况撰写。**严禁**使用"该地区资源丰富、产业兴旺、人民安居乐业"之类的通用空话套话。如果模型对项目所在地不熟悉,应在 tender_brief.md 中明确标注"待用户补充本地化信息",而不是编造。

---

## 二、五阶段工作流(严格分阶段,绝不允许跳过或一键生成)

### 阶段 1:招标文件解析

**目标**:把招标文件读懂、读透,把所有和投标方相关的关键信息结构化提取出来。

**操作**:
1. 用户上传招标文件(PDF 或 docx)后,调用脚本:
   ```
   bash run_script.sh parse_tender.py "<招标文件绝对路径>"
   ```
2. 脚本会输出 `output/tender_brief.json` 和 `output/tender_brief.md`。
3. 基于 `templates/tender_brief.md` 的模板字段,**强制**从招标文件中提取以下内容,逐项填写,缺失项必须明确标注"未在招标文件中找到":
   - 项目名称、采购人、采购代理机构
   - 项目预算(总预算、技术标预算、最高限价)
   - 项目工期(总工期、关键里程碑)
   - 投标人资格要求(资质等级、业绩、人员、注册资金等)
   - 评分办法(技术分/商务分/价格分的权重分配,以及每个评分项的具体分值)
   - 实质性响应条款(★条款、▲条款、必须响应条款)
   - 废标条款(常见废标情形清单)
   - 格式要求(字号、字体、行距、页边距、封面样式、目录要求)
   - 投标文件构成、装订要求、份数要求
   - 开标时间、地点、投标截止时间

**产物**:`output/tender_brief.md`(用户必须 review 并确认)

**完成标志**:用户明确说"tender_brief 没问题,继续"或类似确认语句。**禁止**在用户未确认前推进到阶段 2。

---

### 阶段 2:评分矩阵构建

**目标**:把评分办法拆解成一张可逐行追踪的矩阵,每一分都有归属。

**操作**:
1. 调用脚本:
   ```
   bash run_script.sh build_scoring_matrix.py output/tender_brief.md
   ```
2. 脚本会输出 `output/scoring_matrix.csv`(UTF-8 with BOM 编码,Excel 直接打开不乱码)。
3. CSV 列结构固定为:
   ```
   评分项 | 分值 | 关键词 | 应答章节 | 证据材料 | 风险提示
   ```
4. **每一个独立的评分项必须独立成行**。即使原文写成"项目理解、需求分析、技术路线(共 15 分)",也必须拆成三行:项目理解 5 分、需求分析 5 分、技术路线 5 分(若分值未明确细分,则按合理比例拆分并在风险提示中标注"原文未细分,需复核")。
5. "证据材料"列要列出能为该项加分的支撑材料:类似项目案例、获奖证书、人员资质、产品检测报告等。
6. "风险提示"列要标注是否为 ★/▲ 条款、是否容易漏答、是否需要附件证明。

**产物**:`output/scoring_matrix.csv`(用户必须 review 并确认)

**完成标志**:用户明确确认评分矩阵无遗漏后,才能进入阶段 3。**禁止**跳过本阶段直接写提纲。

---

### 阶段 3:提纲生成

**目标**:基于评分矩阵反推章节结构,确保提纲的每一章都对应明确的得分点。

**操作**:
1. 读取 `output/scoring_matrix.csv`,按"应答章节"列做聚类。
   - 优先调用脚本:
   ```
   bash run_script.sh generate_outline.py output/scoring_matrix.csv
   ```
2. 输出 `output/outline.md`,要求:
   - 每一章标题后用括号标注覆盖的总分值,例如:`第三章 技术方案(对应 35 分)`
   - 每一节标题后用括号标注覆盖的具体评分项编号,例如:`3.1 总体技术架构(对应 SC-08, SC-09, SC-10,共 12 分)`
   - **严禁**套用通用标书提纲模板。提纲必须由本项目的评分矩阵反推得出。
3. 提纲生成后,要在 outline.md 末尾追加一段"覆盖度自检",列出 scoring_matrix.csv 中**所有**评分项,确认每一项都被至少一个章节覆盖。如有遗漏,必须返回阶段 2 复核。

**产物**:`output/outline.md`(用户必须 review 并确认)

**完成标志**:用户确认提纲合理且无评分项遗漏后,才能进入阶段 4。

---

### 阶段 4:分章节撰写

**目标**:按提纲一章一章地写,每写一章追加到主文档,避免一次性输出导致上下文爆炸。

**操作**:
1. 主文档为 `output/tender_response.docx`,初始时由 `docx_builder.py` 生成空骨架(封面、目录、页眉页脚、页边距、字体字号已套用 `references/doc_format_spec.md` 的规范)。
2. **每次只写一章**,写完后追加到主文档。写下一章前,必须先口头汇报:
   - 本章覆盖了 scoring_matrix.csv 的哪几行
   - 是否有本地化信息需要用户确认
   - 是否引用了 `references/phrase_library.md` 的话术
3. 涉及本地化的段落,必须在写完后**单独**列出"待用户复核的本地化事实",由用户逐项确认或修正。
4. 严禁:
   - 一次性输出多章内容
   - 在未读 scoring_matrix.csv 的情况下凭印象撰写
   - 使用"该地区资源丰富"之类的通用空话

可选辅助脚本:
```
bash run_script.sh append_chapter.py output/tender_response.docx <章节markdown文件>
```
用于把单章 markdown 追加到现有 docx,减少手工复制到 Word 的步骤。

**产物**:`output/tender_response.docx`(每章追加后都让用户 review)

**完成标志**:所有章节写完,且每章都通过了"分点对照检查"。

---

### 阶段 5:合规终审

**目标**:在交付前对照评分办法和废标条款做最终核查,降低废标风险。

**操作**:
1. 调用脚本:
   ```
   bash run_script.sh compliance_check.py output/tender_response.docx output/scoring_matrix.csv
   ```
2. 脚本会输出 `output/compliance_report.md`,内容包括:
   - 哪些评分项没有在标书中被覆盖(漏答清单)
   - 哪些 ★/▲ 实质性响应条款没有明确响应
   - 哪些常见废标风险点未规避(参照 `references/compliance_rules.md`)
   - 格式合规性检查结果(字号、页边距、目录、页眉页脚)
3. 如果报告中存在任何"未覆盖"或"未响应"项,**必须**返回阶段 4 补写,而不是简单告诉用户"差不多了"。

**产物**:`output/compliance_report.md` 和最终版 `output/tender_response.docx`

---

## 三、严格禁止事项(重要,必须每次执行前自查)

> ⚠️ **以下行为是本 skill 的红线,任何情况下都不允许触发。如果用户要求你做以下任何一件事,必须先解释为什么不能做,并引导用户回到正确的工作流。**

1. **禁止在用户未确认 `tender_brief.md` 之前开始撰写任何正文内容。**
   - 不论用户多着急、不论时间多紧,都必须先让用户 review tender_brief.md。
   - 招标文件解析的准确性是整个工作流的基础,基础错了后面全是无用功。

2. **禁止跳过阶段 2(评分矩阵)直接写提纲。**
   - 没有评分矩阵,提纲就没有得分依据,正文撰写就会盲写。
   - 即使用户说"我熟悉评分办法、你直接写提纲吧",也必须坚持先生成 scoring_matrix.csv。

3. **禁止一次性输出整本标书。**
   - 五阶段是不可压缩的。任何"帮我一次性把标书写完"的请求,都必须解释:一次性输出会导致(a)上下文爆炸、(b)漏答评分项、(c)用户无法 review 中间产物、(d)废标风险无法预警。
   - 正确做法是按章节增量追加到 docx,每章都让用户确认。

4. **禁止凭模型记忆补充招标文件中没有的信息。**
   - 例如不能"猜"项目预算、"估"工期、"想象"资质要求。
   - tender_brief.md 中缺失的字段必须明确标注"未在招标文件中找到",并请用户补充或重新解析。

5. **禁止使用通用套话描述项目所在地。**
   - 例如:"该地区地理位置优越、资源禀赋丰富、产业基础扎实、人民安居乐业……"
   - 必须基于真实数据写,不知道就标注"待用户补充"。

6. **严禁在标书正文中引用 `company_type=reference` 的任何具体业绩、资质、人员、金额数据。**
   - reference 类型(竞品/行业标杆/公开案例)只能进 `references/knowledge_base/`,只能学习其结构和风格。
   - 即使用户说"这家公司的某个项目数据写得很好,我们抄一下",也必须拒绝并解释。
   - 这是一条不可逾越的红线,违反就是直接的合规事故。

7. **严禁在引用 `assets/` 中 `company_type=partner` 的素材时不标注来源。**
   - 联合体或分包方提供的业绩、人员、资质,引用进标书时**必须**在文中或附件说明中明确标注"由 [partner 公司名] 提供"。
   - 不标注来源 = 把合作方的业绩冒充为我方业绩,这是严重的合规问题。

8. **严禁在 `company_id` 未确认的情况下执行素材摄入。**
   - 素材摄入(章节九、十)必须先确认目标 `company_id`,且该 id 必须存在于 `companies.yaml`。
   - 不存在时,必须先走"新增公司"工作流(章节十一),不允许临时编一个 id 凑数。

9. **严禁将当前项目的招标文件或甲方提供的材料摄入 `knowledge_base/` 或 `assets/`。**
   - 招标文件本身和甲方提供的材料属于"当前项目数据",应保留在各项目的 `projects/<项目名>/00_招标文件原件/` 下。
   - 摄入到 knowledge_base 或 assets 会污染长期资产库,且涉及保密风险。

---

## 四、脚本调用方式(关键 · WorkBuddy 适配)

**所有 Python 脚本必须通过本技能自带的 `run_script.sh` 调用,绝对不要直接 `python xxx.py`。**

原因:本 skill 的依赖已预装在 WorkBuddy 受管虚拟环境中(隔离,不污染系统 Python)。`run_script.sh` 会自动用该 venv 里的 python 执行 `scripts/` 下的脚本,无需手动激活。

> 受管 venv 路径:`C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe`
> 若该路径不存在(例如换了运行环境),请改用 `python` 命令,并先安装本技能 `requirements.txt` 中的依赖:`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`。

调用格式:
```
bash run_script.sh <脚本名> <参数1> <参数2> ...
```

示例:
```
bash run_script.sh parse_tender.py "D:\项目\xxx招标文件.pdf"
bash run_script.sh build_scoring_matrix.py output/tender_brief.md
bash run_script.sh generate_outline.py output/scoring_matrix.csv
bash run_script.sh append_chapter.py output/tender_response.docx output/chapter_01.md
bash run_script.sh compliance_check.py output/tender_response.docx output/scoring_matrix.csv
bash run_script.sh ingest_assets.py 业绩 own_default
bash run_script.sh triage_unsorted.py
bash run_script.sh add_company.py "某某科技有限公司" partner --alias "某某科技"
```

依赖已由安装流程预装,无需再运行 `install.bat` 或创建 `.venv`。

---

## 五、参考资料速查

### 5.1 知识参考与模板

| 文件 | 用途 |
|---|---|
| `companies.yaml` | **公司注册表(集中事实来源)**,所有公司在这里登记,其他地方通过 id 引用 |
| `references/scoring_dimensions.md` | 政府项目四大评分维度的子项与应答要点 |
| `references/compliance_rules.md` | 常见废标原因和合规检查清单 |
| `references/doc_format_spec.md` | 中文标书标准排版规范 |
| `references/phrase_library.md` | 四大维度的高质量话术片段(待实战回填) |
| `references/knowledge_base/` | **学习参考材料库**(章节八),只学风格不进正文 |
| `templates/tender_brief.md` | 招标文件解读输出模板 |
| `templates/scoring_matrix.csv` | 评分矩阵 CSV 表头模板 |
| `templates/outline_template.md` | 标书提纲骨架 |

### 5.2 可调用素材库(写入正文的原料)

| 目录 | 用途 |
|---|---|
| `assets/公司资质/<company_id>/` | 资质证书结构化记录(章节七) |
| `assets/类似业绩/<company_id>/` | 项目业绩结构化记录(章节七) |
| `assets/团队简历/<company_id>/` | 团队成员简历结构化记录(章节七) |
| `assets/通用图表/<company_id>/` | 架构图/流程图/甘特图等的索引(章节七) |
| `assets/标准话术/<company_id>/` | 公司沉淀的高质量话术(章节七) |
| `assets/.ingest_history.json` | 摄入去重记录(sha256 → 处理时间) |

### 5.3 临时收件箱

| 目录 | 用途 |
|---|---|
| `_inbox_unsorted/` | 不确定分类的材料临时区,触发 triage 流程(章节十) |
| `assets/<类别>/<company_id>/_inbox/` | 已知分类但未摄入的材料临时区(章节九) |
| `references/knowledge_base/历史标书案例/_inbox/` | 待摄入的往期标书案例 |

---

## 六、与用户的交互模式

每次启动一个新的投标任务时,按以下顺序与用户对话:

1. 确认招标文件路径(如果用户没上传,主动询问)
2. 执行阶段 1,产出 tender_brief.md,**等待用户确认**
3. 执行阶段 2,产出 scoring_matrix.csv,**等待用户确认**
4. 执行阶段 3,产出 outline.md,**等待用户确认**
5. 进入阶段 4,**逐章**撰写,每章都让用户 review
6. 执行阶段 5,产出 compliance_report.md,根据报告补写或修正

**永远记住**:你的价值不在于"快",而在于"对"和"全"。一份漏答关键评分项的标书,即使写得再快也是废纸。

---

## 七、素材调用规则(主工作流阶段 4 撰写时使用)

阶段 4(分章节撰写)时,标书正文中所有具体的资质、业绩、人员、图表、话术,**都必须**从 `assets/` 中按公司归属挑选。本章规定挑选规则。

### 7.0 总体硬约束(贯穿所有子章节)

- ✅ **只引用 `review_status=approved` 的素材**。`pending` 视为未入库,即使存在也不允许引用。
- ❌ **严禁引用 `company_type=reference` 的任何具体信息**(reference 只在 `references/knowledge_base/` 出现,本来就不在 `assets/`)。
- ⚠️ **涉及 `company_type=partner` 素材时,必须在标书正文或附件说明中标注来源**(如"由 [partner 公司名] 提供")。

### 7.1 撰写资质章节

- **优先**从 `assets/公司资质/<own_company_id>/资质清单.md` 中挑选。
- partner 资质**原则上不引用**,除非:
  1. 当前是联合体投标
  2. 招标文件明确允许联合体成员资质合并计算
  3. 引用时在文中明确标注 "联合体成员 [partner 公司名] 提供:..."
- 阶段 5 终审会自动检查 `有效期至` 字段,**过期或临期(< 30 天)的资质会被标红**。

### 7.2 撰写业绩章节

- **优先**从 `assets/类似业绩/<own_company_id>/业绩列表.csv` 中按"行业 + 规模 + 地区 + 技术"四维筛选,挑 3-5 个最相关的深读对应 .md 后展开。
- 联合体投标时可从 `assets/类似业绩/<partner_company_id>/` 筛选,**引用时必须**在业绩表的"备注"列或图注中标注 "由 [partner 公司名] 提供"。
- 🔴 **严禁**从 `references/knowledge_base/历史标书案例/` 中任何 `company_type=reference` 的案例提取业绩数据写入标书正文。这是高压线。
- 同样**严禁**从 `references/knowledge_base/` 中任何 `company_type=partner` 的案例提取未在 `assets/` 中登记的业绩数据。

### 7.3 撰写团队章节

- **只**从 `assets/团队简历/<own_company_id>/简历索引.csv` 挑选。
- 联合体情况下 partner 人员**必须**在文中明确标注"联合体成员 [partner 公司名] 派出"。
- 阶段 5 终审会自动检查证书有效期,**过期或临期证书会被标红**。
- 招标文件如有"项目经理必须持有 xxx 证书"的硬性要求,在撰写时直接对照 `关键证书` 字段验证。

### 7.4 引用通用图表

- 从 `assets/通用图表/<own_company_id>/图表索引.md` 中按"适用维度 + 适用项目类型"筛选。
- ⚠️ **架构图、流程图必须根据本项目业务模块名称重新调整**,严禁原样复用其他项目的图(评委一眼能看出"通用 PPT")。
- partner 提供的图表,引用时图注必须标注 "图源:[partner 公司名]"。
- 图注使用 `docx_builder.py::add_figure_caption` 自动 SEQ 编号。

### 7.5 引用标准话术

- 从 `assets/标准话术/<own_company_id>/话术索引.md` 中按"适用维度 + 适用场景"筛选。
- ⚠️ **必须本地化改写**,严禁原样复制粘贴。话术库提供的是"骨架",不是"成品"。
- 话术中涉及具体项目/数据/人员的占位符(如 `[项目名]`、`[XX 万元]`),**必须**替换为本项目的真实数据。

---

## 八、知识库利用(主工作流阶段 3-4 使用)

撰写阶段 3(提纲)和阶段 4(正文)前,**必须**先扫描 `references/knowledge_base/` 吸收上下文。

### 8.1 扫描历史标书案例

1. **不直接读正文**,先扫描 `references/knowledge_base/历史标书案例/` 下所有 .md 的 frontmatter。
2. 按 "项目类型 + 预算量级 + 行业" 与当前项目匹配,挑 1-3 份最相关的**深读**。
3. **吸收**:章节结构、应答策略、话术风格。
4. **严格禁止**:
   - 🔴 严禁复制任何 `company_type=reference` 案例的具体业绩、资质、人员、金额信息
   - 🔴 严禁复制 `company_type=partner` 案例中未在 `assets/` 中登记的素材
   - ⚠️ `company_type=own` 案例可作为结构和话术参考,**但不能整段复制**——具体素材应到 `assets/` 取

### 8.2 扫描其他子目录

同时浏览以下子目录,吸收与当前项目相关的内容:

- `references/knowledge_base/评标专家偏好/` —— 调整章节笔墨权重,把评委关注的点写得更扎实
- `references/knowledge_base/行业术语对照/` —— 确保正文术语符合本行业规范,避免"外行话"
- `references/knowledge_base/失败教训/` —— 在阶段 5 合规终审中作为额外检查项

---

## 九、辅助工作流:素材摄入(已知分类)

### 9.1 触发条件

用户**明确说出**类别和公司归属。例如:
- "处理业绩 inbox"(默认 own_default 公司,如有歧义需确认)
- "处理 own_jiao 公司的简历 inbox"
- "处理 partner_xinda 的资质 inbox"
- "把 _inbox 里的东西摄入"(必须先确认类别和公司)

### 9.2 执行步骤

**首选方式:调用现成脚本 `ingest_assets.py`,自动完成 a-g 全部子步骤。**

```
bash run_script.sh ingest_assets.py <类别> <company_id>
# 例:bash run_script.sh ingest_assets.py 业绩 own_default
# 类别支持中文(资质/业绩/简历/图表/话术)或英文别名(qualification/performance/resume/chart/phrase)
```

脚本会自动:
- 校验 `company_id` 存在于 `companies.yaml`(不存在则报错并提示走"新增公司"流程)
- 拒绝 `company_type=reference` 的公司(reference 不能进 assets 摄入流程)
- 遍历 `_inbox/` 下每个文件,自动跳过 `.gitkeep`
- 调用 `extract_text.py` 提取文本和 sha256
- 检查 `.ingest_history.json` 去重,重复文件跳过并在报告中列出
- 按 schema 生成结构化 .md(`company_id` / `company_type` 从目录推断,`review_status=pending`,缺失字段标 `TODO:待人工确认`)
- 追加索引行到对应 CSV 或 markdown 索引表
- 把原文件移动到 `_raw/`,文件名加时间戳前缀 `YYYYMMDD_<原文件名>`
- 更新 `.ingest_history.json`
- 输出"处理成功 / 重复跳过 / 处理失败"统计 + 每条新生成 .md 的 TODO 字段清单

**AI 在脚本跑完后必须做的事(脚本不能替代):**

1. **逐个 review** 新生成的 .md,补全脚本无法自动推断的 TODO 字段(尤其是甲方单位、合同金额、关键技术等关键字段——脚本只是用正则做粗糙的提取,该校验的还要校验)
2. **检查事实性**:脚本生成的字段是从原文里"猜"的,可能猜错。AI 应当通读 `_raw/` 下的归档原文,核对 frontmatter 是否真实
3. **不允许直接把 review_status 改为 approved**——这一步必须等用户人工确认后由用户或 AI 在用户明确指示下操作
4. 如果脚本报"处理失败",查看失败原因。最常见的是 .doc 旧格式不支持,需要用户先用 Word 另存为 .docx 后再放入 inbox

**手工兜底**:如果脚本因某种原因不可用(例如 Python 环境异常、用户在方式三纯对话 AI 下使用),AI 必须按以下手工步骤完成等价工作:

a. 通过 `bash run_script.sh extract_text.py "<文件路径>"` 提取文本和 sha256(或在方式三下让用户手工提供文本)
b. 读取 `assets/.ingest_history.json`,**检查 sha256 去重**
c. 读取同类的 `<类别>schema.md`(业绩 schema / 简历 schema / ...)
d. **严格按 schema 输出结构化 .md**(`company_id` / `company_type` 从目录推断,`review_status=pending`,缺失字段标 `TODO:待人工确认`,文件末尾追加 `## TODO 清单`)
e. **追加索引**:业绩/简历追加一行到 CSV,资质/图表/话术追加一行到 .md 索引表(每行冗余 `company_id` 和 `company_type`)
f. **归档原文件**:从 `_inbox/` 移动到 `_raw/`,加时间戳前缀
g. **更新 `.ingest_history.json`**

**摄入完成后的报告必须包含**:
- ✅ 处理清单:本次摄入的所有文件
- 📂 生成路径:每份文件对应的目标 .md 路径
- ⏭️ 跳过清单:因 sha256 重复而跳过的文件
- 📋 TODO 清单:汇总所有待人工确认的字段
- 👀 待 review 清单:所有 `review_status=pending` 的新增条目

### 9.3 摄入完成后的人工动作

提醒用户:
- 逐个 review 新生成的 .md,补全 TODO 字段
- 把 `review_status` 从 `pending` 改为 `approved`
- 删除 .md 末尾的 `## TODO 清单` 区块
- **只有 `approved` 状态的素材才能被新标书引用**

---

## 十、辅助工作流:分类 triage(未知分类)

### 10.1 触发条件

用户的描述**含混或不确定分类**。例如:
- "处理 _inbox_unsorted"
- "我有一堆材料不知道怎么分类"
- "这堆东西里有简历有业绩有合同,你帮我分一下"

### 10.2 执行步骤

**首选方式:分两步调用 `triage_unsorted.py`,先看建议、再执行分发。**

```
# 第一步:只看建议,不分发(默认行为)
bash run_script.sh triage_unsorted.py

# 第二步:用户确认建议后,再执行分发(会触发已知分类摄入流程)
bash run_script.sh triage_unsorted.py --apply
```

第一步会:
- 扫描 `_inbox_unsorted/` 下所有非 `.gitkeep` 的文件
- 对每份文件调用 `extract_text.py` 提取文本
- 用关键词规则推断**目标类别**(业绩 / 简历 / 资质 / 历史案例 / 图表 / 话术)
- 通过文本和文件名匹配 `companies.yaml` 中已注册公司的名称和别名,推断**目标公司**
- 输出分类建议清单(每条含类别、公司、判断理由、目标路径)

**🔴 不允许直接执行 `--apply` 而跳过用户确认。** 必须先让用户逐条 review 第一步的建议:

- 类别建议是否准确(脚本只是基于关键词,可能误判)
- 公司归属是否正确(尤其是脚本未识别到公司归属时,显示为"【待确认】")
- 是否有新公司需要先注册(若有,触发章节十一"新增公司"工作流)

第二步 (`--apply`) 会:
- 对 `own` / `partner` 类别:把文件副本放入对应 `assets/<类别>/<公司>/_inbox/`,然后**自动触发** `ingest_assets.py` 完成已知分类摄入流程
- 对 `历史案例` / `reference` 类别:把副本放入 `references/knowledge_base/历史标书案例/_inbox/`(🔴 **严禁**进入 `assets/`)
- 公司归属未识别的文件**会被脚本跳过并标记为"未识别公司归属"**——这是预期行为,要求用户先注册公司后再重跑
- 原文件移动到 `_inbox_unsorted/_raw/`,文件名加时间戳前缀

**AI 必须做的事(脚本不能替代):**

1. **第一步建议输出后立即停下,与用户对齐**——脚本不会停下问你,但 AI 在 SKILL 工作流下必须停下确认
2. **关键词规则会有误判**——例如一份"投标文件"可能是 own/partner 的历史案例,也可能是 reference 的竞品分析,需要 AI 结合文件来源判断
3. **公司未识别时的处理**:脚本会在 `--apply` 中跳过未识别公司的文件。AI 应主动询问用户"这份文件应归属哪家公司?",必要时先走"新增公司"流程
4. **生成 triage 报告**:在脚本输出之外,AI 还要给用户写一份易读的总结报告,列出每份源文件被拆分到的所有目标位置(一份源文件可能产生多个目标 .md)

### 10.3 严格禁止(高压线,违反即停止)

- 🔴 **严禁未经用户确认就自动分类**
- 🔴 **严禁把任何材料默认归为 own**(必须明确询问公司归属)
- 🔴 **严禁把 `company_type=reference` 的材料写入 `assets/`**(只能进 `references/knowledge_base/`)
- 🔴 **对公司归属有任何不确定时,必须主动询问用户**,不允许"猜"
- 🔴 **严禁将招标文件本身或甲方提供的项目材料**(无论 own / partner / reference)摄入 `assets/` 或 `knowledge_base/`——这些是项目数据,应保留在 `projects/<项目名>/00_招标文件原件/` 下

---

## 十一、辅助工作流:新增公司

### 11.1 触发条件

- 用户说"新增公司"、"注册一家新合作方"、"加一个 partner"等
- 在执行其他工作流(尤其是章节九摄入和章节十 triage)时,检测到引用了 `companies.yaml` 中**未注册**的公司

### 11.2 执行步骤

1. **询问用户**:
   - 公司**全称**(必填)
   - 公司**简称 / 别名**(选填,作为 `aliases`,可有多个)
   - **类型**:own / partner / reference(必填,务必让用户明确选择)
   - 简要**描述**(选填)

2. **调用脚本完成注册和目录初始化**:

   ```
   bash run_script.sh add_company.py "公司全称" <own|partner|reference> [--alias 别名] [--description 描述] [--id 自定义id]
   # 例:bash run_script.sh add_company.py "信达科技有限公司" partner --alias 信达
   ```

   脚本会自动:
   - 基于公司全称(优先用拼音,fallback 到 ASCII / sha1)生成简短 id,前缀按类型区分:`own_xxx` / `partner_xxx` / `ref_xxx`
   - 检查 id 是否已存在,冲突时自动加序号
   - 在 `companies.yaml` 末尾追加完整条目(`id` / `name` / `type` / `description` / `aliases` / `created_at`)
   - 若类型为 **own** 或 **partner**:在 `assets/` 下每个类别子目录创建 `<新 id>/` 子目录,含 `_inbox/.gitkeep` / `_raw/.gitkeep` / 索引文件骨架(`资质清单.md` / `业绩列表.csv` / `简历索引.csv` / `图表索引.md` / `话术索引.md`)
   - 若类型为 **reference**:🔴 **严禁**在 `assets/` 下创建任何目录。脚本会跳过目录初始化,只往 `companies.yaml` 写一条记录
   - 输出新增报告:id、全称、类型、别名、已创建的目录列表

3. **AI 在脚本调用前必须做的事**:
   - **生成 id 后向用户确认**——脚本默认会基于公司全称自动生成 id(例如"信达科技有限公司"→`partner_xindakejiyouxiangongsi`),AI 应当**先把建议的 id 给用户看,允许用户用 `--id` 参数指定一个更短的版本**(如 `partner_xinda`)
   - **明确 own/partner/reference 类型**——这是高压线决策,不允许 AI 默认归为 own
   - 别名 `--alias` 可以传多次,把公司常用的简称都登记进去,这样后续 triage 流程才能从文件中识别到归属

4. **手工兜底**(脚本不可用时):

   - 在 `companies.yaml` 末尾按现有格式追加一条记录(注意 yaml 缩进 2 空格,`aliases` 用 `[a, b]` 数组格式)
   - 若类型为 own/partner,手工在 `assets/` 下每个类别子目录新建 `<新 id>/{_inbox/.gitkeep, _raw/.gitkeep, 索引文件骨架}`
