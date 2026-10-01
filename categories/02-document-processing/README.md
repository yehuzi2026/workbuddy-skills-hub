# 📄 文档解析与排版 / Document Processing

> 文档转 Markdown、纯离线抽取、标书页码回填、方案排版、OCR 与商务展板统计表生成。

**本分类共 6 个技能。**


| 技能文件夹 | 名称 | 简介 |
| --- | --- | --- |
| `markitdown-skill` | markitdown-skill | Convert documents to Markdown using Microsoft's MarkItDown CLI (`markitdown`). Supports PD… |
| `offline-office-extract` | offline-office-extract | 纯离线文档抽取（零依赖安装）。当沙箱/环境无法安装 pywin32、pymupdf、markitdown、RapidOCR 等第三方库（pip 经代理下载超时、无 LibreOff… |
| `docx-fill-pageindex` | docx-fill-pageindex | 给 .docx 里的表格填数据，并自动回填「证明文件所在页码」这类需要真实排版页码的列。做法：python-docx 填格（保留原格式）→ 用 PowerShell 工具调本机 W… |
| `标书方案排版--小羊羊AI` | 标书方案排版--小羊羊AI | > |
| `hybrid-image-ocr` | hybrid-image-ocr | 图片识别 / OCR 提取 / 表格识别 / 证件印章识别 Skill，专为做标书设计。混合模式：本地离线优先（RapidOCR，隐私不出本机），遇到模糊/复杂图片自动回退云端视觉… |
| `展板统计表生成` | 展板统计表生成 | 生成「藏青+米金」商务展板风格的统计表（序号/类目/数量/占比 + 合计行 + 说明框），输出高清 PNG 可直接插入标书/报告。当用户说「做一个类似这张图的数据表」「做个统计表」… |

## 安装

将本分类下对应的技能文件夹整体复制到 WorkBuddy 用户级技能目录：

```bash
# Windows
xcopy "%USERPROFILE%\.workbuddy\skills"  # 放入对应子文件夹
# 或直接把某个技能文件夹复制到 (Windows 示例):
C:\Users\<你>\.workbuddy\skills\<技能名>
```

放入后重启 WorkBuddy 即可在对话中触发。
