# -*- coding: utf-8 -*-
"""Section families built from copies of the Create Column families (Revit,
IronPython 2.7). docs/COLUMNS.md, item 12.

    RECT    Create Column                              -> PEER_Column Section
    ROUND2  Create Column-Rectangular Rounded          -> PEER_Column Section Round2
    ROUND1  Create Column-Rectangular Rounded One Side -> PEER_Column Section Round1

New names, so loading never replaces the old families and the drawings of the
old button stay as they are. Changes against Create Column:
- cover to the stirrup: CoverR (bar axis from the face) = Cover + Stirrup_Diameter + D / 2;
- the perimeter stirrup is a nested family (PEER_Col_Hoop / _R2 / _R1);
- Klamrot 2d and its parameters are removed;
- slots for the transverse reinforcement that the script fills from code466
  (host parameters <slot>_Vis / _X / _Y / _A / _W / _H, bar axes from the
  left / bottom face of the concrete):
    TieV1..12  straight tie along h at x = _X            (RECT)
    TieH1..12  straight tie along b at y = _Y            (all)
    HoopV1..4  inner hoop over the full h, left bar at x = _X, width _A   (RECT)
    HoopH1..4  inner hoop over the full b, bottom bar at y = _Y, height _A (all)
    VB, VT     V-tie, apex on the bottom / top face at x = _X (RECT; VT also ROUND1)
    VL, VR     V-tie, apex on the left / right face at y = _Y  (RECT)
"""

import math
import os

from Autodesk.Revit.DB import (BuiltInParameter, ElementTransformUtils, Family,
                               FamilyInstanceReferenceType, FilteredElementCollector,
                               GroupTypeId, Line, ReferenceArray, ReferencePlane,
                               SaveAsOptions, SpecTypeId, ViewPlan, XYZ)

from column_rebar.family_build import FT, run

N_TIES, N_HOOPS = 12, 4
RECT, ROUND1, ROUND2 = 'RECT', 'ROUND1', 'ROUND2'
NAMES = {RECT: u'PEER_Column Section', ROUND2: u'PEER_Column Section Round2',
         ROUND1: u'PEER_Column Section Round1'}
SOURCES = {RECT: u'Create Column.rfa', ROUND2: u'Create Column-Rectangular Rounded.rfa',
           ROUND1: u'Create Column-Rectangular Rounded One Side.rfa'}
SECTION_NAME = NAMES[RECT]
KLAMROT = u'Klamrot 2d'
OLD_PARAMS = (u'HasVerticalSpacer', u'HasHorizontalSpacer', u'DistanceFirst SpacerX',
              u'DistanceFirst SpacerY', u'Quantity Side X', u'Quantity Side Y')


from column_rebar.slots import slot_names  # noqa: E402,F401  (one list for the builder and the script)


def _load(fd, path):
    import clr
    ref = clr.Reference[Family]()
    fd.LoadFamily(path, ref)
    fam = ref.Value
    if fam is None:
        name = os.path.splitext(os.path.basename(path))[0]
        fam = [f for f in FilteredElementCollector(fd).OfClass(Family) if f.Name == name][0]
    sym = fd.GetElement(list(fam.GetFamilySymbolIds())[0])
    if not sym.IsActive:
        sym.Activate()
    return sym


class _Host(object):
    def __init__(self, fd):
        self.fd, self.fm, self.fc = fd, fd.FamilyManager, fd.FamilyCreate
        self.view = [v for v in FilteredElementCollector(fd).OfClass(ViewPlan) if not v.IsTemplate][0]
        self.planes = dict((p.Name, p) for p in FilteredElementCollector(fd).OfClass(ReferencePlane))
        self.made = 0

    def P(self, name, spec=None, formula=None, value=None):
        fm = self.fm
        p = fm.get_Parameter(name)
        if p is None:
            p = fm.AddParameter(name, GroupTypeId.Geometry, spec or SpecTypeId.Length, True)
        if formula:
            fm.SetFormula(p, formula)
        elif value is not None:
            fm.Set(p, value)
        return p

    def value(self, name):
        return self.fm.CurrentType.AsDouble(self.fm.get_Parameter(name)) * FT

    def plane(self, name, vertical, at_mm, ref_plane, label):
        fc, fd = self.fc, self.fd
        a = at_mm / FT
        if vertical:
            pl = fc.NewReferencePlane(XYZ(a, -1, 0), XYZ(a, 1, 0), XYZ(0, 0, 1), self.view)
        else:
            pl = fc.NewReferencePlane(XYZ(-1, a, 0), XYZ(1, a, 0), XYZ(0, 0, 1), self.view)
        pl.Name = name
        fd.Regenerate()                      # a dimension to a fresh plane needs it
        ra = ReferenceArray()
        ra.Append(ref_plane.GetReference())
        ra.Append(pl.GetReference())
        o = -0.6 - 0.05 * self.made
        ln = (Line.CreateBound(XYZ(-1, o, 0), XYZ(1, o, 0)) if vertical
              else Line.CreateBound(XYZ(o, -1, 0), XYZ(o, 1, 0)))
        d = fc.NewDimension(self.view, ln, ra)
        d.FamilyLabel = label
        self.made += 1
        return pl

    def place(self, sym, x_mm, y_mm, angle_deg, vplane, hplane):
        """Instance at (x, y), rotated; its centre planes aligned to vplane
        (host plane x = const) and hplane (y = const)."""
        fc, fd = self.fc, self.fd
        inst = fc.NewFamilyInstance(XYZ(x_mm / FT, y_mm / FT, 0), sym, self.view)
        if angle_deg:
            ax = Line.CreateBound(XYZ(x_mm / FT, y_mm / FT, 0), XYZ(x_mm / FT, y_mm / FT, 1))
            ElementTransformUtils.RotateElement(fd, inst.Id, ax, math.radians(angle_deg))
        fd.Regenerate()
        lr = list(inst.GetReferences(FamilyInstanceReferenceType.CenterLeftRight))[0]
        fbk = list(inst.GetReferences(FamilyInstanceReferenceType.CenterFrontBack))[0]
        turned = angle_deg % 180 != 0        # its own Left/Right plane is now horizontal
        fc.NewAlignment(self.view, (hplane if turned else vplane).GetReference(), lr)
        fc.NewAlignment(self.view, (vplane if turned else hplane).GetReference(), fbk)
        return inst

    def link(self, inst, child, host):
        self.fm.AssociateElementParameterToFamilyParameter(inst.LookupParameter(child), host)

    def visible(self, inst, host):
        self.fm.AssociateElementParameterToFamilyParameter(
            inst.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM), host)


def build(app, src, folder, shape=RECT):
    """src: a copy of the Create Column family of this shape; the nested
    PEER_Col_*.rfa in folder. Saves folder/<NAMES[shape]>.rfa.
    Returns (planes made, status, errors)."""
    from peer_library import revit_family as rf
    fd = rf.open_quiet(app, src)
    try:
        H = _Host(fd)
        fm = H.fm
        pl = H.planes
        left, right, bottom, top = pl['Left'], pl['Right'], pl['Bottom'], pl['Top']

        def go():
            # 1. Klamrot out, with its parameters
            for f in list(FilteredElementCollector(fd).OfClass(Family)):
                if f.Name == KLAMROT:
                    fd.Delete(f.Id)
            fd.Regenerate()
            for n in OLD_PARAMS:
                p = fm.get_Parameter(n)
                if p is not None:
                    fm.RemoveParameter(p)
            # 2. cover to the stirrup
            H.P('Stirrup_Diameter', value=8 / FT)
            fm.SetFormula(fm.get_Parameter('CoverR'), 'Cover + Stirrup_Diameter + Rebar_Diameter / 2')
            # 135 degree hook tail of a tie, as Shape 62: max(50 + 2 D, 7 D) of the tie
            hook = H.P('Hook_T', formula='if(7 * Stirrup_Diameter > 50 mm + 2 * Stirrup_Diameter, '
                                          '7 * Stirrup_Diameter, 50 mm + 2 * Stirrup_Diameter)')
            ho = H.P('Hoop_O', formula='Rebar_Diameter / 2 + Stirrup_Diameter / 2')
            bars_b = H.P('Bars_B', formula='PR_Dimension_Width - 2 * CoverR')
            bars_h = H.P('Bars_H', formula='PR_Dimension_Height - 2 * CoverR')
            if shape != RECT:
                half = H.P('Half_B', formula='PR_Dimension_Width / 2')
                arc_l = H.P('Arc_L', formula=('PR_Dimension_Height - PR_Dimension_Width' if shape == ROUND2 else
                                              'PR_Dimension_Height - PR_Dimension_Width / 2 - CoverR + Hoop_O'))
            fd.Regenerate()
            cr = fm.get_Parameter('CoverR')
            w, h, c = H.value('PR_Dimension_Width'), H.value('PR_Dimension_Height'), H.value('CoverR')
            # 3. bar lines
            bl = H.plane('Bar Left', True, c, left, cr)
            br = H.plane('Bar Right', True, w - c, right, cr)
            bb = H.plane('Bar Bottom', False, c, bottom, cr) if shape == RECT else None
            bt = H.plane('Bar Top', False, h - c, top, cr) if shape in (RECT, ROUND1) else None
            tie = _load(fd, os.path.join(folder, 'PEER_Col_Tie.rfa'))
            hoop = _load(fd, os.path.join(folder, 'PEER_Col_Hoop.rfa'))
            vtie = _load(fd, os.path.join(folder, 'PEER_Col_VTie.rfa'))
            # 4. perimeter stirrup
            if shape == RECT:
                st = H.place(hoop, c, c, 0, bl, bb)
                H.link(st, 'A', bars_b)
                H.link(st, 'B', bars_h)
            else:
                mid = H.plane('Middle', True, w / 2, left, half)
                arc0 = H.plane('Arc Bottom', False, w / 2, bottom, half)
                rh = _load(fd, os.path.join(folder, 'PEER_Col_Hoop_R2.rfa' if shape == ROUND2
                                            else 'PEER_Col_Hoop_R1.rfa'))
                st = H.place(rh, w / 2, w / 2, 0, mid, arc0)
                H.link(st, 'A', bars_b)
                H.link(st, 'L', arc_l)
                # contour split (user 2026-11-21): a rect hoop over the straight part +
                # half-round U-bar(s), a stirrup diameter outside the hoop (the lap reads
                # as two lines); the one-piece stirrup above only when not split
                yes = SpecTypeId.Boolean.YesNo
                split = H.P('Contour_Split', yes, value=1)
                one = H.P('Contour_One', yes, formula='not(Contour_Split)')
                H.visible(st, one)
                u_leg = H.P('U_Leg', value=320 / FT)
                u_o = H.P('U_O', formula='Hoop_O + Stirrup_Diameter')
                rect_b = H.P('Rect_B', formula=('PR_Dimension_Height - PR_Dimension_Width' if shape == ROUND2 else
                                                'PR_Dimension_Height - PR_Dimension_Width / 2 - CoverR'))
                rh2 = H.place(hoop, c, w / 2, 0, bl, arc0)
                H.link(rh2, 'A', bars_b)
                H.link(rh2, 'B', rect_b)
                H.link(rh2, 'O', ho)
                H.visible(rh2, split)
                uf = _load(fd, os.path.join(folder, 'PEER_Col_URound.rfa'))
                ends = [(w / 2, 0, arc0)]
                if shape == ROUND2:
                    arc1 = H.plane('Arc Top', False, h - w / 2, top, half)
                    ends.append((h - w / 2, 180, arc1))
                for y_, ang, pl_ in ends:
                    u = H.place(uf, w / 2, y_, ang, mid, pl_)
                    H.link(u, 'A', bars_b)
                    H.link(u, 'O', u_o)
                    H.link(u, 'Leg', u_leg)
                    H.visible(u, split)
            H.link(st, 'O', ho)
            # 5. slots
            yes = SpecTypeId.Boolean.YesNo
            H.P('Show_Fill', yes, value=1)
            H.P('Show_Transverse', yes, value=1)
            for name, kind, d in slot_names(shape):
                vis = H.P(name + '_Vis', yes, value=0)
                if kind == 'tie':
                    if d == 'V':
                        p_ = H.plane(name, True, w / 2, left, H.P(name + '_X', value=w / 2 / FT))
                        inst = H.place(tie, w / 2, c, 0, p_, bb)
                        H.link(inst, 'L', bars_h)
                    else:
                        p_ = H.plane(name, False, h / 2, bottom, H.P(name + '_Y', value=h / 2 / FT))
                        inst = H.place(tie, c, h / 2, -90, bl, p_)
                        H.link(inst, 'L', bars_b)
                    H.link(inst, 'C', hook)
                    H.link(inst, 'R', ho)
                    H.link(inst, 'Alt', H.P(name + '_Alt', yes, value=0))
                elif kind == 'hoopt':          # ROUND1: from the flat end down to a row of side bars
                    a = H.P(name + '_A', value=100 / FT)
                    bh = H.P(name + '_B', value=100 / FT)
                    x0, y0 = w / 2 - 50, h - c - 100
                    px_ = H.plane(name + ' X', True, x0, left, H.P(name + '_X', value=x0 / FT))
                    py_ = H.plane(name + ' Y', False, y0, bottom, H.P(name + '_Y', value=y0 / FT))
                    inst = H.place(hoop, x0, y0, 0, px_, py_)
                    H.link(inst, 'A', a)
                    H.link(inst, 'B', bh)
                    H.link(inst, 'O', ho)
                elif kind == 'hoop':
                    a = H.P(name + '_A', value=100 / FT)
                    if d == 'V':
                        x0 = w / 2 - 50
                        p_ = H.plane(name, True, x0, left, H.P(name + '_X', value=x0 / FT))
                        inst = H.place(hoop, x0, c, 0, p_, bb)
                        H.link(inst, 'A', a)
                        H.link(inst, 'B', bars_h)
                    else:
                        y0 = h / 2 - 50
                        p_ = H.plane(name, False, y0, bottom, H.P(name + '_Y', value=y0 / FT))
                        inst = H.place(hoop, c, y0, 0, bl, p_)
                        H.link(inst, 'A', bars_b)
                        H.link(inst, 'B', a)
                    H.link(inst, 'O', ho)
                else:
                    vw = H.P(name + '_W', value=200 / FT)
                    vh = H.P(name + '_H', value=100 / FT)
                    if d in ('B', 'T'):
                        p_ = H.plane(name, True, w / 2, left, H.P(name + '_X', value=w / 2 / FT))
                        if d == 'B':
                            inst = H.place(vtie, w / 2, c, 0, p_, bb)
                        else:
                            inst = H.place(vtie, w / 2, h - c, 180, p_, bt)
                    else:
                        p_ = H.plane(name, False, h / 2, bottom, H.P(name + '_Y', value=h / 2 / FT))
                        if d == 'L':
                            inst = H.place(vtie, c, h / 2, -90, bl, p_)
                        else:
                            inst = H.place(vtie, w - c, h / 2, 90, br, p_)
                    H.link(inst, 'W', vw)
                    H.link(inst, 'H', vh)
                    H.link(inst, 'Wide', H.P(name + '_Wide', yes, value=0))
                    H.link(inst, 'E', H.P(name + '_E', value=100 / FT))
                    H.link(inst, 'C', hook)
                    H.link(inst, 'R', ho)
                # shown when the slot is on AND the transverse reinforcement is shown
                H.visible(inst, H.P(name + '_On', yes, formula='and(%s_Vis, Show_Transverse)' % name))
            _graphics(H, fd, shape)
            _tidy(H)
            return H.made

        res = run(fd, NAMES[shape], go)
        if res[1] == 'Committed':
            o = SaveAsOptions()
            o.OverwriteExistingFile = True
            fd.SaveAs(os.path.join(folder, NAMES[shape] + u'.rfa'), o)
        return res
    finally:
        fd.Close(False)


# ---- 21.11.2026: graphics switches and parameter groups (user: 'turn the fill
# off, show the bars on a plan without the inner lines; group the parameters so
# that the family can be filled in by hand and used on its own')

GROUPS = (
    # (group, names in this order; a trailing * = every parameter starting so)
    ('geometry', ['PR_Dimension_Width', 'PR_Dimension_Height', 'Cover']),
    ('rebar', ['Rebar_Diameter', 'Rebar_QuantityX', 'Rebar_QuantityY', 'Stirrup_Diameter',
               'Contour_Split', 'U_Leg']),
    ('graphics', ['Show_Fill', 'Show_Transverse', 'Vis_Rebar']),
)
SLOT_PREFIXES = ('TieV', 'TieH', 'HoopV', 'HoopH', 'HoopT', 'VB', 'VT', 'VL', 'VR')
SLOT_INPUTS = ('_Vis', '_X', '_Y', '_A', '_B', '_W', '_H', '_E', '_Wide', '_Alt')
DESCRIPTIONS = {
    'PR_Dimension_Width': u'Section b (short side; diameter of the round end of a rounded column).',
    'PR_Dimension_Height': u'Section h.',
    'Cover': u'Concrete cover to the stirrup.',
    'Rebar_Diameter': u'Longitudinal bar diameter.',
    'Rebar_QuantityX': u'Rectangular: bars along b without the corners. Rounded: bars on each rounded end.',
    'Rebar_QuantityY': u'Rectangular: bars along h without the corners. Rounded: bars on each long side.',
    'Stirrup_Diameter': u'Stirrup and tie diameter.',
    'Contour_Split': u'Rounded: yes - a rectangular hoop over the straight part + half-round U-bars; '
                     u'no - one stirrup along the outline.',
    'U_Leg': u'Rounded, split: straight leg of the half-round U-bar from the arc centre (lap, 40 D).',
    'Show_Fill': u'Concrete fill.',
    'Show_Transverse': u'Inner hoops and ties (the stirrup along the outline stays).',
    'Vis_Rebar': u'Longitudinal bars.',
}


def _graphics(H, fd, shape):
    """The concrete fill on / off by Show_Fill. Its edges were the outline of
    the concrete, so the outline is drawn again on its own, always shown:
    detail lines (and arcs of the rounded ends) on the face planes."""
    from Autodesk.Revit.DB import Arc, FilledRegion
    fm, fc, view = H.fm, H.fc, H.view
    fill = fm.get_Parameter('Show_Fill')
    for f in FilteredElementCollector(fd).OfClass(FilledRegion):
        fm.AssociateElementParameterToFamilyParameter(f.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM), fill)
    pl = dict((p.Name, p) for p in FilteredElementCollector(fd).OfClass(ReferencePlane))
    w, h = H.value('PR_Dimension_Width'), H.value('PR_Dimension_Height')

    def line(p0, p1, a, b_):
        el = fc.NewDetailCurve(view, Line.CreateBound(XYZ(p0[0] / FT, p0[1] / FT, 0), XYZ(p1[0] / FT, p1[1] / FT, 0)))
        fd.Regenerate()
        c = el.GeometryCurve
        for i, pls in ((0, a), (1, b_)):
            for q in pls:
                fc.NewAlignment(view, pl[q].GetReference(), c.GetEndPointReference(i))

    def arc(cx, cy, a0, a1, px, py):
        r = w / 2.0
        el = fc.NewDetailCurve(view, Arc.Create(XYZ(cx / FT, cy / FT, 0), r / FT, a0, a1, XYZ.BasisX, XYZ.BasisY))
        fd.Regenerate()
        for q in (px, py):
            fc.NewAlignment(view, pl[q].GetReference(), el.CenterPointReference)
        mid = (a0 + a1) / 2.0
        d = fc.NewRadialDimension(view, el.GeometryCurve.Reference,
                                  XYZ((cx + 0.5 * r * math.cos(mid)) / FT, (cy + 0.5 * r * math.sin(mid)) / FT, 0))
        d.FamilyLabel = fm.get_Parameter('Half_B')

    if shape == RECT:
        line((0, 0), (w, 0), ('Left', 'Bottom'), ('Right', 'Bottom'))
        line((w, 0), (w, h), ('Right', 'Bottom'), ('Right', 'Top'))
        line((w, h), (0, h), ('Right', 'Top'), ('Left', 'Top'))
        line((0, h), (0, 0), ('Left', 'Top'), ('Left', 'Bottom'))
        return
    R = w / 2.0
    top = 'Arc Top' if shape == ROUND2 else 'Top'
    ytop = h - R if shape == ROUND2 else h
    line((0, R), (0, ytop), ('Left', 'Arc Bottom'), ('Left', top))
    line((w, R), (w, ytop), ('Right', 'Arc Bottom'), ('Right', top))
    arc(R, R, math.pi, 2 * math.pi, 'Middle', 'Arc Bottom')
    if shape == ROUND2:
        arc(R, h - R, 0.0, math.pi, 'Middle', 'Arc Top')
    else:
        line((0, h), (w, h), ('Left', 'Top'), ('Right', 'Top'))


def _natural(name):
    import re
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', name)]


def _tidy(H):
    """Inputs grouped and ordered (Dimensions, Rebar Set, Graphics, the slots
    under Constraints), everything computed under Other; tooltips on the inputs."""
    from Autodesk.Revit.DB import ForgeTypeId, GroupTypeId
    fm = H.fm
    gid = {'geometry': GroupTypeId.Geometry, 'rebar': GroupTypeId.RebarArray,
           'graphics': GroupTypeId.Graphics, 'slots': GroupTypeId.Constraints, 'other': ForgeTypeId()}
    params = dict((p.Definition.Name, p) for p in fm.Parameters)
    order, placed = [], set()
    for g, names in GROUPS:
        for n in names:
            if n in params:
                order.append((g, params[n]))
                placed.add(n)
    slots = [n for n in params if n.startswith(SLOT_PREFIXES) and n.endswith(SLOT_INPUTS) and n not in placed]
    for n in sorted(slots, key=_natural):
        order.append(('slots', params[n]))
        placed.add(n)
    for n in sorted(params, key=_natural):
        if n in placed:
            continue
        p = params[n]
        g0 = p.Definition.GetGroupTypeId().TypeId
        builtin = g0.startswith('autodesk.parameter.group.identityData') or g0.startswith('autodesk.parameter.group.ifc')
        order.append((None if builtin else 'other', p))
    for g, p in order:
        if g is None:
            continue
        try:
            p.Definition.SetGroupTypeId(gid[g])
        except Exception:
            pass                       # a shared parameter may refuse: it keeps its group
        d = DESCRIPTIONS.get(p.Definition.Name)
        if d:
            try:
                fm.SetDescription(p, d)
            except Exception:
                pass
    from System.Collections.Generic import List
    from Autodesk.Revit.DB import FamilyParameter
    ids = List[FamilyParameter]([p for _, p in order])
    try:
        fm.ReorderParameters(ids)
    except Exception:
        pass


# ---- 21.11.2026: round column (user: a round column is needed too)

CIRCLE = 'CIRCLE'
NAMES[CIRCLE] = u'PEER_Column Section Round'
BAR_DOT = u'PEER_Col_BarDot'


def extract_bar_dot(app, round2_section, folder):
    """The filled bar dot the old rounded families nest (Family1 inside
    Point+Radius inside PR_Column Reinforcementr), saved as folder/PEER_Col_BarDot.rfa."""
    from peer_library import revit_family as rf
    docs = []
    fd = rf.open_quiet(app, round2_section)
    try:
        cur = fd
        for name in (u'PR_Column Reinforcementr', u'Point+Radius', u'Family1'):
            fam = [f for f in FilteredElementCollector(cur).OfClass(Family) if f.Name == name][0]
            cur = cur.EditFamily(fam)
            docs.append(cur)
        o = SaveAsOptions()
        o.OverwriteExistingFile = True
        cur.SaveAs(os.path.join(folder, BAR_DOT + u'.rfa'), o)
        return os.path.join(folder, BAR_DOT + u'.rfa')
    finally:
        for d in reversed(docs):
            try:
                d.Close(False)
            except Exception:
                pass
        fd.Close(False)


MAX_RING_BARS = 24
SHARED = {   # the section families' shared parameters (the column tag reads them)
    'PR_Dimension_Width': '8f2e4f93-9472-4941-a65d-0ac468fd6a5d',
    'PR_Dimension_Height': 'da753fe3-ecfa-465b-9a2c-02f55d0c2ff1',
    'Rebar_Diameter': '5498ba20-78b8-42d5-a4bf-f4ba6f5c16dd',
    'Rebar_QuantityX': 'de7637e2-5111-4f6b-ba9d-b8394ea5d7c3',
    'Rebar_Quantity': '9f1fd3ff-24b0-4862-b060-7e2af48108f4',
    'Rebar_Number': '3daaa3a8-42d9-4e71-86e3-9541a415b23b',
}


def _add_shared(app, fm, specs, folder):
    """Shared instance parameters by their GUIDs: [(name, spec, group)] ->
    {name: FamilyParameter}. A temporary shared parameter file in folder;
    the user's setting is restored."""
    from System import Guid
    from Autodesk.Revit.DB import ExternalDefinitionCreationOptions
    spf = os.path.join(folder, '_section_params.txt')
    if os.path.exists(spf):
        os.remove(spf)
    open(spf, 'w').close()
    old = app.SharedParametersFilename
    out = {}
    try:
        app.SharedParametersFilename = spf
        defs = app.OpenSharedParameterFile().Groups.Create('PEER').Definitions
        for name, spec, group in specs:
            o = ExternalDefinitionCreationOptions(name, spec)
            o.GUID = Guid(SHARED[name])
            out[name] = fm.get_Parameter(name) or fm.AddParameter(defs.Create(o), group, True)
    finally:
        app.SharedParametersFilename = old
    return out


def build_ring_bar(app, folder):
    """PEER_Col_RingBar: one bar dot Rr from the origin at the angle Ang
    (radial arrays of nested instances fail through the API - 'internal
    error' - so the section places MAX_RING_BARS of these, each turned by its
    own Ang). The dot sits on planes Rr * cos / sin(Ang) from the centre,
    measured from planes Off = Rr + 10 mm behind it (a labelled distance
    may not go negative or zero). Parameters Rr, Ang, Rebar_Diameter."""
    from Autodesk.Revit.DB import SpecTypeId as S
    from column_rebar.family_build import Builder
    b = Builder(app)
    try:
        def go():
            b.ensure_type('Bar')
            fm = b.fm
            from Autodesk.Revit.DB import GroupTypeId as G
            rr = b.param('Rr')
            ang = b.param('Ang', S.Angle)
            dia = _add_shared(app, fm, [('Rebar_Diameter', S.BarDiameter, G.RebarArray)], folder)['Rebar_Diameter']
            off, ox, oy = b.param('Off'), b.param('Ox'), b.param('Oy')
            fm.Set(rr, 200 / FT)
            fm.Set(ang, 0.0)
            fm.Set(dia, 20 / FT)
            fm.SetFormula(off, 'Rr + 10 mm')
            fm.SetFormula(ox, 'Rr * cos(Ang) + Off')
            fm.SetFormula(oy, 'Rr * sin(Ang) + Off')
            xl = b.plane('Behind x', True, -210)
            yl = b.plane('Behind y', False, -210)
            b.dim([xl.GetReference(), b.cx.GetReference()], True, -300, off)
            b.dim([yl.GetReference(), b.cy.GetReference()], False, -300, off)
            px = b.plane('Bar x', True, 200)
            py = b.plane('Bar y', False, 0)
            b.dim([xl.GetReference(), px.GetReference()], True, -350, ox)
            b.dim([yl.GetReference(), py.GetReference()], False, -350, oy)
            dot = _load(b.fd, os.path.join(folder, BAR_DOT + u'.rfa'))
            inst = b.fc.NewFamilyInstance(XYZ(200 / FT, 0, 0), dot, b.view)
            b.fd.Regenerate()
            lr = list(inst.GetReferences(FamilyInstanceReferenceType.CenterLeftRight))[0]
            fbk = list(inst.GetReferences(FamilyInstanceReferenceType.CenterFrontBack))[0]
            b.fc.NewAlignment(b.view, px.GetReference(), lr)
            b.fc.NewAlignment(b.view, py.GetReference(), fbk)
            fm.AssociateElementParameterToFamilyParameter(inst.LookupParameter('Rebar_Diameter'), dia)
            return True
        res = run(b.fd, 'PEER_Col_RingBar', go)
        if res[1] == 'Committed':
            b.save(os.path.join(folder, 'PEER_Col_RingBar.rfa'))
        return res
    finally:
        b.close()


def build_circle(app, folder, fill_source):
    """PEER_Column Section Round: concrete circle (outline + fill by Show_Fill),
    the round stirrup, Bars bar dots on a ring (count Bars, at most MAX_RING_BARS).
    Origin = the centre. fill_source: a section family to take the Concrete
    filled region type from. Parameters as the other section families
    (PR_Dimension_Width = diameter, Cover, Rebar_Diameter, Stirrup_Diameter)."""
    from Autodesk.Revit.DB import (Arc, ArrayAnchorMember, CopyPasteOptions, CurveElement, CurveLoop,
                                   ElementClassFilter, ElementId, FilledRegion, FilledRegionType,
                                   GroupTypeId, SpecTypeId, Transform)
    from System.Collections.Generic import List
    from column_rebar.family_build import Builder
    from peer_library import revit_family as rf
    b = Builder(app)
    src = rf.open_quiet(app, fill_source)
    try:
        def go():
            fm = b.fm
            b.ensure_type('Round')
            yes = SpecTypeId.Boolean.YesNo
            sh = _add_shared(app, fm, [
                ('PR_Dimension_Width', SpecTypeId.Length, GroupTypeId.Geometry),
                ('PR_Dimension_Height', SpecTypeId.Length, GroupTypeId.Geometry),
                ('Rebar_Diameter', SpecTypeId.BarDiameter, GroupTypeId.RebarArray),
                ('Rebar_QuantityX', SpecTypeId.Number, GroupTypeId.RebarArray),
                ('Rebar_Quantity', SpecTypeId.Number, GroupTypeId.RebarArray),
                ('Rebar_Number', SpecTypeId.Int.Integer, GroupTypeId.RebarArray)], folder)
            D, Hh, dl, qx = sh['PR_Dimension_Width'], sh['PR_Dimension_Height'], sh['Rebar_Diameter'], sh['Rebar_QuantityX']
            cov = fm.AddParameter('Cover', GroupTypeId.Geometry, SpecTypeId.Length, True)
            dw = fm.AddParameter('Stirrup_Diameter', GroupTypeId.RebarArray, SpecTypeId.Length, True)
            bars = fm.AddParameter('Bars', GroupTypeId.RebarArray, SpecTypeId.Int.Integer, True)
            for p_, v in ((D, 500.0), (cov, 25.0), (dl, 20.0), (dw, 8.0)):
                fm.Set(p_, v / FT)
            fm.Set(qx, 8.0)
            fm.SetFormula(bars, 'round(Rebar_QuantityX)')        # all the bars on the ring
            fm.SetFormula(sh['Rebar_Quantity'], 'Rebar_QuantityX')
            fm.SetFormula(sh['Rebar_Number'], 'Rebar_Diameter / 1 mm')
            fm.SetFormula(Hh, 'PR_Dimension_Width')
            cr = fm.AddParameter('CoverR', GroupTypeId.Geometry, SpecTypeId.Length, True)
            fm.SetFormula(cr, 'Cover + Stirrup_Diameter + Rebar_Diameter / 2')
            hd = fm.AddParameter('Hoop_D', GroupTypeId.Geometry, SpecTypeId.Length, True)
            fm.SetFormula(hd, 'PR_Dimension_Width - 2 * Cover - Stirrup_Diameter')
            rr = fm.AddParameter('Ring_R', GroupTypeId.Geometry, SpecTypeId.Length, True)
            fm.SetFormula(rr, 'PR_Dimension_Width / 2 - CoverR')
            fill = fm.AddParameter('Show_Fill', GroupTypeId.Graphics, yes, True)
            fm.Set(fill, 1)
            vb = fm.AddParameter('Vis_Rebar', GroupTypeId.Graphics, yes, True)
            fm.Set(vb, 1)
            r0 = 250.0
            # faces as the other section families name them (the drawing dimensions them)
            faces = {}
            for nm, vert, at in (('Left', True, -r0), ('Right', True, r0), ('Bottom', False, -r0), ('Top', False, r0)):
                faces[nm] = b.plane(nm, vert, at)
                # 'Is Reference' as in PEER_Column Section: Left 0, Right 2, Bottom 6, Top 8
                faces[nm].get_Parameter(BuiltInParameter.ELEM_REFERENCE_NAME).Set(
                    {'Left': 0, 'Right': 2, 'Bottom': 6, 'Top': 8}[nm])
            b.dim([faces['Left'].GetReference(), b.cx.GetReference(), faces['Right'].GetReference()],
                  True, -r0 - 150, None, equal=True)
            b.dim([faces['Left'].GetReference(), faces['Right'].GetReference()], True, -r0 - 250, D)
            b.dim([faces['Bottom'].GetReference(), b.cy.GetReference(), faces['Top'].GetReference()],
                  False, -r0 - 150, None, equal=True)
            b.dim([faces['Bottom'].GetReference(), faces['Top'].GetReference()], False, -r0 - 250, D)
            # concrete: outline and fill
            b.ring((0, 0), r0, b.cx, b.cy, D)
            ft_ = [t for t in FilteredElementCollector(src).OfClass(FilledRegionType)
                   if t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == u'Concrete']
            ids = ElementTransformUtils.CopyElements(src, List[ElementId]([ft_[0].Id]), b.fd,
                                                     Transform.Identity, CopyPasteOptions())
            loop = CurveLoop()
            loop.Append(Arc.Create(XYZ(0, 0, 0), r0 / FT, 0.0, math.pi, XYZ.BasisX, XYZ.BasisY))
            loop.Append(Arc.Create(XYZ(0, 0, 0), r0 / FT, math.pi, 2 * math.pi, XYZ.BasisX, XYZ.BasisY))
            fr = FilledRegion.Create(b.fd, list(ids)[0], b.view.Id, List[CurveLoop]([loop]))
            b.fd.Regenerate()
            fm.AssociateElementParameterToFamilyParameter(fr.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM), fill)
            edges = [b.fd.GetElement(i) for i in fr.GetDependentElements(ElementClassFilter(CurveElement))]
            for e in edges:
                for pl in (b.cx, b.cy):
                    try:
                        b.fc.NewAlignment(b.view, pl.GetReference(), e.CenterPointReference)
                    except Exception:
                        pass
            if edges:
                dd = b.fc.NewDiameterDimension(b.view, edges[0].GeometryCurve.Reference,
                                               XYZ(r0 / FT, r0 / FT, 0))
                dd.FamilyLabel = D
            # the round stirrup
            b.ring((0, 0), r0 - 29.0, b.cx, b.cy, hd)
            # bars: MAX_RING_BARS ring bars at the centre, bar k at (k - 1) * 360 / Bars,
            # shown while k <= Bars
            rb = _load(b.fd, os.path.join(folder, 'PEER_Col_RingBar.rfa'))
            for k in range(1, MAX_RING_BARS + 1):
                inst = b.fc.NewFamilyInstance(XYZ(0, 0, 0), rb, b.view)
                b.fd.Regenerate()
                lr = list(inst.GetReferences(FamilyInstanceReferenceType.CenterLeftRight))[0]
                fbk = list(inst.GetReferences(FamilyInstanceReferenceType.CenterFrontBack))[0]
                b.fc.NewAlignment(b.view, b.cx.GetReference(), lr)
                b.fc.NewAlignment(b.view, b.cy.GetReference(), fbk)
                a_k = fm.AddParameter('Bar%d_Ang' % k, GroupTypeId.Geometry, SpecTypeId.Angle, True)
                fm.SetFormula(a_k, u'%d * 360° / Bars' % (k - 1))
                v_k = fm.AddParameter('Bar%d_On' % k, GroupTypeId.Geometry, yes, True)
                fm.SetFormula(v_k, 'and(Vis_Rebar, Bars > %d)' % (k - 1))
                fm.AssociateElementParameterToFamilyParameter(inst.LookupParameter('Rr'), rr)
                fm.AssociateElementParameterToFamilyParameter(inst.LookupParameter('Ang'), a_k)
                fm.AssociateElementParameterToFamilyParameter(inst.LookupParameter('Rebar_Diameter'), dl)
                fm.AssociateElementParameterToFamilyParameter(
                    inst.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM), v_k)
            b.fd.Regenerate()
            for n_, d_ in DESCRIPTIONS.items():
                p_ = fm.get_Parameter(n_)
                if p_ is not None:
                    try:
                        fm.SetDescription(p_, d_)
                    except Exception:
                        pass
            fm.SetDescription(D, u'Diameter of the column.')
            fm.SetDescription(qx, u'Bars on the ring (all of them), at most %d.' % MAX_RING_BARS)
            return True
        res = run(b.fd, NAMES[CIRCLE], go)
        if res[1] == 'Committed':
            b.save(os.path.join(folder, NAMES[CIRCLE] + u'.rfa'))
        return res
    finally:
        src.Close(False)
        b.close()
