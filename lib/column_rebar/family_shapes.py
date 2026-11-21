# -*- coding: utf-8 -*-
"""2D bar shapes for the schedules, built from a copy of PEER_Rebar_Shape 60
(Revit, IronPython 2.7). User 2026-11-21:

    PEER_Rebar_Shape 64   half-round U-bar (open), the end of a rounded column
    PEER_Rebar_Shape 65   stirrup with half circles on both ends (stadium)
    PEER_Rebar_Shape 75   round stirrup (ring)

Shape 60 is a closed U (half circle at the bottom, flat top with the hook
marks). Its labels, parameters (shared Rebar_*, Rebar_Stirrup Spacing Dense)
and look stay; only the geometry changes:
    64  the top line, the hook marks and the width label out; Rebar_B = overall (leg + A / 2)
    65  legs end at a new plane A / 2 under the top, a half circle on top;
        Rebar_B = overall, the leg label shows the straight part B - A
    75  legs, arcs and the leg / arc labels out, a full circle of diameter A;
        Rebar_B = A
Rebar_A = width (out to out as the button writes it), as Shape 60.

    from column_rebar import family_shapes
    family_shapes.build_all(app, src_shape60, folder) -> {name: (result, status, errors)}
"""

import math
import os

from Autodesk.Revit.DB import (Arc, CurveElement, DetailLine, Dimension, ElementId, FamilyInstance,
                               FilteredElementCollector, Line, ReferencePlane, SaveAsOptions,
                               ViewPlan, XYZ)
from System.Collections.Generic import List

from column_rebar.family_build import FT, run

NAMES = {64: u'PEER_Rebar_Shape 64', 65: u'PEER_Rebar_Shape 65', 75: u'PEER_Rebar_Shape 75'}
LENGTH = {
    64: 'roundup((Length_Round + 2 * Length_H) / 50 mm) * 50 mm',
    65: 'roundup((2 * Length_Round + 2 * Length_H + 20 * Rebar_Diameter) / 50 mm) * 50 mm',
    75: 'roundup((pi() * Rebar_A + 20 * Rebar_Diameter) / 50 mm) * 50 mm',
}


class _Doc(object):

    def __init__(self, fd):
        self.fd, self.fm, self.fc = fd, fd.FamilyManager, fd.FamilyCreate
        self.view = [v for v in FilteredElementCollector(fd).OfClass(ViewPlan) if not v.IsTemplate][0]

    def planes(self):
        """Shape 60 planes by their place in the nominal state (A 200, B 400):
        x 200 / 300 / 400 = left / centre / right, y 200 / 0 / -200 = top / centre / bottom."""
        out = {}
        for p in FilteredElementCollector(self.fd).OfClass(ReferencePlane):
            a, b = p.BubbleEnd, p.FreeEnd
            if abs(a.X - b.X) < 1e-6:
                k = {200: 'left', 300: 'cx', 400: 'right'}.get(int(round(a.X * FT)))
            elif abs(a.Y - b.Y) < 1e-6:
                k = {200: 'top', 0: 'cy', -200: 'bottom'}.get(int(round(a.Y * FT)))
            else:
                k = None
            if k:
                out[k] = p
        return out

    def nested(self, family, linked=None):
        """Nested instances of a family; linked: only those with a parameter
        associated to this family parameter."""
        out = []
        for i in FilteredElementCollector(self.fd).OfClass(FamilyInstance):
            if i.Symbol.FamilyName != family:
                continue
            if linked is None:
                out.append(i)
                continue
            for pp in i.Parameters:
                a = self.fm.GetAssociatedFamilyParameter(pp)
                if a is not None and a.Definition.Name == linked:
                    out.append(i)
                    break
        return out

    def rebar_curves(self):
        return [c for c in FilteredElementCollector(self.fd).OfClass(CurveElement)
                if c.LineStyle is not None and c.LineStyle.Name == u'Rebar  Lines']

    def delete(self, els):
        ids = List[ElementId]([e.Id for e in els])
        if ids.Count:
            self.fd.Delete(ids)

    def formula(self, name, f):
        self.fm.SetFormula(self.fm.get_Parameter(name), f)

    def style(self, el, like):
        el.LineStyle = like.LineStyle

    def common(self, shape):
        """Every new shape: its number, length, no sketch image of Shape 60."""
        fm = self.fm
        self.formula('Rebar_Shape', '%d' % shape)
        self.formula('Rebar_Length', LENGTH[shape])
        p = fm.get_Parameter('Rebar_Sketch')
        if p is not None:
            try:
                fm.Set(p, ElementId.InvalidElementId)
            except Exception:
                pass


def _legs(d):
    """The two vertical rebar lines of Shape 60 (left, right)."""
    legs = []
    for c in d.rebar_curves():
        g = c.GeometryCurve
        if isinstance(g, Line) and abs(g.Direction.X) < 1e-6 and g.Length * FT > 50:
            legs.append(c)
    return sorted(legs, key=lambda c: c.GeometryCurve.GetEndPoint(0).X)


def _u(d, P):
    """64: open U - no top line, no hook marks, no width label (user
    2026-11-21: the arc length and the leg)."""
    d.delete(d.nested(u'TN_Re_Shape_01'))
    d.delete(d.nested(u'Rebar_Dim Label', 'Rebar_A'))
    d.common(64)


def _stadium(d, P):
    """65: half circles on both ends."""
    fd, fc, view = d.fd, d.fc, d.view
    d.delete(d.nested(u'TN_Re_Shape_01'))
    fd.Regenerate()
    legs = _legs(d)
    like = legs[0]
    # the legs' top ends were locked to the top plane: those dimensions out
    top_id = P['top'].Id
    leg_ids = set(l.Id for l in legs)
    dims = []
    for dm in FilteredElementCollector(fd).OfClass(Dimension):
        ids = set(r.ElementId for r in dm.References)
        if top_id in ids and ids & leg_ids:
            dims.append(dm)
    d.delete(dims)
    fd.Regenerate()
    # plane at the top arc centre: A / 2 under the top
    half = d.fm.get_Parameter('Half_A') or d.fm.AddParameter(
        'Half_A', d.fm.get_Parameter('Length_H').Definition.GetGroupTypeId(),
        d.fm.get_Parameter('Length_H').Definition.GetDataType(), True)
    d.fm.SetFormula(half, 'Rebar_A / 2')
    y_top = P['top'].BubbleEnd.Y
    x_l, x_r = P['left'].BubbleEnd.X, P['right'].BubbleEnd.X
    r = (x_r - x_l) / 2.0
    yc = y_top - r
    tc = fc.NewReferencePlane(XYZ(-1, yc, 0), XYZ(1, yc, 0), XYZ(0, 0, 1), view)
    tc.Name = u'Top Arc Centre'
    fd.Regenerate()
    from Autodesk.Revit.DB import ReferenceArray
    ra = ReferenceArray()
    ra.Append(P['top'].GetReference())
    ra.Append(tc.GetReference())
    dm = fc.NewDimension(view, Line.CreateBound(XYZ(x_r + 0.5, 0, 0), XYZ(x_r + 0.5, 1, 0)), ra)
    dm.FamilyLabel = half
    # legs up to that plane, their top ends aligned to it
    # (the end order kept: the bottom end is joined to the arc by its index)
    for c in legs:
        g = c.GeometryCurve
        p0, p1 = g.GetEndPoint(0), g.GetEndPoint(1)
        i = 0 if p0.Y > p1.Y else 1
        pts = [p0, p1]
        pts[i] = XYZ(pts[i].X, yc, 0)
        c.GeometryCurve = Line.CreateBound(pts[0], pts[1])
        fd.Regenerate()
        fc.NewAlignment(view, tc.GetReference(), c.GeometryCurve.GetEndPointReference(i))
    # the top half circle, centre on the centre plane and the new plane
    xc = P['cx'].BubbleEnd.X
    rr = d.fm.get_Parameter('Rebar_Radius')
    arc = fc.NewDetailCurve(view, Arc.Create(XYZ(xc, yc, 0), r - 0.5 / FT, 0.0, math.pi,
                                             XYZ.BasisX, XYZ.BasisY))
    d.style(arc, like)
    fd.Regenerate()
    fc.NewAlignment(view, P['cx'].GetReference(), arc.CenterPointReference)
    fc.NewAlignment(view, tc.GetReference(), arc.CenterPointReference)
    rd = fc.NewRadialDimension(view, arc.GeometryCurve.Reference, XYZ(xc + r / 3.0, yc + r / 3.0, 0))
    rd.FamilyLabel = rr
    d.formula('Length_H', 'Rebar_B - Rebar_A')
    d.common(65)


def _ring(d, P):
    """75: a full circle of diameter A."""
    fd, fc, view = d.fd, d.fc, d.view
    d.delete(d.nested(u'TN_Re_Shape_01'))
    d.delete(d.nested(u'Rebar_Dim Label_Round'))
    d.delete(d.nested(u'Rebar_Dim Label', 'Length_H'))
    curves = d.rebar_curves()
    like_style = curves[0].LineStyle
    d.delete(curves)
    fd.Regenerate()
    d.formula('Rebar_B', 'Rebar_A')
    xc, yc = P['cx'].BubbleEnd.X, P['cy'].BubbleEnd.Y
    r = (P['right'].BubbleEnd.X - P['left'].BubbleEnd.X) / 2.0
    ring = fc.NewDetailCurve(view, Arc.Create(XYZ(xc, yc, 0), r, 0.0, 2 * math.pi, XYZ.BasisX, XYZ.BasisY))
    ring.LineStyle = like_style
    fd.Regenerate()
    fc.NewAlignment(view, P['cx'].GetReference(), ring.CenterPointReference)
    fc.NewAlignment(view, P['cy'].GetReference(), ring.CenterPointReference)
    dd = fc.NewDiameterDimension(view, ring.GeometryCurve.Reference, XYZ(xc + r, yc + r, 0))
    # a diameter dimension takes a Length parameter, not the shared reinforcement length
    rd = d.fm.get_Parameter('Ring_D') or d.fm.AddParameter(
        'Ring_D', d.fm.get_Parameter('Length_H').Definition.GetGroupTypeId(),
        d.fm.get_Parameter('Length_H').Definition.GetDataType(), True)
    d.fm.SetFormula(rd, 'Rebar_A')
    dd.FamilyLabel = rd
    d.common(75)


MAKERS = {64: _u, 65: _stadium, 75: _ring}


def build(app, src, folder, shape):
    """src: Shape 60 (with Rebar_Stirrup Spacing Dense). Saves folder/<NAMES[shape]>.rfa."""
    from peer_library import revit_family as rf
    fd = rf.open_quiet(app, src)
    try:
        d = _Doc(fd)

        def go():
            P = d.planes()
            missing = [k for k in ('left', 'cx', 'right', 'top', 'cy', 'bottom') if k not in P]
            if missing:
                raise ValueError('Shape 60 planes not found: %s' % missing)
            MAKERS[shape](d, P)
            fd.Regenerate()
            return shape

        res = run(fd, NAMES[shape], go)
        if res[1] == 'Committed':
            o = SaveAsOptions()
            o.OverwriteExistingFile = True
            fd.SaveAs(os.path.join(folder, NAMES[shape] + u'.rfa'), o)
        return res
    finally:
        fd.Close(False)


def build_all(app, src, folder):
    return dict((NAMES[s], build(app, src, folder, s)) for s in (64, 65, 75))

