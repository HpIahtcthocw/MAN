# -*- coding: utf-8 -*-
"""Submission MD -> DOCX converter (offline, python-docx only).

Renders headings, paragraphs, bullet/numbered lists, pipe tables, bold spans
and fenced code. Mermaid architecture blocks are replaced by a built-in layer
diagram so the converted document carries a real 系统架构图 instead of code.
Usage: python tools/md_to_docx.py <input.md> <output.docx> [--title 定制标题]
"""
import re
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

PRIMARY = RGBColor(0x1C, 0x3D, 0x34)


def set_font(run, size=11, bold=False, color=None):
    run.font.name = 'Microsoft YaHei'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color


def add_runs(par, text, size=11, base_bold=False):
    for part in re.split(r'(\*\*[^*]+\*\*)', text):
        if not part:
            continue
        if part.startswith('**') and part.endswith('**'):
            run = par.add_run(part[2:-2])
            set_font(run, size, True, PRIMARY)
        else:
            run = par.add_run(part)
            set_font(run, size, base_bold)


def add_layer_diagram(doc):
    """Built-in architecture layer diagram (replaces the mermaid block)."""
    doc.add_paragraph()
    title = doc.add_paragraph()
    add_runs(title, '系统架构（分层）', 12, True)
    layers = [
        ('渠道层', '手机银行 App 内嵌 H5/小程序 · React 响应式界面（手机/桌面）· 会话隔离与 CSRF'),
        ('智能体编排层', '意图解析 → 受限类型规划（最多5节点白名单）→ 任务状态机；模型只提案，无批准/执行/验证码权限'),
        ('银行能力层', 'BankAdapter 同构接口：流水/转账/预约/代扣协议/回执；整数分账本、幂等键、UNKNOWN 回查、执行租约'),
        ('风控与审计层', '红黄绿权限分级 · 反诈话术门禁 · 哈希链审计 · 异常熔断 · 操作员 CLI 人工接管'),
    ]
    for index, (name, detail) in enumerate(layers):
        table = doc.add_table(rows=1, cols=2)
        table.style = 'Table Grid'
        cells = table.rows[0].cells
        run = cells[0].paragraphs[0].add_run(name)
        set_font(run, 11, True, RGBColor(0xFF, 0xFF, 0xFF))
        cells[0].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        run2 = cells[1].paragraphs[0].add_run(detail)
        set_font(run2, 10)
        if index < len(layers) - 1:
            arrow = doc.add_paragraph()
            arrow.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run3 = arrow.add_run('↓')
            set_font(run3, 10)
    doc.add_paragraph()


def convert(source, target, doc_title=None):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Microsoft YaHei'
    style.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    style.font.size = Pt(11)

    lines = open(source, encoding='utf-8').read().split('\n')
    index, in_code, code_buffer, in_table = 0, False, [], []
    first_heading_done = False
    while index < len(lines):
        line = lines[index]
        if line.startswith('```'):
            if in_code:
                if any(key in code_buffer[0] for key in ('flowchart', 'stateDiagram', 'graph')):
                    add_layer_diagram(doc)
                else:
                    for code_line in code_buffer:
                        par = doc.add_paragraph()
                        run = par.add_run(code_line)
                        set_font(run, 9)
                        run.font.name = 'Consolas'
                code_buffer, in_code = [], False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_buffer.append(line)
            index += 1
            continue
        if line.startswith('|') and index + 1 < len(lines) and re.match(r'^\|[\s\-|:]+\|$', lines[index + 1]):
            rows = []
            while index < len(lines) and lines[index].startswith('|'):
                cells = [c.strip() for c in lines[index].strip('|').split('|')]
                if not re.match(r'^\|[\s\-|:]+\|$', lines[index]):
                    rows.append(cells)
                index += 1
            if rows:
                table = doc.add_table(rows=len(rows), cols=len(rows[0]))
                table.style = 'Table Grid'
                for r, row in enumerate(rows):
                    for c, cell in enumerate(row[:len(table.columns)]):
                        add_runs(table.rows[r].cells[c].paragraphs[0], cell.replace('**', ''), 10, r == 0)
            continue
        match = re.match(r'^(#{1,4})\s+(.*)$', line)
        if match:
            level, text = len(match.group(1)), match.group(2)
            if level == 1 and not first_heading_done:
                head = doc.add_paragraph()
                head.alignment = WD_ALIGN_PARAGRAPH.CENTER
                add_runs(head, doc_title or text, 20, True)
                first_heading_done = True
            else:
                head = doc.add_heading('', level=min(level, 3))
                add_runs(head, text, 15 - level, True)
            index += 1
            continue
        if re.match(r'^\s*[-*]\s+', line):
            par = doc.add_paragraph(style='List Bullet')
            add_runs(par, re.sub(r'^\s*[-*]\s+', '', line))
            index += 1
            continue
        if re.match(r'^\s*\d+\.\s+', line):
            par = doc.add_paragraph(style='List Number')
            add_runs(par, re.sub(r'^\s*\d+\.\s+', '', line))
            index += 1
            continue
        if line.startswith('>'):
            par = doc.add_paragraph()
            par.paragraph_format.left_indent = Pt(18)
            add_runs(par, line.lstrip('> '), 10)
            index += 1
            continue
        if line.strip():
            par = doc.add_paragraph()
            add_runs(par, line)
        index += 1
    doc.save(target)
    print('converted ->', target)


if __name__ == '__main__':
    source, target = sys.argv[1], sys.argv[2]
    title = sys.argv[sys.argv.index('--title') + 1] if '--title' in sys.argv else None
    convert(source, target, title)
