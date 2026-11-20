# -*- coding: utf-8 -*-
"""The RECT section family 'PEER_Column Section' built from a copy of
'Create Column' (Revit, IronPython 2.7). docs/COLUMNS.md, item 12.

New name, so loading it never replaces the old family and the drawings of
the old button stay as they are. Changes against Create Column:
- cover to the stirrup: CoverR (bar axis from the face) = Cover + Stirrup_Diameter + D / 2;
- the perimeter stirrup is a nested PEER_Col_Hoop;
- Klamrot 2d and its parameters are removed;
- slots for the transverse reinforcement that the script fills from code466
  (names = host parameters <slot>_Vis / _X / _Y / _A / _W / _H):
    TieV1..8   straight tie along h at x = TieVi_X (holds bars of the b faces)
    TieH1..8   straight tie along b at y = TieHi_Y
    HoopV1..4  inner hoop over the full h, left bar at x = _X, width between bar axes _A
    HoopH1..4  inner hoop over the full b, bottom bar at y = _Y, height _A
    VB, VT     V-tie, apex on the bottom / top face at x = _X, opens inwards; _W, _H
    VL, VR     V-tie, apex on the left / right face at y = _Y
  x / y - bar axes from the left / bottom face of the concrete.
"""

import math
import os

from Autodesk.Revit.DB import (BuiltInParameter, ElementTransformUtils, Family,
                               FamilyInstanceReferenceType, FilteredElementCollector,
                               GroupTypeId, Line, ReferenceArray, ReferencePlane,
                               SaveAsOptions, SpecTypeId, ViewPlan, XYZ)

from column_rebar.family_build import FT, run

N_TIES, N_HOOPS = 8, 4
SECTION_NAME = u'PEER_Column Section'
KLAMROT = u'Klamrot 2d'
OLD_PARAMS = (u'HasVerticalSpacer', u'HasHorizontalSpacer', u'DistanceFirst SpacerX',
              u'DistanceFirst SpacerY', u'Quantity Side X', u'Quantity Side Y')


def slot_names():
    """[(slot, kind, direction)] in the order the slots are built."""
    out = [('TieV%d' % i, 'tie', 'V') for i in range(1, N_TIES + 1)]
    out += [('TieH%d' % i, 'tie', 'H') for i in range(1, N_TIES + 1)]
    out += [('HoopV%d' % i, 'hoop', 'V') for i in range(1, N_HOOPS + 1)]
    out += [('HoopH%d' % i, 'hoop', 'H') for i in range(1, N_HOOPS + 1)]
    out += [('VB', 'v', 'B'), ('VT', 'v', 'T'), ('VL', 'v', 'L'), ('VR', 'v', 'R')]
    return out


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


def build(app, src, folder):
    """src: a copy of Create Column.rfa; the nested PEER_Col_*.rfa in folder.
    Saves folder/PEER_Column Section.rfa. Returns (result, status, errors)."""
    from peer_library import revit_family as rf
    fd = rf.open_quiet(app, src)
    try:
        fm, fc = fd.FamilyManager, fd.FamilyCreate
        view = [v for v in FilteredElementCollector(fd).OfClass(ViewPlan) if not v.IsTemplate][0]
        planes = dict((p.Name, p) for p in FilteredElementCollector(fd).OfClass(ReferencePlane))
        left, right, bottom, top = planes['Left'], planes['Right'], planes['Bottom'], planes['Top']
        made = []

        def P(name, spec=None, formula=None, value=None):
            p = fm.get_Parameter(name)
            if p is None:
                p = fm.AddParameter(name, GroupTypeId.Geometry, spec or SpecTypeId.Length, True)
            if formula:
                fm.SetFormula(p, formula)
            elif value is not None:
                fm.Set(p, value)
            return p

        def plane(name, vertical, at_mm, ref_plane, label):
            a = at_mm / FT
            if vertical:
                pl = fc.NewReferencePlane(XYZ(a, -1, 0), XYZ(a, 1, 0), XYZ(0, 0, 1), view)
            else:
                pl = fc.NewReferencePlane(XYZ(-1, a, 0), XYZ(1, a, 0), XYZ(0, 0, 1), view)
            pl.Name = name
            fd.Regenerate()                      # a dimension to a fresh plane needs it
            ra = ReferenceArray()
            ra.Append(ref_plane.GetReference())
            ra.Append(pl.GetReference())
            o = -0.6 - 0.05 * len(made)
            ln = (Line.CreateBound(XYZ(-1, o, 0), XYZ(1, o, 0)) if vertical
                  else Line.CreateBound(XYZ(o, -1, 0), XYZ(o, 1, 0)))
            d = fc.NewDimension(view, ln, ra)
            d.FamilyLabel = label
            made.append(name)
            return pl

        def place(sym, x_mm, y_mm, angle_deg, vplane, hplane):
            """Instance at (x, y), rotated; its centre planes aligned to vplane
            (host plane x = const) and hplane (y = const)."""
            inst = fc.NewFamilyInstance(XYZ(x_mm / FT, y_mm / FT, 0), sym, view)
            if angle_deg:
                ax = Line.CreateBound(XYZ(x_mm / FT, y_mm / FT, 0), XYZ(x_mm / FT, y_mm / FT, 1))
                ElementTransformUtils.RotateElement(fd, inst.Id, ax, math.radians(angle_deg))
            fd.Regenerate()
            lr = list(inst.GetReferences(FamilyInstanceReferenceType.CenterLeftRight))[0]
            fbk = list(inst.GetReferences(FamilyInstanceReferenceType.CenterFrontBack))[0]
            turned = angle_deg % 180 != 0        # its own Left/Right plane is now horizontal
            fc.NewAlignment(view, (hplane if turned else vplane).GetReference(), lr)
            fc.NewAlignment(view, (vplane if turned else hplane).GetReference(), fbk)
            return inst

        def link(inst, child, host):
            fm.AssociateElementParameterToFamilyParameter(inst.LookupParameter(child), host)

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
            P('Stirrup_Diameter', value=8 / FT)
            fm.SetFormula(fm.get_Parameter('CoverR'), 'Cover + Stirrup_Diameter + Rebar_Diameter / 2')
            P('Ring_D', formula='Rebar_Diameter + Stirrup_Diameter')
            P('Hoop_O', formula='Rebar_Diameter / 2 + Stirrup_Diameter / 2')
            P('Bars_B', formula='PR_Dimension_Width - 2 * CoverR')
            P('Bars_H', formula='PR_Dimension_Height - 2 * CoverR')
            fd.Regenerate()
            ct = fm.CurrentType
            cr = fm.get_Parameter('CoverR')
            w = ct.AsDouble(fm.get_Parameter('PR_Dimension_Width')) * FT
            h = ct.AsDouble(fm.get_Parameter('PR_Dimension_Height')) * FT
            c = ct.AsDouble(cr) * FT
            # 3. bar lines
            bl = plane('Bar Left', True, c, left, cr)
            bb = plane('Bar Bottom', False, c, bottom, cr)
            br = plane('Bar Right', True, w - c, right, cr)
            bt = plane('Bar Top', False, h - c, top, cr)
            tie = _load(fd, os.path.join(folder, 'PEER_Col_Tie.rfa'))
            hoop = _load(fd, os.path.join(folder, 'PEER_Col_Hoop.rfa'))
            vtie = _load(fd, os.path.join(folder, 'PEER_Col_VTie.rfa'))
            bars_b, bars_h = fm.get_Parameter('Bars_B'), fm.get_Parameter('Bars_H')
            ring, ho = fm.get_Parameter('Ring_D'), fm.get_Parameter('Hoop_O')
            # 4. perimeter stirrup
            st = place(hoop, c, c, 0, bl, bb)
            link(st, 'A', bars_b)
            link(st, 'B', bars_h)
            link(st, 'O', ho)
            # 5. slots
            yes = SpecTypeId.Boolean.YesNo
            for name, kind, d in slot_names():
                vis = P(name + '_Vis', yes, value=0)
                if kind == 'tie':
                    if d == 'V':
                        pl = plane(name, True, w / 2, left, P(name + '_X', value=w / 2 / FT))
                        inst = place(tie, w / 2, c, 0, pl, bb)
                        link(inst, 'L', bars_h)
                    else:
                        pl = plane(name, False, h / 2, bottom, P(name + '_Y', value=h / 2 / FT))
                        inst = place(tie, c, h / 2, -90, bl, pl)
                        link(inst, 'L', bars_b)
                    link(inst, 'D', ring)
                elif kind == 'hoop':
                    a = P(name + '_A', value=100 / FT)
                    if d == 'V':
                        x0 = w / 2 - 50
                        pl = plane(name, True, x0, left, P(name + '_X', value=x0 / FT))
                        inst = place(hoop, x0, c, 0, pl, bb)
                        link(inst, 'A', a)
                        link(inst, 'B', bars_h)
                    else:
                        y0 = h / 2 - 50
                        pl = plane(name, False, y0, bottom, P(name + '_Y', value=y0 / FT))
                        inst = place(hoop, c, y0, 0, bl, pl)
                        link(inst, 'A', bars_b)
                        link(inst, 'B', a)
                    link(inst, 'O', ho)
                else:
                    vw = P(name + '_W', value=200 / FT)
                    vh = P(name + '_H', value=100 / FT)
                    if d in ('B', 'T'):
                        pl = plane(name, True, w / 2, left, P(name + '_X', value=w / 2 / FT))
                        if d == 'B':
                            inst = place(vtie, w / 2, c, 0, pl, bb)
                        else:
                            inst = place(vtie, w / 2, h - c, 180, pl, bt)
                    else:
                        pl = plane(name, False, h / 2, bottom, P(name + '_Y', value=h / 2 / FT))
                        if d == 'L':
                            inst = place(vtie, c, h / 2, -90, bl, pl)
                        else:
                            inst = place(vtie, w - c, h / 2, 90, br, pl)
                    link(inst, 'W', vw)
                    link(inst, 'H', vh)
                    link(inst, 'D', ring)
                fm.AssociateElementParameterToFamilyParameter(
                    inst.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM), vis)
            return len(made)

        res = run(fd, SECTION_NAME, go)
        if res[1] == 'Committed':
            o = SaveAsOptions()
            o.OverwriteExistingFile = True
            fd.SaveAs(os.path.join(folder, SECTION_NAME + u'.rfa'), o)
        return res
    finally:
        fd.Close(False)
