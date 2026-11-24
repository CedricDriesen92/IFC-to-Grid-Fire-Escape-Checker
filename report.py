"""PDF report of the escape routes (English, Dutch or French), with a plan of each floor and its routes."""
import math
import os
from io import BytesIO
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, NextPageTemplate, PageBreak, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

import i18n
from grid_codec import EMPTY

MARGIN = 50
# the colours of the 2D view (static/js/app/state.js): cells by code, routes by status, spaces tinted by status
CELL_COLORS = np.array([(255, 255, 255), (229, 209, 229), (14, 14, 14), (155, 107, 95), (225, 193, 105), (146, 160, 160)],
                       dtype=np.uint8)
ROUTE_COLORS = {'ok': '#16a34a', 'day': '#dc2626', 'night': '#f59e0b', 'none': '#6b7280', 'second': '#38bdf8'}
SPACE_TINTS = {'ok': (34, 197, 94, 0.10), 'day': (239, 68, 68, 0.16), 'night': (245, 158, 11, 0.16),
               'none': (107, 114, 128, 0.10)}
# what survives when a large grid is shrunk for the plan: walls over doors over stairs over floor over empty
CELL_RANK = np.array([0, 1, 5, 4, 3, 2], dtype=np.uint8)
RANK_CELL = np.argsort(CELL_RANK).astype(np.uint8)
MAX_PLAN_CELLS = 2500   # longest side of the plan image in cells; larger grids are shrunk
PLAN_PIXELS = 4000      # the image is enlarged by whole pixels up to about this, so walls stay sharp when zoomed in


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


def route_status(route: Optional[Dict[str, Any]]) -> str:
    """ok, day (a problem), night (a problem at night only) or none (no route), as the 2D view colours it."""
    if not route:
        return 'none'
    v = route['violations']
    if route.get('distance') is None or v.get('general') or v.get('daytime'):
        return 'day'
    return 'night' if v.get('nighttime') else 'ok'


class FloorPlan(Flowable):
    """One floor drawn as in the 2D view: the grid, the spaces tinted by their status with name and distance, each
    route from its furthest point to its exit, the routes to a second exit dashed, and the exits. The drawing is
    cropped to what is on the floor and scaled to fit (call fit first)."""

    def __init__(self, codes: np.ndarray, floor: int, routes: List[Dict[str, Any]], spaces: List[Dict[str, Any]],
                 exits: List[List[int]], grid_size: float, bbox: Dict[str, float], font: str):
        super().__init__()
        self.codes, self.floor, self.font = codes, floor, font
        self.routes = [r for r in routes if r.get('floor', r.get('starting_elevation')) == floor]
        self.spaces = [s for s in spaces if s.get('floor') == floor and s.get('polygon') and len(s['polygon']) >= 3]
        self.exits = [e for e in exits if e[2] == floor]
        self.grid_size, self.bbox = grid_size, bbox
        self.route_of = {r.get('space_id'): r for r in self.routes}
        rows, cols = codes.shape
        used = codes != EMPTY
        if used.any():
            r_any, c_any = np.flatnonzero(used.any(axis=1)), np.flatnonzero(used.any(axis=0))
            r0, r1, c0, c1 = r_any[0], r_any[-1] + 1, c_any[0], c_any[-1] + 1
        else:
            r0, r1, c0, c1 = 0, rows, 0, cols
        pad = max(3, int(0.02 * max(r1 - r0, c1 - c0)))
        self.r0, self.r1 = max(0, r0 - pad), min(rows, r1 + pad)
        self.c0, self.c1 = max(0, c0 - pad), min(cols, c1 + pad)
        self.landscape = (self.c1 - self.c0) > (self.r1 - self.r0)
        self.scale = 1.0
        self.width, self.height = float(self.c1 - self.c0), float(self.r1 - self.r0)

    def fit(self, width: float, height: float) -> 'FloorPlan':
        self.scale = min(width / (self.c1 - self.c0), height / (self.r1 - self.r0))
        self.width, self.height = (self.c1 - self.c0) * self.scale, (self.r1 - self.r0) * self.scale
        return self

    def wrap(self, avail_width, avail_height):
        return self.width, self.height

    def point(self, row: float, col: float):
        """PDF coordinates of the centre of a cell; rows run down the page, as in the 2D view."""
        return (col + 0.5 - self.c0) * self.scale, self.height - (row + 0.5 - self.r0) * self.scale

    def polygon_cells(self, polygon):
        """IFC plan coordinates to (row, col): x runs along the columns, y along the rows (as polygonToCells)."""
        gs, b = self.grid_size, self.bbox
        return [((py - b['min_y']) / gs, (px - b['min_x']) / gs) for px, py in polygon]

    def image(self):
        """The cropped grid as an image, shrunk by keeping the strongest cell of each block when it is large."""
        crop = self.codes[self.r0:self.r1, self.c0:self.c1]
        k = max(1, math.ceil(max(crop.shape) / MAX_PLAN_CELLS))
        if k > 1:
            h, w = math.ceil(crop.shape[0] / k), math.ceil(crop.shape[1] / k)
            ranks = np.zeros((h * k, w * k), dtype=np.uint8)
            ranks[:crop.shape[0], :crop.shape[1]] = CELL_RANK[crop]
            crop = RANK_CELL[ranks.reshape(h, k, w, k).max(axis=(1, 3))]
        rgb = CELL_COLORS[np.clip(crop, 0, len(CELL_COLORS) - 1)]
        u = max(1, PLAN_PIXELS // max(rgb.shape[:2]))
        img = Image.fromarray(rgb)
        if u > 1:
            img = img.resize((rgb.shape[1] * u, rgb.shape[0] * u), Image.NEAREST)
        return img, k

    def draw(self):
        canv, s = self.canv, self.scale
        canv.saveState()
        clip = canv.beginPath()
        clip.rect(0, 0, self.width, self.height)
        canv.clipPath(clip, stroke=0, fill=0)

        img, k = self.image()   # covers whole blocks of k cells, so it may reach a little past the crop
        h_cells = math.ceil((self.r1 - self.r0) / k) * k
        w_cells = math.ceil((self.c1 - self.c0) / k) * k
        canv.drawImage(ImageReader(img), 0, self.height - h_cells * s, w_cells * s, h_cells * s)

        # spaces, tinted by their status
        canv.setLineWidth(0.3)
        canv.setStrokeColor(colors.Color(80 / 255, 80 / 255, 80 / 255, alpha=0.6))
        for space in self.spaces:
            r, g, b, a = SPACE_TINTS[route_status(self.route_of.get(space.get('id')))]
            canv.setFillColor(colors.Color(r / 255, g / 255, b / 255, alpha=a))
            path = canv.beginPath()
            for i, (row, col) in enumerate(self.polygon_cells(space['polygon'])):
                x, y = self.point(row, col)
                path.lineTo(x, y) if i else path.moveTo(x, y)
            path.close()
            canv.drawPath(path, stroke=1, fill=1)

        # routes, then the routes to a second exit dashed
        canv.setLineJoin(1)
        for route in self.routes:
            if route.get('optimal_path'):
                self.polyline(route['optimal_path'], ROUTE_COLORS[route_status(route)], 0.8)
        for route in self.routes:
            if route.get('second_path'):
                self.polyline(route['second_path'], ROUTE_COLORS['second'], 0.6, dash=(2, 1.5))
        for route in self.routes:
            point = route.get('furthest_point')
            if route.get('optimal_path') and point and point[2] == self.floor:
                self.dot(point[0], point[1], 0.9, colors.HexColor('#a21caf'))
        for row, col, _ in self.exits:
            self.dot(row, col, 2.6, colors.HexColor('#ef4444'), colors.white)

        self.labels()
        canv.restoreState()

    def polyline(self, path, color, width, dash=None):
        canv = self.canv
        canv.setStrokeColor(colors.HexColor(color))
        canv.setLineWidth(width)
        canv.setDash(*dash) if dash else canv.setDash()
        canv.setLineCap(0 if dash else 1)
        p, drawing = canv.beginPath(), False
        for row, col, f in path:
            if f != self.floor:
                drawing = False
                continue
            x, y = self.point(row, col)
            p.lineTo(x, y) if drawing else p.moveTo(x, y)
            drawing = True
        canv.drawPath(p, stroke=1, fill=0)
        canv.setDash()

    def dot(self, row, col, radius, fill, ring=None):
        x, y = self.point(row, col)
        self.canv.setFillColor(fill)
        if ring is not None:
            self.canv.setStrokeColor(ring)
            self.canv.setLineWidth(0.8)
        self.canv.circle(x, y, radius, stroke=1 if ring is not None else 0, fill=1)

    def labels(self):
        """Name and distance of each space at its centre, small enough to fit its width."""
        canv = self.canv
        for space in self.spaces:
            cells = self.polygon_cells(space['polygon'])
            rows, cols = [c[0] for c in cells], [c[1] for c in cells]
            route = self.route_of.get(space.get('id'))
            text = str(space.get('name') or '')
            if route and route.get('distance') is not None:
                text += f" · {route['distance']:.1f} m"
            if not text:
                continue
            room = (max(cols) - min(cols)) * self.scale
            size = min(5.0, 1.9 * room / max(len(text), 1))
            if size < 1.8:
                continue
            x, y = self.point(sum(rows) / len(rows), sum(cols) / len(cols))
            canv.setFont(self.font, size)
            canv.setFillColor(colors.HexColor('#111111'))
            canv.drawCentredString(x, y - size * 0.35, text)


def plan_legend(tr, width: float, font: str) -> Drawing:
    """What the colours and marks on the plans mean."""
    items = [('line', ROUTE_COLORS['ok'], tr('legend_ok')), ('line', ROUTE_COLORS['day'], tr('legend_problem')),
             ('line', ROUTE_COLORS['night'], tr('legend_night')), ('dash', ROUTE_COLORS['second'], tr('legend_second')),
             ('exit', '#ef4444', tr('legend_exit')), ('dot', '#a21caf', tr('legend_furthest'))]
    placed, x, line = [], 0.0, 0   # wrapped onto more lines when the labels do not fit the width
    for item in items:
        step = 17 + pdfmetrics.stringWidth(item[2], font, 7) + 14
        if x and x + step - 14 > width:
            x, line = 0.0, line + 1
        placed.append((x, line, item))
        x += step
    height = 12 * (line + 1)
    d = Drawing(width, height)
    for x, line, (kind, color, label) in placed:
        y = height - 12 * line - 7
        c = colors.HexColor(color)
        if kind in ('line', 'dash'):
            d.add(Line(x, y, x + 14, y, strokeColor=c, strokeWidth=1.5, strokeDashArray=[3, 2] if kind == 'dash' else None))
        elif kind == 'exit':
            d.add(Circle(x + 7, y, 3, fillColor=c, strokeColor=colors.white, strokeWidth=0.8))
        else:
            d.add(Circle(x + 7, y, 1.5, fillColor=c, strokeColor=None))
        d.add(String(x + 17, y - 2.5, label, fontName=font, fontSize=7))
    return d


def build_pdf(routes: List[Dict[str, Any]], floors: List[Dict[str, Any]], filename: str, lang: str = 'en',
              compartments: Optional[List[Dict[str, Any]]] = None, occupancy: Optional[float] = None,
              needed: int = 1, plans: Optional[Dict[str, Any]] = None) -> bytes:
    """routes: results with 'violations' (and optionally 'use', 'compartment'); compartments: as returned by a
    project analysis (name, occupancy, needed). Without compartments one occupancy and number of exits is shown.
    plans: {'codes': a grid per floor, 'grid_size', 'bbox', 'spaces', 'exits'} adds a plan of each floor with its
    routes (on a landscape page when the floor is wider than it is deep)."""
    tr = lambda key, **kw: i18n.t(lang, key, **kw)  # noqa: E731
    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                          bottomMargin=MARGIN, title=tr('title'))
    frames = {}
    for name, size in (('portrait', A4), ('landscape', landscape(A4))):
        frames[name] = Frame(MARGIN, MARGIN, size[0] - 2 * MARGIN, size[1] - 2 * MARGIN, id=name)
    doc.addPageTemplates([PageTemplate(id=name, frames=[frames[name]], pagesize=size)
                          for name, size in (('portrait', A4), ('landscape', landscape(A4)))])
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
    codes = (plans or {}).get('codes') or []
    for floor_index, floor in enumerate(floors):
        title = f"{tr('floor')} {floor_index + 1}/{len(floors)}: {escape(str(floor.get('name')))}"
        if floor_index < len(codes) and (codes[floor_index] != EMPTY).any():
            plan = FloorPlan(codes[floor_index], floor_index, routes, plans.get('spaces') or [], plans.get('exits') or [],
                             plans['grid_size'], plans['bbox'], font)
            orientation = 'landscape' if plan.landscape else 'portrait'
            frame = frames[orientation]
            elements += [NextPageTemplate(orientation), PageBreak(), Paragraph(title, styles['Heading3']),
                         plan.fit(frame._width - 12, frame._height - 85), Spacer(1, 6),
                         plan_legend(tr, frame._width - 12, font), NextPageTemplate('portrait'), PageBreak()]
        elements.append(Paragraph(title, styles['Heading3']))
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
