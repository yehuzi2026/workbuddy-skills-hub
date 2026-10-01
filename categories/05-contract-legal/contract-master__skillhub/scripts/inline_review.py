"""
原文件修订工具 - 直接在原文件上添加修订和批注
直接在原 .docx 文件上操作，保留原文档格式
"""
import os
import sys
import re
import shutil
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET
from typing import List, Dict, Optional, Tuple

# OOXML 命名空间
NAMESPACES = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'w14': 'http://schemas.microsoft.com/office/word/2010/wordml',
    'w15': 'http://schemas.microsoft.com/office/word/2012/wordml',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
    'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
    'dc': 'http://purl.org/dc/elements/1.1/',
}

# 注册命名空间
for prefix, uri in NAMESPACES.items():
    ET.register_namespace(prefix, uri)


class RevisionItem:
    """修订项"""
    def __init__(self, old_text: str, new_text: str, reason: str,
                 change_type: str = "modify", clause_title: str = "",
                 risk_level: Optional[str] = None):
        self.old_text = old_text
        self.new_text = new_text
        self.reason = reason
        self.change_type = change_type  # insert, delete, modify
        self.clause_title = clause_title
        # 风险等级标签（值如 RiskLevel.author_name / RiskLevel.initials），
        # 未指定时回退到 self.author
        self.risk_level = risk_level


class CommentItem:
    """批注项"""
    def __init__(self, text: str, reason: str, location: str = "",
                 legal_basis: str = "", suggestion: str = "",
                 risk_level: Optional[str] = None):
        self.text = text
        self.reason = reason
        self.location = location
        self.legal_basis = legal_basis
        self.suggestion = suggestion
        # 风险等级标签（值如 RiskLevel.author_name）
        self.risk_level = risk_level


class InlineReviewer:
    """
    原文件修订工具
    直接在原 .docx 文件上添加修订和批注
    """
    
    def __init__(self, original_docx_path: str, output_path: str = None, 
                 author: str = "AI审核助手"):
        self.original_docx_path = original_docx_path
        self.output_path = output_path or original_docx_path.replace('.docx', '_修订版.docx')
        self.author = author
        self.date = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # 临时解压目录
        self.temp_dir = None
        
        # 修订和批注列表
        self.revisions: List[RevisionItem] = []
        self.comments: List[CommentItem] = []
        
        # 修订/批注ID计数器
        self.revision_id = 100
        self.comment_id = 100
        
        # 记录所有批注（用于生成 comments.xml）
        self.comment_records = []
    
    def _extract_docx(self) -> str:
        """解压 docx 文件"""
        import tempfile
        self.temp_dir = tempfile.mkdtemp(prefix='docx_review_')
        
        with zipfile.ZipFile(self.original_docx_path, 'r') as zip_ref:
            zip_ref.extractall(self.temp_dir)
        
        return self.temp_dir
    
    def _pack_docx(self) -> bool:
        """重新打包 docx 文件"""
        if not self.temp_dir:
            return False
        
        # 创建新的 docx 文件
        with zipfile.ZipFile(self.output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, self.temp_dir)
                    zipf.write(file_path, arc_name)
        
        # 清理临时目录
        shutil.rmtree(self.temp_dir)
        self.temp_dir = None
        
        return True
    
    def _read_xml(self, xml_path: str) -> Optional[str]:
        """读取 XML 文件"""
        full_path = os.path.join(self.temp_dir, xml_path)
        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None
    
    def _write_xml(self, xml_path: str, content: str):
        """写入 XML 文件"""
        full_path = os.path.join(self.temp_dir, xml_path)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def _create_comment_xml(self) -> str:
        """仅返回新批注的 XML 片段（不含外层 <?xml?><w:comments> 头）。

        设计：让 _ensure_comments_files 决定是"新建完整文件"还是"merge 到旧文件"。
        这样原 docx 已有旧批注时不会被覆盖丢失。
        """
        if not self.comment_records:
            return ""

        fragments = []
        for i, comment in enumerate(self.comment_records):
            comment_id = self.comment_id + i  # 起点避让已有批注
            comment_date = comment.get('date', self.date)
            comment_author = comment.get('author', self.author)
            comment_text = self._escape_xml(comment.get('text', ''))
            comment_reason = self._escape_xml(comment.get('reason', ''))
            comment_legal = self._escape_xml(comment.get('legal_basis', ''))
            comment_suggestion = self._escape_xml(comment.get('suggestion', ''))

            # 组合批注内容
            full_comment = f"{comment_text}"
            if comment_reason:
                full_comment += f"\n\n【修改理由】\n{comment_reason}"
            if comment_legal:
                full_comment += f"\n\n【法律依据】\n{comment_legal}"
            if comment_suggestion:
                full_comment += f"\n\n【修改建议】\n{comment_suggestion}"

            fragments.append(
                f'<w:comment w:id="{comment_id}" w:author="{comment_author}" '
                f'w:date="{comment_date}" w:initials="AI">'
                f'<w:p><w:r><w:t xml:space="preserve">'
                f'{self._escape_xml(full_comment)}'
                f'</w:t></w:r></w:p></w:comment>'
            )
        return "\n".join(fragments)

    def _build_complete_comments_xml(self) -> str:
        """根据是否已有 comments.xml 决定策略，组装最终完整 XML。"""
        fragments = self._create_comment_xml()
        if not fragments:
            return ""

        existing = self._read_xml('word/comments.xml')
        if not existing:
            # 没有旧文件：用完整模板
            return (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
                'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">\n'
                + fragments + '\n</w:comments>'
            )

        # 有旧文件：在 </w:comments> 之前插入新片段
        # 防御性：去掉旧文件结尾的空白行，避免 merge 产生多余空行
        existing_trimmed = re.sub(r'\s*$', '', existing)
        insert_pos = existing_trimmed.find('</w:comments>')
        if insert_pos < 0:
            # 旧文件结构异常，回退到覆盖
            return existing_trimmed + '\n' + fragments + '\n</w:comments>'
        return existing_trimmed[:insert_pos] + fragments + '\n' + existing_trimmed[insert_pos:]
    
    def _escape_xml(self, text: str) -> str:
        """转义 XML 特殊字符"""
        if not text:
            return ""
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        text = text.replace('"', '&quot;')
        text = text.replace("'", '&apos;')
        return text
    
    def _scan_max_comment_id(self) -> int:
        """扫描原 docx 已有的批注最大 w:id，避免新批注 id 冲突。

        Edge case: 若原文件已被其他工具审过、有旧批注，self.comment_id 必须
        从 max+1 开始，否则会触发 Word 报"批注引用不唯一"的修复对话框。
        """
        existing = self._read_xml('word/comments.xml')
        if not existing:
            return 0
        ids = re.findall(r'w:id="(\d+)"', existing)
        return max([int(i) for i in ids]) if ids else 0

    def _scan_max_rel_id(self) -> int:
        """扫描 word/_rels/document.xml.rels 中已用的最大 rId。"""
        rels = self._read_xml('word/_rels/document.xml.rels')
        if not rels:
            return 0
        rids = re.findall(r'Id="rId(\d+)"', rels)
        return max([int(r) for r in rids]) if rids else 0

    def _ensure_comments_files(self):
        """确保批注相关文件存在（OOXML parts 自检）

        Word 在打开含批注的 docx 时需要三件套同时存在：
        1) word/comments.xml（批注本身）
        2) word/_rels/document.xml.rels（关联关系）
        3) [Content_Types].xml（ContentType 注册）
        缺任意一个 Word 都打不开，或弹出"文件已损坏"对话框。
        本方法做"自检+补齐"，无论原文件本来有没有批注。
        """
        # 0) 让新批注 id 起点避开已有批注。
        # 注意：self.comment_id 默认是 100（保证比手写 id 大），但若原文件
        # 已有 200 个旧批注（base=200），100 < 201，必须把起点抬到 201。
        base = self._scan_max_comment_id()
        if self.comment_id <= base:
            self.comment_id = base + 1

        # 1. 创建或 merge comments.xml（保留旧批注，追加新批注）
        comments_xml = self._build_complete_comments_xml()
        if comments_xml:
            self._write_xml('word/comments.xml', comments_xml)

        # 2. 更新 [Content_Types].xml
        content_types = self._read_xml('[Content_Types].xml')
        if content_types and 'comments.xml' not in content_types:
            # 处理自闭合 <Types .../> 边界
            insert_pos = content_types.find('</Types>')
            if insert_pos > 0:
                new_content = (
                    content_types[:insert_pos]
                    + '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
                    + content_types[insert_pos:]
                )
                self._write_xml('[Content_Types].xml', new_content)
            else:
                # 自闭合边界：append 一个新的 Types 根（极少见，仅防御）
                new_content = content_types.replace(
                    '/>',
                    '><Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/></Types>',
                    1,
                )
                if 'Override' not in new_content:
                    new_content = content_types  # 兜底，不破坏原文件
                self._write_xml('[Content_Types].xml', new_content)

        # 3. 更新 word/_rels/document.xml.rels
        rels_path = 'word/_rels/document.xml.rels'
        rels = self._read_xml(rels_path)
        if rels and 'comments.xml' not in rels:
            new_rid = self._scan_max_rel_id() + 1
            insert_pos = rels.find('</Relationships>')
            if insert_pos > 0:
                new_rels = (
                    rels[:insert_pos]
                    + f'<Relationship Id="rId{new_rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>'
                    + rels[insert_pos:]
                )
                self._write_xml(rels_path, new_rels)

        # 4. 防御性：document.xml 缺 w14/w15 命名空间声明时，Word 也能容忍（不报错）
        #    这里只做最小声明检查，不再额外修补
        doc_xml = self._read_xml('word/document.xml')
        if doc_xml and 'xmlns:w14' not in doc_xml:
            # 不强行插入，避免破坏原文档结构；仅打印提示
            print("  ℹ️ document.xml 缺 w14 命名空间声明，Word 通常能容忍")
    
    def add_revision(self, revision: RevisionItem):
        """添加修订项"""
        self.revisions.append(revision)

    def add_comment(self, comment: CommentItem):
        """添加批注项"""
        self.comments.append(comment)
        # 优先用 per-comment 的 risk_level（author_name 形式）作为 Word 批注的 author
        # 留空时回退到顶层 self.author
        author_for_word = comment.risk_level or self.author
        self.comment_records.append({
            'text': comment.text,
            'reason': comment.reason,
            'legal_basis': comment.legal_basis,
            'suggestion': comment.suggestion,
            'author': author_for_word,
            'date': self.date
        })

    def add_revision_with_comment(self, old_text: str, new_text: str,
                                   reason: str, clause_title: str = "",
                                   legal_basis: str = "", suggestion: str = "",
                                   change_type: str = "modify",
                                   risk_level: Optional[str] = None):
        """添加带批注的修订

        risk_level: 形如 "AI-🔴高风险" 的 author_name；未指定时回退到 self.author。
        """
        revision = RevisionItem(old_text, new_text, reason, change_type,
                                clause_title, risk_level=risk_level)
        self.add_revision(revision)

        comment = CommentItem(
            text=f"建议修改：{new_text if new_text else '(删除)'}",
            reason=reason,
            legal_basis=legal_basis,
            suggestion=suggestion,
            risk_level=risk_level
        )
        self.add_comment(comment)
    
    def process_document(self) -> bool:
        """
        处理文档：应用修订和批注
        
        策略：
        1. 解压原文档
        2. 解析 document.xml
        3. 在指定位置添加修订标记和批注
        4. 更新相关配置文件
        5. 重新打包
        """
        try:
            # 1. 解压文档
            self._extract_docx()
            
            # 2. 读取 document.xml
            doc_xml = self._read_xml('word/document.xml')
            if not doc_xml:
                print("❌ 无法读取 document.xml")
                return False
            
            # 3. 应用修订和批注
            modified_xml = self._apply_revisions_and_comments(doc_xml)
            
            # 4. 确保批注文件存在
            self._ensure_comments_files()
            
            # 5. 写回 document.xml
            self._write_xml('word/document.xml', modified_xml)
            
            # 6. 重新打包
            return self._pack_docx()
            
        except Exception as e:
            print(f"❌ 处理文档时出错: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _apply_revisions_and_comments(self, doc_xml: str) -> str:
        """
        应用修订和批注到 document.xml

        对于简单的文本替换，我们采用以下策略：
        1. 找到包含目标文本的 <w:t> 元素
        2. 将文本替换为带有修订标记的 XML
        """
        # 为了简化，我们使用字符串替换方式
        # 对于复杂的修订，需要使用 DOM 解析

        result = doc_xml

        # 处理修订
        for i, revision in enumerate(self.revisions):
            self.revision_id = 100 + i
            # per-revision author：留空时回退到 self.author
            rev_author = revision.risk_level or self.author

            if revision.change_type == "delete":
                # 替换为删除标记
                old = self._escape_xml(revision.old_text)
                new_content = f'''<w:del w:id="{self.revision_id}" w:author="{rev_author}" w:date="{self.date}"><w:r><w:delText xml:space="preserve">{old}</w:delText></w:r></w:del>'''
                result = result.replace(old, new_content, 1)

            elif revision.change_type == "insert":
                # 替换为插入标记
                new = self._escape_xml(revision.new_text)
                new_content = f'''<w:ins w:id="{self.revision_id}" w:author="{rev_author}" w:date="{self.date}"><w:r><w:t xml:space="preserve">{new}</w:t></w:r></w:ins>'''
                result = result.replace(revision.old_text, new_content, 1) if revision.old_text else result.replace('<w:t>', f'<w:t>{new_content}', 1)

            elif revision.change_type == "modify":
                # 先删除旧文本，再插入新文本
                old = self._escape_xml(revision.old_text)
                new = self._escape_xml(revision.new_text)

                # 创建修订标记
                del_id = self.revision_id
                ins_id = self.revision_id + 1

                del_content = f'''<w:del w:id="{del_id}" w:author="{rev_author}" w:date="{self.date}"><w:r><w:delText xml:space="preserve">{old}</w:delText></w:r></w:del>'''
                ins_content = f'''<w:ins w:id="{ins_id}" w:author="{rev_author}" w:date="{self.date}"><w:r><w:t xml:space="preserve">{new}</w:t></w:r></w:ins>'''

                result = result.replace(old, del_content + ins_content, 1)
        
        # 处理批注
        if self.comment_records:
            # 为批注添加标记
            for i, comment in enumerate(self.comment_records):
                comment_id = i + 1
                comment_text = self._escape_xml(comment.get('text', '')[:50])  # 取前50字符作为定位
                
                # 查找并添加批注范围
                # 注意：这里需要精确定位，实际使用时需要更好的定位逻辑
                search_text = self._escape_xml(comment.get('text', ''))
                if search_text and search_text in result:
                    # 找到文本位置，添加批注标记
                    # 这是一个简化版本，实际使用需要更精确的定位
                    pass
        
        return result
    
    def create_inline_review(self, revisions: List[Dict], comments: List[Dict] = None) -> bool:
        """
        创建带修订和批注的文档

        Args:
            revisions: 修订列表，每项包含 old_text, new_text, reason, change_type, risk_level(可选)
            comments: 批注列表，每项可含 risk_level(可选)

        Returns:
            bool: 是否成功
        """
        # 添加修订
        for rev in revisions:
            self.add_revision(RevisionItem(
                old_text=rev.get('old_text', ''),
                new_text=rev.get('new_text', ''),
                reason=rev.get('reason', ''),
                change_type=rev.get('change_type', 'modify'),
                clause_title=rev.get('clause_title', ''),
                risk_level=rev.get('risk_level')  # per-item author_name
            ))

            # 添加对应的批注
            if rev.get('reason') or rev.get('legal_basis') or rev.get('suggestion'):
                self.add_comment(CommentItem(
                    text=f"建议修改：{rev.get('new_text', '(删除)')}",
                    reason=rev.get('reason', ''),
                    legal_basis=rev.get('legal_basis', ''),
                    suggestion=rev.get('suggestion', ''),
                    risk_level=rev.get('risk_level')
                ))

        # 添加独立批注
        if comments:
            for comm in comments:
                self.add_comment(CommentItem(
                    text=comm.get('text', ''),
                    reason=comm.get('reason', ''),
                    legal_basis=comm.get('legal_basis', ''),
                    suggestion=comm.get('suggestion', ''),
                    risk_level=comm.get('risk_level')
                ))

        return self.process_document()


def review_and_markup(docx_path: str, output_path: str = None,
                      reviews: List[Dict] = None, author: str = "AI审核助手") -> Tuple[bool, str]:
    """
    审核并标记文档

    Args:
        docx_path: 原文档路径
        output_path: 输出路径
        reviews: 审核修订列表
        author: 修订作者

    Returns:
        (成功标志, 输出路径/错误信息)
    """
    reviewer = InlineReviewer(docx_path, output_path, author)

    if reviews:
        for review in reviews:
            reviewer.add_revision_with_comment(
                old_text=review.get('old_text', ''),
                new_text=review.get('new_text', ''),
                reason=review.get('reason', ''),
                clause_title=review.get('clause_title', ''),
                legal_basis=review.get('legal_basis', ''),
                suggestion=review.get('suggestion', ''),
                change_type=review.get('change_type', 'modify'),
                risk_level=review.get('risk_level')
            )

    success = reviewer.process_document()

    if success:
        return (True, reviewer.output_path)
    else:
        return (False, "处理失败")


if __name__ == '__main__':
    # 测试代码
    print("原文件修订工具 - 直接在原文件上添加修订和批注")
