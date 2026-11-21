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
                    H.link(inst, 'C', hook)
                    H.link(inst, 'R', ho)
                H.visible(inst, vis)
            return H.made

        res = run(fd, NAMES[shape], go)
        if res[1] == 'Committed':
            o = SaveAsOptions()
            o.OverwriteExistingFile = True
            fd.SaveAs(os.path.join(folder, NAMES[shape] + u'.rfa'), o)
        return res
    finally:
        fd.Close(False)
