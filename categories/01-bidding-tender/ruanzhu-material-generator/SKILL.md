---
name: ruanzhu-material-generator
description: 软著鉴别材料生成专家。针对版权中心「模板化」补正/新申请，用「真实搭建系统→真实截图→真实代码截取」路线产出源程序鉴别材料（前30+后30页PDF）与文档鉴别材料（用户手册docx/PDF）。触发词：软著材料、软著补正、源程序鉴别材料、文档鉴别材料、软著被驳回、模板化补正
version: 1.1.0
agent_created: true
---

# 软著鉴别材料生成（真实系统路线）

## 核心理念

版权中心对「模板化」材料的审查本质是查「AI 拼凑、无真实软件对应」。仅改文字二次驳回率高。
**唯一稳的路线：让软件真实存在** —— 搭可运行系统 → 浏览器真实操作截图 → 从真实代码截取源程序材料 → 手册与代码严格对应。

## 环境准备（本机已就绪）

- JDK17 + Maven 3.9.16：`C:/Users/Administrator/.workbuddy/binaries/java/`（清华镜像下载）
- Maven 阿里云镜像 settings：工程 `maven/settings-aliyun.xml`（`-s` 指定）
- **启动系统**：Git Bash 里 Unix `mvn` 脚本报 `ClassNotFoundException: classworlds`（PATH 混入 Unix 路径所致）。必须调 `mvn.cmd` 且 `JAVA_HOME` 用 Windows 格式（`C:\\...`）；最稳做法：工程里放 `run.bat`（set JAVA_HOME/MAVEN_HOME + call mvn.cmd），Bash 后台 `cmd //c run.bat > run.log 2>&1` 或 PowerShell 起停
- PDF 生成：venv（`.workbuddy/binaries/python/envs/default/`）`pip install reportlab pypdf pymupdf`
- Word 文档：`pip install python-docx`；PDF 直接用 reportlab platypus 双渲染（见下），不依赖 Word COM

## 流水线 v2.0（内容块 + 双渲染，推荐）

一次编写、两份输出，参考 `honggang-auction-platform/scripts/`：

1. `extract_dict.py` — 正则扫描 `domain/*.java`（@Table/字段/注释）→ `dict.json` 数据字典（表名/字段/类型/长度/可空/说明），手册数据字典章节自动生成，保证与代码零偏差
2. `manual_content.py` — 手册全部内容定义为内容块列表 BLOCKS（cover/h1/h2/p/steps/bullet/table/shot），所有数字、公式、编号规则从源码 grep 取证
3. `gen_manual_docx.py` — BLOCKS → docx（python-docx，页眉软件名+PAGE 域页码）
4. `gen_manual_pdf.py` — BLOCKS → PDF（reportlab platypus，页眉页脚 onPage 回调）
5. `gen_source_pdf.py` — 源程序 PDF（见下）
6. `shot.sh` — 一体化截图脚本（见铁律）

## 源程序 PDF 规范要点

- **真实「前30+后30」**：`selected = lines[:1500] + lines[-1500:]`（v1.0 只取 `[:3000]` 是错的，后30页必须来自工程尾段）；页码连续 1-60
- 每页 50 行、宋体 8.8~9pt、页眉「软件名V版本 + 第X页/共60页」、超长行截/折行处理
- 文件顺序按工程包结构（启动类→domain→repository→service→web→config→bootstrap→前端→yml），pypdf 校验：60页、每页≥50行、P31 起为前端代码、P60 为源码流最后几行

## agent-browser 铁律（v1.1 补强）

1. **守护进程跨 Bash 调用必丢/卡死**：`set viewport` 也会卡死。最稳方案：把 open→登录→逐页签截图全流程写进一个 `.sh`（函数式：`ab(){ agent-browser "$@" >>log 2>&1; }`），**Bash 后台执行该脚本**，轮询 log
2. 切 SPA 页签：`agent-browser eval "document.querySelectorAll('.menu-item')[i].click()"` + wait 3000 后截图
3. 截图绝对路径；静态资源 no-store（否则改页后截图字节级不变）
4. open 单独后台跑会成功但后续跨 shell 命令全卡——**全流程必须同 shell**

## 头号技术坑：in-DOM 模板自闭合标签

HTML 里直接写 Vue 模板时 `<el-table-column ... />` 会被 HTML 解析器视为未闭合标签，**吞掉后续兄弟节点**（与车拍拍 chepaipai-template-fix 同源）。症状：表格表头竖排堆叠、列错乱、el-table header 宽度异常（如 280px）。
修复：正则批量展开 `<(el-[\w-]+)((?:"[^"]*"|[^"<>])*)/>` → `<\1\2></\1>`（Python 脚本，处理后 grep 校验 0 残留）。写 Vue in-DOM 模板时**永远不用自闭合**。

## 交付前质量验证清单

1. pypdf 校验源程序：60 页 / 每页≥50 行 / P31 起为尾段代码
2. 全文提取校验手册：11 张表名、全部接口路径、关键算法数字（权重/阈值/费率）逐一在册
3. **雷同自查**：新旧材料 PDF 提取 token（≥6字符）求交集，过滤 Java 框架通用词后业务标识应为 0 交集
4. pymupdf 渲染抽查排版：表格长字段名是否折行（数据字典第一列宽 0.19）、末页是否孤行（缩短末段文字收页）

## 参考实现

- v2.0 流水线（内容块+双渲染+数据字典自动提取）：`WorkBuddy/2026-09-10-18-19-32/honggang-auction-platform/scripts/`
  （交付：`桌面/2/软著/补正材料-拍卖决策系统/`，2026-09-11，60页源程序+20页手册）
- v1.0 参考：`WorkBuddy/2026-09-10-18-19-32/honggang-road-platform/`（交付：`桌面/2/软著/补正材料/`）
- ⚠️ 多件软著并行时交付目录必须按软件名分开（`补正材料-<软件名>/`），避免新旧材料混淆
