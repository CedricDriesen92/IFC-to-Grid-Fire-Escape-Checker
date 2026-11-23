"""PDF report of the escape routes (English, Dutch or French)."""
import os
from io import BytesIO
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

import i18n


def report_fonts():
    """A TrueType font with the letters IFC room names use (ų, é, ...), regular and bold; Helvetica, which only
    covers Latin-1, when none is found."""
    windows = os.environ.get('WINDIR', 'C:/Windows')
    candidates = [
        (os.path.join(windows, 'Fonts', 'arial.ttf'), os.path.join(windows, 'Fonts', 'arialbd.ttf')),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    ]
    for regular, bold in candidates:
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                if 'ReportSans' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('ReportSans', regular))
                    pdfmetrics.registerFont(TTFont('ReportSans-Bold', bold))
                return 'ReportSans', 'ReportSans-Bold'
            except Exception:
                continue
    return 'Helvetica', 'Helvetica-Bold'


def build_pdf(routes: List[Dict[str, Any]], floors: List[Dict[str, Any]], filename: str, lang: str = 'en',
              compartments: Optional[List[Dict[str, Any]]] = None, occupancy: Optional[float] = None,
              needed: int = 1) -> bytes:
    """routes: results with 'violations' (and optionally 'use', 'compartment'); compartments: as returned by a
    project analysis (name, occupancy, needed). Without compartments one occupancy and number of exits is shown."""
    tr = lambda key, **kw: i18n.t(lang, key, **kw)  # noqa: E731
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=50,
                            title=tr('title'))
    styles = getSampleStyleSheet()
    font, bold_font = report_fonts()
    for style in styles.byName.values():
        if hasattr(style, 'fontName'):
            style.fontName = bold_font if 'Bold' in style.fontName else font
    cell = ParagraphStyle('cell', parent=styles['BodyText'], fontName=font, fontSize=8, leading=10)
    head = ParagraphStyle('head', parent=cell, fontName=bold_font, textColor=colors.whitesmoke)
    elements = []

    elements.append(Paragraph(tr('title'), styles['Title']))
    elements.append(Paragraph(f"{tr('file')}: {escape(filename)}", styles['Heading2']))
    elements.append(Paragraph(tr('scope'), styles['BodyText']))
    elements.append(Spacer(1, 8))

    second_column = needed >= 2 or any((c.get('needed') or 1) >= 2 for c in compartments or [])
    if compartments:
        elements.append(Paragraph(tr('compartments'), styles['Heading2']))
        rows = [[tr('compartments'), tr('occupancy'), tr('exits_required')]]
        for c in compartments:
            occ = f"{c['occupancy']:.0f} {tr('persons')}" if c.get('occupancy') is not None else tr('not_given')
            rows.append([c['name'], occ, str(c.get('needed', 1))])
        elements.append(_table(rows, [250, 120, doc.width - 370], cell, head))
    else:
        occ = f"{occupancy:.0f} {tr('persons')}" if occupancy is not None else tr('not_given')
        elements.append(Paragraph(f"{tr('occupancy').capitalize()}: {occ}; {tr('exits_required')}: {needed}.", styles['BodyText']))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph(tr('violations'), styles['Heading2']))
    flagged = [r for r in routes if any(r['violations'].values())]
    if not flagged:
        elements.append(Paragraph(tr('none_found'), styles['BodyText']))
    for route in flagged:
        elements.append(Paragraph(escape(route['space_name']), styles['Heading3']))
        for kind, items in route['violations'].items():
            if items:
                elements.append(Paragraph(f"{tr(kind)}:", styles['Heading4']))
                for item in items:
                    elements.append(Paragraph(f"- {escape(item)}", styles['BodyText']))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph(tr('overview'), styles['Heading2']))
    for floor_index, floor in enumerate(floors):
        elements.append(Paragraph(f"{tr('floor')} {floor_index + 1}/{len(floors)}: {escape(str(floor.get('name')))}", styles['Heading3']))
        floor_routes = [r for r in routes if int(r['starting_elevation']) == floor_index]
        if not floor_routes:
            elements.append(Paragraph(tr('no_routes_floor'), styles['BodyText']))
            continue
        header = [tr('col_space'), tr('col_use'), tr('col_exit_m'), tr('col_exit')] + ([tr('col_second')] if second_column else []) + [tr('col_issues')]
        rows = [header]
        for r in floor_routes:
            use = r.get('use')
            row = [r['space_name'], tr(use) if use in ('day', 'night') else tr('unknown'),
                   f"{r['distance']:.1f}" if r.get('distance') is not None else "-",
                   tr(r['exit_kind']) if r.get('exit_kind') else "-"]
            if second_column:
                s = r.get('second_exit_distance')
                row.append(f"{s:.1f}" if s is not None else (f"> {r['second_exit_beyond']:.0f}" if r.get('second_exit_beyond') else "-"))
            row.append("; ".join(v for items in r['violations'].values() for v in items) or "-")
            rows.append(row)
        widths = [120, 45, 50, 65] + ([50] if second_column else [])
        widths.append(doc.width - sum(widths))
        table = _table(rows, widths, cell, head)
        for i, r in enumerate(floor_routes, start=1):
            v = r['violations']
            if v['general'] or v['daytime']:
                table.setStyle(TableStyle([('BACKGROUND', (0, i), (-1, i), colors.pink)]))
            elif v['nighttime']:
                table.setStyle(TableStyle([('BACKGROUND', (0, i), (-1, i), colors.yellow)]))
        elements.append(table)
        elements.append(Spacer(1, 10))

    elements.append(Paragraph(tr('not_checked'), styles['Heading2']))
    for item in i18n.not_checked(lang):
        elements.append(Paragraph(f"- {escape(item)}", styles['BodyText']))

    doc.build(elements)
    return buffer.getvalue()


def _table(rows, widths, cell, head) -> Table:
    data = [[Paragraph(escape(str(v)), head if r == 0 else cell) for v in row] for r, row in enumerate(rows)]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    return table
