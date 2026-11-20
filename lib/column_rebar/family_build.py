# -*- coding: utf-8 -*-
"""Builds the nested detail families of the Create Column section (Revit,
IronPython 2.7). Item 12 of docs/COLUMNS.md: the section stays a family, the
transverse reinforcement is drawn by nested families placed in 'slots' whose
position, size and visibility the script sets from code466.

    PEER_Col_Tie    (family_ties) straight tie beside the bars, hooks as Rebar_Shape 61,
                    see family_ties.py
    PEER_Col_Hoop   inner closed hoop, origin bottom-left, A along X, B along Y
    PEER_Col_VTie   V-shaped tie, apex at origin, ends at (-W/2, H) and (W/2, H),
                    rings of diameter D round the three bars
    PEER_Column Section   the RECT section (copy of 'Create Column', new name so
                    the old button's drawings stay as they are): cover to the
                    stirrup, perimeter stirrup = a PEER_Col_Hoop, Klamrot 2d
                    removed, slots (see SLOTS) for ties, inner hoops and V-ties

Every curve end is aligned to two reference planes and the planes are driven
by labelled dimensions, so the geometry follows the parameters. Built from
'Metric Detail Item.rft'. Each build checks itself by flexing (rolled back).
"""

import math
import os

from Autodesk.Revit.DB import (Arc, CurveElement, FailureProcessingResult,
                               FailureSeverity, GroupTypeId, IFailuresPreprocessor,
                               Line, Options, ReferenceArray, ReferencePlane,
                               SaveAsOptions, SpecTypeId, Transaction, ViewPlan,
                               FilteredElementCollector, XYZ)

FT = 304.8
TEMPLATE = r'C:\ProgramData\Autodesk\RVT {0}\Family Templates\English\Metric Detail Item.rft'
LINE_STYLE = u'Rebar  Lines'          # as in PEER_Rebar_Shape families; None = default


class _Guard(IFailuresPreprocessor):
    def __init__(self):
        self.errors = []

    def PreprocessFailures(self, fa):
        err = False
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == FailureSeverity.Warning:
                fa.DeleteWarning(f)
            else:
                err = True
                self.errors.append(f.GetDescriptionText())
        return FailureProcessingResult.ProceedWithRollBack if err else FailureProcessingResult.Continue


def run(doc, name, fn, commit=True):
    """fn() inside a guarded transaction that is ALWAYS closed.
    Returns (result, status, errors)."""
    g = _Guard()
    t = Transaction(doc, name)
    o = t.GetFailureHandlingOptions()
    o.SetFailuresPreprocessor(g)
    o.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(o)
    t.Start()
    try:
        r = fn()
        if commit:
            t.Commit()
            return r, str(t.GetStatus()), g.errors
        return r, 'rolled back', g.errors
    except Exception as ex:
        return None, 'error: {0}'.format(ex), g.errors
    finally:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()


class Builder(object):
    """Small helpers over a new detail item family document."""

    def __init__(self, app):
        self.fd = app.NewFamilyDocument(TEMPLATE.format(app.VersionNumber))
        self.fc = self.fd.FamilyCreate
        self.fm = self.fd.FamilyManager
        self.view = [v for v in FilteredElementCollector(self.fd).OfClass(ViewPlan) if not v.IsTemplate][0]
        planes = dict((p.Name, p) for p in FilteredElementCollector(self.fd).OfClass(ReferencePlane))
        self.cx = planes['Center (Left/Right)']      # x = 0
        self.cy = planes['Center (Front/Back)']      # y = 0

    def ensure_type(self, name):
        """A new family has no type, and parameters cannot be set without one."""
        if self.fm.CurrentType is None:
            self.fm.NewType(name)

    def param(self, name, spec=None, instance=True):
        p = self.fm.get_Parameter(name)
        if p is None:
            p = self.fm.AddParameter(name, GroupTypeId.Geometry, spec or SpecTypeId.Length, instance)
        return p

    def plane(self, name, vertical, at_mm):
        """Reference plane x = at (vertical) or y = at."""
        a = at_mm / FT
        if vertical:
            p = self.fc.NewReferencePlane(XYZ(a, -1, 0), XYZ(a, 1, 0), XYZ(0, 0, 1), self.view)
        else:
            p = self.fc.NewReferencePlane(XYZ(-1, a, 0), XYZ(1, a, 0), XYZ(0, 0, 1), self.view)
        p.Name = name
        self.fd.Regenerate()
        return p

    def dim(self, refs, vertical_planes, at_mm=-150.0, label=None, equal=False):
        """Dimension between planes (vertical_planes: they are x = const)."""
        ra = ReferenceArray()
        for r in refs:
            ra.Append(r)
        o = at_mm / FT
        line = (Line.CreateBound(XYZ(-1, o, 0), XYZ(1, o, 0)) if vertical_planes
                else Line.CreateBound(XYZ(o, -1, 0), XYZ(o, 1, 0)))
        d = self.fc.NewDimension(self.view, line, ra)
        if equal:
            d.AreSegmentsEqual = True
        if label is not None:
            d.FamilyLabel = label
        return d

    def line(self, p0, p1, planes0, planes1):
        """Detail line p0 -> p1 (mm); each end aligned to its planes."""
        el = self.fc.NewDetailCurve(self.view, Line.CreateBound(XYZ(p0[0] / FT, p0[1] / FT, 0),
                                                               XYZ(p1[0] / FT, p1[1] / FT, 0)))
        self._style(el)
        self.fd.Regenerate()
        c = el.GeometryCurve
        for i, pls in ((0, planes0), (1, planes1)):
            for p in pls:
                self.fc.NewAlignment(self.view, p.GetReference(), c.GetEndPointReference(i))
        return el

    def ring(self, centre, r_mm, px, py, radius_param):
        """Full circle at centre (mm), centre locked to planes px (x) and py (y),
        diameter driven by 2 * radius_param through a formula parameter."""
        cx, cy = centre[0] / FT, centre[1] / FT
        arc = Arc.Create(XYZ(cx, cy, 0), r_mm / FT, 0.0, 2 * math.pi, XYZ.BasisX, XYZ.BasisY)
        el = self.fc.NewDetailCurve(self.view, arc)
        self._style(el)
        self.fd.Regenerate()
        cref = el.GeometryCurve.Reference
        for p in (px, py):          # a dimension to the centre is refused; an alignment works
            self.fc.NewAlignment(self.view, p.GetReference(), el.CenterPointReference)
        dd = self.fc.NewDiameterDimension(self.view, cref, XYZ(cx + r_mm / FT, cy + r_mm / FT, 0))
        dd.FamilyLabel = radius_param
        return el

    def arc(self, centre, r_mm, a0, a1, px, py, radius_param):
        """Arc a0..a1 (rad) at centre (mm); centre aligned to px / py,
        radius driven by radius_param (radial dimension)."""
        cx, cy = centre[0] / FT, centre[1] / FT
        arc = Arc.Create(XYZ(cx, cy, 0), r_mm / FT, a0, a1, XYZ.BasisX, XYZ.BasisY)
        el = self.fc.NewDetailCurve(self.view, arc)
        self._style(el)
        self.fd.Regenerate()
        for p in (px, py):
            self.fc.NewAlignment(self.view, p.GetReference(), el.CenterPointReference)
        mid = (a0 + a1) / 2.0
        pt = XYZ(cx + 0.5 * r_mm / FT * math.cos(mid), cy + 0.5 * r_mm / FT * math.sin(mid), 0)
        d = self.fc.NewRadialDimension(self.view, el.GeometryCurve.Reference, pt)
        d.FamilyLabel = radius_param
        return el

    def dashed_style(self, name=u'Tie Alternate'):
        """Graphics style of a dashed subcategory of the family's category."""
        from Autodesk.Revit.DB import (GraphicsStyleType, LinePattern, LinePatternElement,
                                       LinePatternSegment, LinePatternSegmentType)
        from System.Collections.Generic import List
        cats = self.fd.Settings.Categories
        parent = self.fd.OwnerFamily.FamilyCategory
        sub = None
        for c in parent.SubCategories:
            if c.Name == name:
                sub = c
        if sub is None:
            sub = cats.NewSubcategory(parent, name)
        pat = LinePatternElement.GetLinePatternElementByName(self.fd, u'Dash')
        if pat is None:
            lp = LinePattern(u'Dash')
            segs = List[LinePatternSegment]()
            segs.Add(LinePatternSegment(LinePatternSegmentType.Dash, 3.0 / FT))
            segs.Add(LinePatternSegment(LinePatternSegmentType.Space, 1.5 / FT))
            lp.SetSegments(segs)
            pat = LinePatternElement.Create(self.fd, lp)
        sub.SetLinePatternId(pat.Id, GraphicsStyleType.Projection)
        return sub.GetGraphicsStyle(GraphicsStyleType.Projection)

    def visible_by(self, el, param):
        from Autodesk.Revit.DB import BuiltInParameter
        self.fm.AssociateElementParameterToFamilyParameter(
            el.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM), param)

    def _style(self, el):
        if not LINE_STYLE:
            return
        for gs in el.GetLineStyleIds():
            s = self.fd.GetElement(gs)
            if s is not None and s.Name == LINE_STYLE:
                el.LineStyle = s
                return

    def save(self, path):
        o = SaveAsOptions()
        o.OverwriteExistingFile = True
        self.fd.SaveAs(path, o)

    def close(self):
        self.fd.Close(False)


def build_tie(app, folder):
    """Moved to family_ties (ties drawn as the user's Rebar_Shape 61)."""
    from column_rebar import family_ties
    return family_ties.build_tie(app, folder)


def build_hoop(app, folder):
    """PEER_Col_Hoop: origin on the bottom-left bar it holds; A, B - between
    the axes of the bars at its corners; O - from a bar axis to the hoop axis
    (bar / 2 + hoop / 2), the hoop runs outside the bars."""
    b = Builder(app)
    try:
        def go():
            b.ensure_type('Hoop')
            A, B, O = b.param('A'), b.param('B'), b.param('O')
            o, a, bb = 14.0, 300.0, 500.0
            xl = b.plane('Left', True, -o)
            xa = b.plane('Bar right', True, a)
            xr = b.plane('Right', True, a + o)
            yb = b.plane('Bottom', False, -o)
            yb2 = b.plane('Bar top', False, bb)
            yt = b.plane('Top', False, bb + o)
            b.dim([xl.GetReference(), b.cx.GetReference()], True, -200, O)
            b.dim([b.cx.GetReference(), xa.GetReference()], True, -250, A)
            b.dim([xa.GetReference(), xr.GetReference()], True, -200, O)
            b.dim([yb.GetReference(), b.cy.GetReference()], False, -200, O)
            b.dim([b.cy.GetReference(), yb2.GetReference()], False, -250, B)
            b.dim([yb2.GetReference(), yt.GetReference()], False, -200, O)
            pts = [(-o, -o, xl, yb), (a + o, -o, xr, yb), (a + o, bb + o, xr, yt), (-o, bb + o, xl, yt)]
            for i in range(4):
                x0, y0, px0, py0 = pts[i]
                x1, y1, px1, py1 = pts[(i + 1) % 4]
                b.line((x0, y0), (x1, y1), [px0, py0], [px1, py1])
            b.fm.Set(A, a / FT)
            b.fm.Set(B, bb / FT)
            b.fm.Set(O, o / FT)
        res = run(b.fd, 'PEER_Col_Hoop', go)
        if res[1] == 'Committed':
            b.save(os.path.join(folder, 'PEER_Col_Hoop.rfa'))
        return res
    finally:
        b.close()


def build_vtie(app, folder):
    """Moved to family_ties."""
    from column_rebar import family_ties
    return family_ties.build_vtie(app, folder)


def build_round_hoop(app, folder, both_ends):
    """Perimeter stirrup of a rounded column, origin = centre of the bottom half
    circle. A - between the bar axes across, O - bar axis to hoop axis, L - from
    the bottom arc centre to the top arc centre (both_ends, PEER_Col_Hoop_R2) or
    to the axis of the flat top leg (PEER_Col_Hoop_R1). Rr = A / 2 + O."""
    b = Builder(app)
    name = 'PEER_Col_Hoop_R2' if both_ends else 'PEER_Col_Hoop_R1'
    try:
        def go():
            b.ensure_type('Hoop')
            A, L, O = b.param('A'), b.param('L'), b.param('O')
            Rr = b.param('Rr')
            W = b.param('Wo')
            a, ll, o = 400.0, 600.0, 14.0
            b.fm.Set(A, a / FT)
            b.fm.Set(O, o / FT)
            b.fm.Set(L, ll / FT)
            b.fm.SetFormula(Rr, 'A / 2 + O')
            b.fm.SetFormula(W, 'A + 2 * O')
            r = a / 2 + o
            xl = b.plane('Left', True, -r)
            xr = b.plane('Right', True, r)
            yt = b.plane('Top', False, ll)
            b.dim([xl.GetReference(), b.cx.GetReference(), xr.GetReference()], True, -r - 150, None, equal=True)
            b.dim([xl.GetReference(), xr.GetReference()], True, -r - 250, W)
            b.dim([b.cy.GetReference(), yt.GetReference()], False, r + 150, L)
            b.arc((0, 0), r, math.pi, 2 * math.pi, b.cx, b.cy, Rr)
            if both_ends:
                b.arc((0, ll), r, 0.0, math.pi, b.cx, yt, Rr)
            else:
                b.line((-r, ll), (r, ll), [xl, yt], [xr, yt])
            b.line((-r, 0), (-r, ll), [xl, b.cy], [xl, yt])
            b.line((r, 0), (r, ll), [xr, b.cy], [xr, yt])
        res = run(b.fd, name, go)
        if res[1] == 'Committed':
            b.save(os.path.join(folder, name + '.rfa'))
        return res
    finally:
        b.close()


def flex(app, path, values):
    """Opens a built family, sets each {param: mm} in a rolled-back
    transaction and returns the curves: [(values, [('line', p0, p1) |
    ('ring', centre, diameter)])] in mm."""
    from peer_library import revit_family as rf
    fd = rf.open_quiet(app, path)
    out = []
    try:
        fm = fd.FamilyManager
        for vals in values:
            def go():
                for k, v in vals.items():
                    fm.Set(fm.get_Parameter(k), v / FT)
                fd.Regenerate()
                cur = []
                for c in FilteredElementCollector(fd).OfClass(CurveElement):
                    g = c.GeometryCurve
                    if isinstance(g, Line):
                        cur.append(('line', _mm(g.GetEndPoint(0)), _mm(g.GetEndPoint(1))))
                    elif isinstance(g, Arc):
                        cur.append(('ring', _mm(g.Center), round(g.Radius * 2 * FT, 1)))
                out.append((vals, cur))
            run(fd, 'flex', go, commit=False)
    finally:
        fd.Close(False)
    return out


def _mm(p):
    return (round(p.X * FT, 1), round(p.Y * FT, 1))
