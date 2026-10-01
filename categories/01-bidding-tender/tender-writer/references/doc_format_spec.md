# 中文政府类技术标排版规范

> 本规范适用于中文政府类项目技术标书的标准排版,
> 是 `scripts/docx_builder.py` 生成 docx 时套用的默认样式。
> 若招标文件对格式有特殊要求,**以招标文件为准**,在 docx_builder.py 中临时覆盖默认值。

---

## 一、页面设置

| 项目 | 规格 |
|---|---|
| 纸张 | A4 纵向(21.0 × 29.7 cm) |
| 上边距 | 2.54 cm |
| 下边距 | 2.54 cm |
| 左边距 | 3.17 cm |
| 右边距 | 3.17 cm |
| 装订线 | 0 cm(装订靠左边距) |
| 页眉边距 | 1.5 cm |
| 页脚边距 | 1.75 cm |

> 说明:这是 Word 默认的"普通"页边距。政府类标书最常见的就是这一组,基本不出错。

---

## 二、字体字号(标书正文)

| 元素 | 中文字体 | 西文字体 | 字号 | 加粗 | 对齐 |
|---|---|---|---|---|---|
| 封面主标题 | 黑体 | Times New Roman | 二号 22pt | 是 | 居中 |
| 封面副标题 / 项目名 | 宋体 | Times New Roman | 小二 18pt | 是 | 居中 |
| "目  录"二字 | 黑体 | Times New Roman | 三号 16pt | 是 | 居中 |
| 一级标题 H1(章) | 黑体 | Times New Roman | 三号 16pt | 是 | 左对齐 |
| 二级标题 H2(节) | 黑体 | Times New Roman | 小三 15pt | 是 | 左对齐 |
| 三级标题 H3(条) | 黑体 | Times New Roman | 四号 14pt | 是 | 左对齐 |
| 四级标题 H4(款) | 黑体 | Times New Roman | 小四 12pt | 是 | 左对齐 |
| 正文 | 宋体 | Times New Roman | 四号 14pt | 否 | 两端对齐 |
| 表格表头 | 仿宋_GB2312 | Times New Roman | 五号 10.5pt | 是 | 水平垂直居中 |
| 表格内容(短文本) | 仿宋_GB2312 | Times New Roman | 五号 10.5pt | 否 | 水平垂直居中 |
| 表格内容(长文本) | 仿宋_GB2312 | Times New Roman | 五号 10.5pt | 否 | 左对齐 + 垂直居中 |
| 图注 / 表注 | 宋体 | Times New Roman | 五号 10.5pt | 否 | 居中 |
| 页眉 / 页脚 | 宋体 | Times New Roman | 小五 9pt | 否 | 居中 |

> ⚠️ python-docx 设置中文字体必须用 XML 设置 `w:eastAsia`,只设 `font.name` 不生效。
> 详见 `scripts/docx_builder.py` 中的 `set_run_font` 工具函数。

---

## 三、段落规范

| 项目 | 规格 |
|---|---|
| 正文行距 | 1.5 倍行距(或固定值 28 磅) |
| 正文首行缩进 | 2 字符 |
| 段前段后 | 0 磅(所有段落,含标题、正文) |
| 标题对齐 | 左对齐(不缩进) |
| 标题段前 | 0 磅 |
| 标题段后 | 0 磅 |

> 说明:不再用段前段后留白,而是依靠 1.5 倍行距和首行缩进自然区分层次。
> 这是当前主流标书排版的做法,简洁且不浪费版面。

---

## 四、目录规范

- 使用 Word 内置 TOC 域**自动生成**目录
- 目录页标题"目  录"两字之间空两格,黑体三号居中
- 目录条目使用 Word 内置目录样式(TOC 1 / TOC 2 / TOC 3)
- 目录最多显示三级标题,四级标题不入目录
- 目录与正文之间插入分页符

```python
# python-docx 中插入自动目录的伪代码
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

def insert_toc(paragraph):
    """在段落处插入 Word 目录域(TOC),Word 打开后按 F9 更新"""
    run = paragraph.add_run()
    fldChar1 = OxmlElement('w:fldChar')
    fldChar1.set(qn('w:fldCharType'), 'begin')
    instrText = OxmlElement('w:instrText')
    instrText.set(qn('xml:space'), 'preserve')
    instrText.text = 'TOC \\o "1-3" \\h \\z \\u'
    fldChar2 = OxmlElement('w:fldChar')
    fldChar2.set(qn('w:fldCharType'), 'separate')
    fldChar3 = OxmlElement('w:fldChar')
    fldChar3.set(qn('w:fldCharType'), 'end')
    run._element.append(fldChar1)
    run._element.append(instrText)
    run._element.append(fldChar2)
    run._element.append(fldChar3)
```

---

## 五、图表编号

- 使用 Word 的 SEQ 域代码自动编号(打开 Word 按 F9 刷新)
- 图编号格式:`图 1-1 xxx 架构图`(章节号 - 顺序号)
- 表编号格式:`表 1-1 xxx 对照表`(章节号 - 顺序号)
- 图注位于图下方,表注位于表上方
- 图表编号字体:宋体五号,居中

```python
# SEQ 域代码插入示例
def insert_seq_field(paragraph, seq_name="图"):
    """插入 SEQ 域,自动连续编号"""
    run = paragraph.add_run()
    fldChar1 = OxmlElement('w:fldChar')
    fldChar1.set(qn('w:fldCharType'), 'begin')
    instrText = OxmlElement('w:instrText')
    instrText.set(qn('xml:space'), 'preserve')
    instrText.text = f' SEQ {seq_name} \\* ARABIC '
    fldChar2 = OxmlElement('w:fldChar')
    fldChar2.set(qn('w:fldCharType'), 'end')
    run._element.append(fldChar1)
    run._element.append(instrText)
    run._element.append(fldChar2)
```

---

## 六、页眉与页脚

- **页眉**:左上角写项目名称(简称),右上角写"投标文件 - 技术标"
- **页脚**:居中写"第 X 页 共 Y 页"
- 页眉与正文之间用 0.75 磅细黑线分隔
- 封面、目录页**不加**页眉页脚(从正文第一章开始)

---

## 七、特殊场景切换

### 场景 A:招标文件要求按公文格式(GB/T 9704-2012)
- 正文:**仿宋_GB2312 三号(16pt)**
- 一级标题:**黑体 三号**
- 二级标题:**楷体_GB2312 三号**
- 三级标题:**仿宋_GB2312 三号 加粗**
- 四级标题:**仿宋_GB2312 三号**
- 行距:固定值 28 磅
- 页边距:上 3.7 cm / 下 3.5 cm / 左 2.8 cm / 右 2.6 cm

### 场景 B:招标文件要求按需求规格说明书 GB 标准
- 正文:**宋体 小四(12pt)**
- 标题层级与本文档第二节一致
- 行距:1.5 倍

---

## 八、常见排版错误清单

- ❌ 标题用了空格缩进而不是样式(导致目录抓不到)
- ❌ 正文每段前手动空两格(应使用首行缩进 2 字符)
- ❌ 表格内容字号过大,一页放不下一行
- ❌ 中英文字体没分开设置,导致英文用中文字体显示丑陋
- ❌ 页眉页脚出现在封面页(应从正文第一页开始)
- ❌ 图表编号手写,新增/删除图表后编号错乱
- ❌ 目录手写,正文页码变动后目录失效

---

## 九、docx_builder.py 应用本规范的接口约定

`scripts/docx_builder.py` 提供以下统一接口,其他脚本通过 import 调用:

```python
from docx_builder import (
    create_tender_doc,           # 创建标书空骨架(封面 + 目录 + 页眉页脚)
    set_run_font,                # 设置某个 run 的中英文字体字号
    apply_default_styles,        # 把本规范应用到文档的 Normal/Heading 1~4 样式
    add_chapter,                 # 追加一章(自动套用样式)
    add_paragraph,               # 追加一段正文(自动首行缩进)
    add_table,                   # 追加一张表格(自动套用表格样式)
    insert_toc,                  # 插入自动目录
    insert_seq_field,            # 插入 SEQ 域(图表编号)
    set_page_margins,            # 设置页边距
)
```

所有接口的实现细节见 `scripts/docx_builder.py` 源码。
