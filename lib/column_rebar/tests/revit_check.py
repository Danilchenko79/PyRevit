# -*- coding: utf-8 -*-
"""Big check of the section families in Revit (run through the connector or a
dev button; IronPython 2.7). Nothing in the open projects is touched: a blank
project is made in the background, every case of cases.py is placed on a
drafting view with the parameters from code466 + slots, checked against the
expected geometry, and the views are exported to PNG. The project is closed
without saving.

    from column_rebar.tests import revit_check
    report = revit_check.run(app, families_folder, out_folder)

Checks per section (mm, from the bottom-left corner of the concrete):
  bars    the family's bars = slots.family_bar_points (count and places),
          and code466's bars are within 3 mm of them
  rings   every hook ring sits on a bar; count = 2 x straight ties + 3 x V-ties
  ties    every tie / V leg ends on bars
  lines   every other line is a face of the concrete or lies O = (D + Dw) / 2
          from a bar line (stirrup and inner hoops)
  inside  nothing outside the concrete
  revit   no Revit errors when setting the parameters
"""

import clr
import math
import os

from System.Collections.Generic import List
from Autodesk.Revit.DB import (Arc, BuiltInCategory, ElementId, ElementTypeGroup, ExportRange, Family,
                               FilteredElementCollector, GeometryInstance, ImageExportOptions,
                               ImageFileType, ImageResolution, Line, Options, Solid, StorageType,
                               TextNote, UnitSystem, ViewDrafting, ViewFamily, ViewFamilyType, XYZ,
                               ZoomFitType)

from column_rebar import code466, slots
from column_rebar.family_build import FT, run as tx_run
from column_rebar.family_section import NAMES
from column_rebar.tests import cases as case_list

NL = chr(10)
PER_VIEW = 12
COLS, CELL = 4, 2400.0      # grid of the check views, mm
GAP = 600.0
TOL = 1.0


def _curves(geo, out):
    for g in geo:
        if isinstance(g, GeometryInstance):
            _curves(g.GetInstanceGeometry(), out)
        elif isinstance(g, (Line, Arc)):
            out.append(g)
        elif isinstance(g, Solid) and g.Edges.Size:
            out.append(g)            # filled regions: the bars (discs) and the concrete


def _centre(solid):
    """Mean of the distinct edge end points (a regular polygon: its centre)."""
    pts = []
    for e in solid.Edges:
        p = e.AsCurve().GetEndPoint(0)
        if not any(p.IsAlmostEqualTo(q) for q in pts):
            pts.append(p)
    n = float(len(pts))
    return XYZ(sum(p.X for p in pts) / n, sum(p.Y for p in pts) / n, 0)


def _extent(solid):
    """(xmin, ymin, xmax, ymax) in feet from the edges of a flat solid."""
    xs, ys = [], []
    for e in solid.Edges:
        for p in e.AsCurve().Tessellate():
            xs.append(p.X)
            ys.append(p.Y)
    return min(xs), min(ys), max(xs), max(ys)


def _near(p, pts, tol):
    return any(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for q in pts)


def check(case, inst, view, origin, result):
    name, shape, b, h, cover, d, nb, nh, ov = case
    dw = result['stirrup']['dia']
    cr = cover + dw + d / 2.0
    o_ = (d + dw) / 2.0
    ox, oy = origin
    opts = Options()
    opts.View = view
    cv = []
    _curves(inst.get_Geometry(opts), cv)
    P = lambda p: (p.X * FT - ox, p.Y * FT - oy)
    bars, rings, other_arcs, lines = [], [], [], []
    for c in cv:
        if isinstance(c, Solid):
            x0, y0, x1, y1 = _extent(c)
            wd, ht = (x1 - x0) * FT, (y1 - y0) * FT
            # the disc comes as a polygon (D20: 20 x 17.3) - its larger size is the diameter
            # (a disc of the radial array on a round end is turned: 23.6 for D25)
            if 0.9 * d < max(wd, ht) < d + 1.0 and min(wd, ht) > 0.8 * d:
                bars.append(P(_centre(c)))       # ComputeCentroid fails on a flat solid
            continue
        if isinstance(c, Arc):
            r = c.Radius * FT
            cen = P(c.Center)
            if abs(r - d / 2.0) < 0.6:
                bars.append(cen)
            elif abs(r - o_) < 0.6:
                rings.append(cen)                # hook: half circle round a bar
            else:
                other_arcs.append((cen, r))
        else:
            lines.append((P(c.GetEndPoint(0)), P(c.GetEndPoint(1))))
    problems = []
    # bars
    want = slots.family_bar_points(shape, b, h, cr, nb, nh)
    uniq = []
    for p in bars:
        if not _near(p, uniq, 0.5):
            uniq.append(p)
    miss = [p for p in want if not _near(p, uniq, TOL)]
    extra = [p for p in uniq if not _near(p, want, TOL)]
    if miss:
        problems.append('bars missing %d: %s' % (len(miss), _fmt(miss[:4])))
    if extra:
        problems.append('bars extra %d: %s' % (len(extra), _fmt(extra[:4])))
    far = [p for p in result['bars'] if not _near(p, want, 3.0)]
    if far:
        problems.append('code466 bars off the family by > 3 mm: %d, e.g. %s' % (len(far), _fmt(far[:3])))
    # hooks: half circles of radius R = (D + Dw) / 2 round the bars (user's Rebar_Shape 61)
    off = [p for p in rings if not _near(p, uniq, TOL)]
    if off:
        problems.append('hooks not on bars %d: %s' % (len(off), _fmt(off[:4])))
    straight = len([t for t in result['ties'] if t.get('kind') != 'v'])
    vt = len([t for t in result['ties'] if t.get('kind') == 'v'])
    if len(rings) != 2 * straight + 3 * vt:          # V: apex arc + two hooks
        problems.append('hooks %d, expected %d (%d ties, %d V)' % (len(rings), 2 * straight + 3 * vt, straight, vt))
    tails = rings
    lines_all = lines
    # no line may run through a bar centre (user: 'lines through the bar centres look bad')
    for a_, c_ in lines:
        for q in uniq:
            if _dist_seg(q, a_, c_) < o_ - 1.0:
                problems.append('line through a bar at %s' % _fmt([q]))
                break
    # lines
    xs_bar = sorted(set(round(p[0], 1) for p in uniq))
    ys_bar = sorted(set(round(p[1], 1) for p in uniq))
    for a, c in lines:
        touch = any(abs(math.hypot(e[0] - q[0], e[1] - q[1]) - o_) < 0.8 for e in (a, c) for q in uniq)
        if touch and not (abs(a[0] - c[0]) < 0.5 or abs(a[1] - c[1]) < 0.5):
            continue                     # an inclined V leg or its return, ending on a hook circle
        vert, hor = abs(a[0] - c[0]) < 0.5, abs(a[1] - c[1]) < 0.5
        face = (vert and (abs(a[0]) < 0.6 or abs(a[0] - b) < 0.6)) or (hor and (abs(a[1]) < 0.6 or abs(a[1] - h) < 0.6))
        if face:
            continue
        # stirrup / hoop axis o_ off the bar axis; a half-round U-bar (contour split) a stirrup
        # diameter further out
        ok = (vert and any(abs(a[0] - (x + s * oo)) < TOL for x in xs_bar for s in (-1, 1)
                           for oo in (o_, o_ + dw))) or \
             (hor and any(abs(a[1] - (y + s * o_)) < TOL for y in ys_bar for s in (-1, 1)))
        if not ok:
            problems.append('stray line %s-%s' % (_fmt([a]), _fmt([c])))
            if len(problems) > 12:
                break
    for (cen, r) in other_arcs:
        ok = abs(r - (b / 2.0 - 0.5)) < 1.0 or abs(r - (b / 2.0 - cr + o_)) < 1.0 or \
            abs(r - (b / 2.0 - cr + o_ + dw)) < 1.0
        if not ok:
            problems.append('arc r=%.1f at %s' % (r, _fmt([cen])))
    # inside
    pts = [p for ln in lines_all for p in ln] + uniq
    out_ = [p for p in pts if p[0] < -1 or p[0] > b + 1 or p[1] < -1 or p[1] > h + 1]
    if out_:
        problems.append('outside the concrete %d: %s' % (len(out_), _fmt(out_[:3])))
    return problems, {'bars': len(uniq), 'rings': len(tails), 'lines': len(lines)}


def _dist_seg(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def _fmt(pts):
    return ' '.join('(%.1f,%.1f)' % (p[0], p[1]) for p in pts)


def _set(inst, vals):
    for k, v in vals.items():
        p = inst.LookupParameter(k)
        if p is None:
            raise Exception('no parameter ' + k)
        if p.StorageType == StorageType.Integer:
            p.Set(int(v))
        elif k.startswith('Rebar_Quantity'):
            p.Set(float(v))
        else:
            p.Set(v / FT)


def _label(c, res, probs, note):
    """Text under a section: name, what code466 decided, its messages, the check."""
    name = c[0]
    msgs = ['%s %s' % ('RED' if m['level'] == code466.RED else 'yel', m['code']) for m in res['messages']]
    if note:
        verdict = 'NOT DRAWN: ' + note
    elif probs:
        verdict = 'CHECK: ' + '; '.join(probs[:2])
    else:
        verdict = 'check OK'
    txt = [name, code466.summary(res) or '-']
    if msgs:
        txt.append(', '.join(msgs))
    txt.append(verdict)
    return NL.join(txt)


def run(app, folder, out_folder, only=None, pdf_name=None, images=False):
    """Returns the report text. pdf_name: one PDF of A3 sheets (a view of 12
    sections each, labelled) in out_folder; images: PNG of the views too."""
    if not os.path.isdir(out_folder):
        os.makedirs(out_folder)
    pd = app.NewProjectDocument(UnitSystem.Metric)
    lines = []
    try:
        syms = {}

        def load():
            for shape, nm in NAMES.items():
                ref = clr.Reference[Family]()
                pd.LoadFamily(os.path.join(folder, nm + u'.rfa'), ref)
                s_ = pd.GetElement(list(ref.Value.GetFamilySymbolIds())[0])
                s_.Activate()
                syms[shape] = s_
        r = tx_run(pd, 'load', load)
        lines.append('load: %s %s' % (r[1], r[2]))
        vft = [v for v in FilteredElementCollector(pd).OfClass(ViewFamilyType) if v.ViewFamily == ViewFamily.Drafting][0]
        text_type = pd.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType)
        cs = [c for c in case_list.cases() if not only or c[0] in only]
        views = []
        total_bad = 0
        for start in range(0, len(cs), PER_VIEW):
            chunk = cs[start:start + PER_VIEW]
            placed = []

            def place():
                v = ViewDrafting.Create(pd, vft.Id)
                v.Name = 'CHECK %02d' % (start // PER_VIEW + 1)
                v.Scale = 25
                for i, c in enumerate(chunk):
                    name, shape, b, h, cover, d, nb, nh, ov = c
                    x, y = (i % COLS) * CELL, -(i // COLS) * CELL      # a grid: readable sheets
                    res = code466.design(shape, b, h, cover, d, nb, nh, **ov)
                    if not res['stirrup']:
                        placed.append((c, None, (x, y), res, 'no section'))
                        continue
                    try:
                        vals = slots.params(res, b, h, cover, d, nb, nh, shape)
                    except ValueError as ex:
                        placed.append((c, None, (x, y), res, 'slots: %s' % ex))
                        continue
                    inst = pd.Create.NewFamilyInstance(XYZ(x / FT, y / FT, 0), syms[shape], v)
                    _set(inst, vals)
                    placed.append((c, inst, (x, y), res, None))
                views.append(v)
                return v
            v, st, errs = tx_run(pd, 'place', place)
            if st != 'Committed':
                lines.append('VIEW %d: %s %s' % (start // PER_VIEW + 1, st, errs))
                continue
            labels = []
            for c, inst, origin, res, note in placed:
                red = [m['code'] for m in res['messages'] if m['level'] == code466.RED]
                head = '%-26s %-6s' % (c[0], c[1])
                probs = []
                if note:
                    lines.append('%s SKIP %s' % (head, note))
                else:
                    probs, info = check(c, inst, v, origin, res)
                    total_bad += 1 if probs else 0
                    lines.append('%s %s bars=%d hooks=%d lines=%d%s' % (
                        head, 'OK ' if not probs else 'BAD', info['bars'], info['rings'], info['lines'],
                        (' red=' + ','.join(red)) if red else ''))
                    for p_ in probs:
                        lines.append('      - ' + p_)
                labels.append((origin, _label(c, res, probs, note)))

            def write_labels():
                for (x, y), txt in labels:
                    TextNote.Create(pd, v.Id, XYZ(x / FT, (y - 120) / FT, 0), 80 / FT, txt, text_type)
            tx_run(pd, 'labels', write_labels)
        lines.append('sections with problems: %d' % total_bad)
        if images:
            for v in views:
                o = ImageExportOptions()
                o.ExportRange = ExportRange.SetOfViews
                o.SetViewsAndSheets(List[ElementId]([v.Id]))
                o.FilePath = os.path.join(out_folder, v.Name.replace(' ', '_'))
                o.ZoomType = ZoomFitType.FitToPage
                o.PixelSize = 9000
                o.HLRandWFViewsFileType = ImageFileType.PNG
                o.ImageResolution = ImageResolution.DPI_150
                pd.ExportImage(o)
        if pdf_name:
            lines.append('pdf: %s' % _pdf(pd, views, out_folder, pdf_name))
    finally:
        pd.Close(False)
    return NL.join(lines)


def _pdf(pd, views, out_folder, name):
    """One A3 sheet per view, all into one PDF."""
    from Autodesk.Revit.DB import (ExportPaperFormat, PageOrientationType, PDFExportOptions,
                                   Viewport, ViewSheet, ZoomType)
    sheets = []

    def make():
        for i, v in enumerate(views):
            sh = ViewSheet.Create(pd, ElementId.InvalidElementId)
            sh.SheetNumber = 'C%02d' % (i + 1)
            sh.Name = 'Column sections check %d' % (i + 1)
            Viewport.Create(pd, sh.Id, v.Id, XYZ(0, 0, 0))
            sheets.append(sh.Id)
    r = tx_run(pd, 'sheets', make)
    if r[1] != 'Committed':
        return 'sheets: %s %s' % (r[1], r[2])
    o = PDFExportOptions()
    o.FileName = name
    o.Combine = True
    o.PaperFormat = ExportPaperFormat.ISO_A3
    o.PaperOrientation = PageOrientationType.Landscape
    o.ZoomType = ZoomType.FitToPage
    ok = pd.Export(out_folder, List[ElementId](sheets), o)
    return '%s %s' % (ok, os.path.join(out_folder, name + '.pdf'))
