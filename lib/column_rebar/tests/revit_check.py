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
            if abs(max(wd, ht) - d) < 1.0 and min(wd, ht) > 0.8 * d:
                bars.append(P(_centre(c)))       # ComputeCentroid fails on a flat solid
            continue
        if isinstance(c, Arc):
            r = c.Radius * FT
            cen = P(c.Center)
            if abs(r - d / 2.0) < 0.6:
                bars.append(cen)
            elif abs(r - o_) < 0.6 and not c.IsBound:
                rings.append(cen)
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
    # rings
    off = [p for p in rings if not _near(p, uniq, TOL)]
    if off:
        problems.append('rings off bars %d: %s' % (len(off), _fmt(off[:4])))
    straight = len([t for t in result['ties'] if t.get('kind') != 'v'])
    vt = len([t for t in result['ties'] if t.get('kind') == 'v'])
    if len(rings) != 2 * straight + 3 * vt:
        problems.append('rings %d, expected %d (%d ties, %d V)' % (len(rings), 2 * straight + 3 * vt, straight, vt))
    # lines
    xs_bar = sorted(set(round(p[0], 1) for p in uniq))
    ys_bar = sorted(set(round(p[1], 1) for p in uniq))
    for a, c in lines:
        on_bars = _near(a, uniq, TOL) and _near(c, uniq, TOL)
        if on_bars:
            continue
        vert, hor = abs(a[0] - c[0]) < 0.5, abs(a[1] - c[1]) < 0.5
        face = (vert and (abs(a[0]) < 0.6 or abs(a[0] - b) < 0.6)) or (hor and (abs(a[1]) < 0.6 or abs(a[1] - h) < 0.6))
        if face:
            continue
        ok = (vert and any(abs(a[0] - (x + s * o_)) < TOL for x in xs_bar for s in (-1, 1))) or \
             (hor and any(abs(a[1] - (y + s * o_)) < TOL for y in ys_bar for s in (-1, 1)))
        if not ok:
            problems.append('stray line %s-%s' % (_fmt([a]), _fmt([c])))
            if len(problems) > 12:
                break
    for (cen, r) in other_arcs:
        ok = abs(r - (b / 2.0 - 0.5)) < 1.0 or abs(r - (b / 2.0 - cr + o_)) < 1.0
        if not ok:
            problems.append('arc r=%.1f at %s' % (r, _fmt([cen])))
    # inside
    pts = [p for ln in lines for p in ln] + uniq + rings
    out_ = [p for p in pts if p[0] < -1 or p[0] > b + 1 or p[1] < -1 or p[1] > h + 1]
    if out_:
        problems.append('outside the concrete %d: %s' % (len(out_), _fmt(out_[:3])))
    return problems, {'bars': len(uniq), 'rings': len(rings), 'lines': len(lines)}


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


def run(app, folder, out_folder, only=None):
    """Returns the report text; images go to out_folder."""
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
                s = pd.GetElement(list(ref.Value.GetFamilySymbolIds())[0])
                s.Activate()
                syms[shape] = s
        r = tx_run(pd, 'load', load)
        lines.append('load: %s %s' % (r[1], r[2]))
        vft = [v for v in FilteredElementCollector(pd).OfClass(ViewFamilyType) if v.ViewFamily == ViewFamily.Drafting][0]
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
                text_type = pd.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType)
                for i, c in enumerate(chunk):
                    name, shape, b, h, cover, d, nb, nh, ov = c
                    x, y = (i % COLS) * CELL, -(i // COLS) * CELL      # a grid: readable pictures
                    TextNote.Create(pd, v.Id, XYZ(x / FT, (y - 150) / FT, 0), name, text_type)
                    res = code466.design(shape, b, h, cover, d, nb, nh, **ov)
                    if not res['stirrup']:
                        placed.append((c, None, None, res, 'no section (%s)' % ', '.join(m['code'] for m in res['messages'])))
                        continue
                    try:
                        vals = slots.params(res, b, h, cover, d, nb, nh, shape)
                    except ValueError as ex:
                        placed.append((c, None, None, res, 'slots: %s' % ex))
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
            for c, inst, origin, res, note in placed:
                red = [m['code'] for m in res['messages'] if m['level'] == code466.RED]
                head = '%-24s %-6s' % (c[0], c[1])
                if note:
                    lines.append('%s SKIP %s' % (head, note))
                    continue
                probs, info = check(c, inst, v, origin, res)
                total_bad += 1 if probs else 0
                lines.append('%s %s bars=%d rings=%d lines=%d%s' % (
                    head, 'OK ' if not probs else 'BAD', info['bars'], info['rings'], info['lines'],
                    (' red=' + ','.join(red)) if red else ''))
                for p in probs:
                    lines.append('      - ' + p)
        lines.append('sections with problems: %d' % total_bad)
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
    finally:
        pd.Close(False)
    return '\n'.join(lines)
