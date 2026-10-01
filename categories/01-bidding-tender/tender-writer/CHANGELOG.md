# Changelog

## [1.1.0] - 2026-04-13

### Added
- 五阶段工作流(招标解析 → 评分矩阵 → 提纲反推 → 分章节撰写 → 合规终审)
- own/partner/reference 三级素材隔离机制
- 支持 4 种使用方式(Claude Code / Cline 类 / 纯对话 AI / 手动)
- 自包含 venv 环境,install.bat 一键准备
- 素材入库三入口(已知分类 / unsorted triage / 新增公司)
- 合规终审自动核查漏答与废标风险

### Known Limitations
- 仅支持中文政府类项目技术标
- 扫描件 PDF 需先 OCR
- 不处理商务标与价格标
