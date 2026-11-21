# -*- coding: utf-8 -*-
"""Ties of the section families drawn as the user's own tie family
(Klamrot 2d > Rebar_Shape 61): the tie runs BESIDE the bars (tangent, R from
their axes), each hook is a half circle round the bar and a straight return
leg of length C (Revit, IronPython 2.7). User 2026-11-20: 'lines through the
bar centres look bad, make the hooks as in my families'.

    PEER_Col_Tie    bars at (0, 0) and (0, L); the tie at x = +R; hooks round
                    both bars, returns at x = -R; Alt - the dashed variant
    PEER_Col_VTie   apex bar at (0, 0), end bars at (-W/2, H) and (W/2, H);
                    legs tangent on the outside, an arc round the apex bar,
                    hooks round the end bars with returns along the legs;
                    Wide: a flat end round two bars E apart (2026-11-21)

R = bar / 2 + tie / 2, C = hook return (Shape 62: max(50 + 2 D, 7 D) of the tie).
Every curve end is aligned to reference planes driven by labelled dimensions;
the V's inclined offsets are formula parameters (an arc whose end points are
aligned to planes follows them - checked 2026-11-20).
"""

import math
import os

from column_rebar.family_build import FT, Builder, run


def build_tie(app, folder):
    from Autodesk.Revit.DB import SpecTypeId as S
    b = Builder(app)
    try:
        def go():
            b.ensure_type('Tie')
            L, R, C = b.param('L'), b.param('R'), b.param('C')
            alt = b.param('Alt', S.Boolean.YesNo)
            solid = b.param('Solid', S.Boolean.YesNo)
            l, r, c = 400.0, 15.0, 70.0
            b.fm.Set(L, l / FT)
            b.fm.Set(R, r / FT)
            b.fm.Set(C, c / FT)
            b.fm.SetFormula(solid, 'not(Alt)')
            top = b.plane('End', False, l)
            xr = b.plane('Tie', True, r)
            xl = b.plane('Return', True, -r)
            yc0 = b.plane('Return 1', False, c)
            yc1 = b.plane('Return 2', False, l - c)
            b.dim([b.cy.GetReference(), top.GetReference()], False, 150, L)
            b.dim([b.cx.GetReference(), xr.GetReference()], True, -100, R)
            b.dim([xl.GetReference(), b.cx.GetReference()], True, -150, R)
            b.dim([b.cy.GetReference(), yc0.GetReference()], False, 200, C)
            b.dim([yc1.GetReference(), top.GetReference()], False, 200, C)
            dashed = b.dashed_style()
            for vis, style in ((solid, None), (alt, dashed)):
                els = [b.line((r, 0), (r, l), [xr, b.cy], [xr, top]),
                       b.arc((0, 0), r, math.pi, 2 * math.pi, b.cx, b.cy, R),      # under the first bar
                       b.line((-r, 0), (-r, c), [xl, b.cy], [xl, yc0]),
                       b.arc((0, l), r, 0.0, math.pi, b.cx, top, R),               # over the second bar
                       b.line((-r, l), (-r, l - c), [xl, top], [xl, yc1])]
                for el in els:
                    if style is not None:
                        el.LineStyle = style
                    b.visible_by(el, vis)
        res = run(b.fd, 'PEER_Col_Tie', go)
        if res[1] == 'Committed':
            b.save(os.path.join(folder, 'PEER_Col_Tie.rfa'))
        return res
    finally:
        b.close()


def build_vtie(app, folder, rebar_lines=False):
    """PEER_Col_VTie, two variants in one family (user 2026-11-21):
    Wide = no   the apex bent round ONE bar of the face at (0, 0);
    Wide = yes  a flat end round TWO bars at (-E/2, 0) and (E/2, 0): a bend
                round each and a straight piece between them behind the bars.
    End bars at (-W/2, H) and (W/2, H) in both. Every curve of a variant is
    visible by Pointed = not(Wide) / Wide; the hidden variant keeps a valid
    width (Ee = if(Wide, E, 100 mm)).
    rebar_lines: draw with a 'Rebar  Lines' subcategory (weight 6, as the
    PEER_Rebar_Shape families) - the copy nested in Shape 66 for the schedules."""
    from Autodesk.Revit.DB import SpecTypeId as S
    b = Builder(app)
    try:
        def go():
            b.ensure_type('V-tie')
            if rebar_lines:
                from Autodesk.Revit.DB import GraphicsStyleType
                cat = b.fd.OwnerFamily.FamilyCategory
                if not any(sc.Name == u'Rebar  Lines' for sc in cat.SubCategories):
                    sc = b.fd.Settings.Categories.NewSubcategory(cat, u'Rebar  Lines')
                    sc.SetLineWeight(6, GraphicsStyleType.Projection)
            W, H, R, C = b.param('W'), b.param('H'), b.param('R'), b.param('C')
            E = b.param('E')
            wide = b.param('Wide', S.Boolean.YesNo)
            pointed = b.param('Pointed', S.Boolean.YesNo)
            Ee = b.param('Ee')
            # built far apart: ends of the two variants closer than ~1 mm get joined
            # by Revit and then follow the wrong planes
            w, hh, r, c, e = 400.0, 300.0, 30.0, 70.0, 300.0
            for p_, v in ((W, w), (H, hh), (R, r), (C, c), (E, e)):
                b.fm.Set(p_, v / FT)
            b.fm.Set(wide, 1)                        # built wide (Ee = E), pointed by default at the end
            b.fm.SetFormula(pointed, 'not(Wide)')
            b.fm.SetFormula(Ee, 'if(Wide, E, 100 mm)')
            xl = b.plane('Left end', True, -w / 2)
            xr = b.plane('Right end', True, w / 2)
            yh = b.plane('Ends', False, hh)
            b.dim([xl.GetReference(), b.cx.GetReference(), xr.GetReference()], True, -150, None, equal=True)
            b.dim([xl.GetReference(), xr.GetReference()], True, -250, W)
            b.dim([b.cy.GetReference(), yh.GetReference()], False, w / 2 + 150, H)
            ybot = b.plane('Behind the bars', False, -r)
            b.dim([ybot.GetReference(), b.cy.GetReference()], False, w / 2 + 450, R)
            # wide: the two bars of the flat end
            al = b.plane('Flat bar left', True, -e / 2)
            ar = b.plane('Flat bar right', True, e / 2)
            b.dim([al.GetReference(), b.cx.GetReference(), ar.GetReference()], True, -500, None, equal=True)
            b.dim([al.GetReference(), ar.GetReference()], True, -550, Ee)
            _vtie_variant(b, 'P', w, hh, r, c, 0.0, pointed, xl, xr, yh, ybot, b.cx, b.cx)
            _vtie_variant(b, 'D', w, hh, r, c, e / 2.0, wide, xl, xr, yh, ybot, al, ar)
            b.fm.Set(wide, 0)
        res = run(b.fd, 'PEER_Col_VTie', go)
        if res[1] == 'Committed':
            b.save(os.path.join(folder, 'PEER_Col_VTie.rfa'))
        return res
    finally:
        b.close()


def _arc3(b, p1, p2, pm, centre_planes, end_planes):
    """Detail arc p1 -> p2 through pm (mm); centre aligned to centre_planes,
    end i to end_planes[i] (planes found by the actual end order)."""
    from Autodesk.Revit.DB import Arc, XYZ
    arc = Arc.Create(XYZ(p1[0] / FT, p1[1] / FT, 0), XYZ(p2[0] / FT, p2[1] / FT, 0),
                     XYZ(pm[0] / FT, pm[1] / FT, 0))
    el = b.fc.NewDetailCurve(b.view, arc)
    b._style(el)
    b.fd.Regenerate()
    for pl in centre_planes:
        b.fc.NewAlignment(b.view, pl.GetReference(), el.CenterPointReference)
    g = el.GeometryCurve
    q0 = g.GetEndPoint(0)
    first = 0 if abs(q0.X * FT - p1[0]) < 0.5 and abs(q0.Y * FT - p1[1]) < 0.5 else 1
    for k, pls in ((first, end_planes[0]), (1 - first, end_planes[1])):
        for pl in pls:
            b.fc.NewAlignment(b.view, pl.GetReference(), g.GetEndPointReference(k))
    return el


def _vtie_variant(b, tag, w, hh, r, c, half, vis, xl, xr, yh, ybot, apl, apr):
    """One variant of the V: the apex bar(s) at x = -half / +half (planes apl /
    apr; one bar at 0 when half = 0), legs tangent outside to the end bars."""
    fm = b.fm
    hf = 'Ee / 2' if tag == 'D' else '0 mm'
    Dx, Lw, Px, Py, Cx, Cy = (b.param(n + '_' + tag) for n in ('Dx', 'Lw', 'Px', 'Py', 'Cx', 'Cy'))
    fm.SetFormula(Dx, 'W / 2 - %s' % hf)
    fm.SetFormula(Lw, 'sqrt(Dx_%s ^ 2 + H ^ 2)' % tag)
    fm.SetFormula(Px, 'R * H / Lw_%s' % tag)
    fm.SetFormula(Py, 'R * Dx_%s / Lw_%s' % (tag, tag))
    fm.SetFormula(Cx, 'C * Dx_%s / Lw_%s' % (tag, tag))
    fm.SetFormula(Cy, 'C * H / Lw_%s' % tag)
    dx = w / 2 - half
    lw = math.hypot(dx, hh)
    px, py, cx_, cy_ = r * hh / lw, r * dx / lw, c * dx / lw, c * hh / lw
    off = 60 * (tag == 'D')
    els = []
    # tangent points at the apex bar(s)
    ta_l = b.plane('Apex left ' + tag, True, -half - px)
    ta_r = b.plane('Apex right ' + tag, True, half + px)
    ya = b.plane('Apex ' + tag, False, -py)
    b.dim([ta_l.GetReference(), apl.GetReference()], True, -400 - off, Px)
    b.dim([apr.GetReference(), ta_r.GetReference()], True, -400 - off, Px)
    b.dim([ya.GetReference(), b.cy.GetReference()], False, w / 2 + 250 + off, Py)
    if half == 0.0:
        els.append(_arc3(b, (-px, -py), (px, -py), (0, -r), (b.cx, b.cy), ((ta_l, ya), (ta_r, ya))))
    else:
        mid = (-math.pi / 2.0 + math.atan2(-py, px)) / 2.0     # right bend, mirrored for the left
        for s, apl_, ta in ((-1, apl, ta_l), (1, apr, ta_r)):
            x0 = s * half
            els.append(_arc3(b, (x0, -r), (x0 + s * px, -py),
                             (x0 + s * r * math.cos(mid), r * math.sin(mid)),
                             (apl_, b.cy), ((apl_, ybot), (ta, ya))))
        els.append(b.line((-half, -r), (half, -r), [apl, ybot], [apr, ybot]))
    # legs and the hooks round the end bars
    y1 = b.plane('Leg end ' + tag, False, hh - py)
    y2 = b.plane('Hook end ' + tag, False, hh + py)
    y3 = b.plane('Return end ' + tag, False, hh + py - cy_)
    b.dim([y1.GetReference(), yh.GetReference()], False, w / 2 + 300 + off, Py)
    b.dim([yh.GetReference(), y2.GetReference()], False, w / 2 + 300 + off, Py)
    b.dim([y3.GetReference(), y2.GetReference()], False, w / 2 + 350 + off, Cy)
    for s, xe in ((-1, xl), (1, xr)):
        ex = s * w / 2
        x1 = b.plane('Leg end %d %s' % (s, tag), True, ex + s * px)
        x2 = b.plane('Hook end %d %s' % (s, tag), True, ex - s * px)
        x3 = b.plane('Return end %d %s' % (s, tag), True, ex - s * px - s * cx_)
        if s < 0:
            b.dim([x1.GetReference(), xe.GetReference()], True, -300 - off, Px)
            b.dim([xe.GetReference(), x2.GetReference()], True, -300 - off, Px)
            b.dim([x2.GetReference(), x3.GetReference()], True, -350 - off, Cx)
        else:
            b.dim([xe.GetReference(), x1.GetReference()], True, -300 - off, Px)
            b.dim([x2.GetReference(), xe.GetReference()], True, -300 - off, Px)
            b.dim([x3.GetReference(), x2.GetReference()], True, -350 - off, Cx)
        e1 = (ex + s * px, hh - py)
        e2 = (ex - s * px, hh + py)
        e3 = (ex - s * px - s * cx_, hh + py - cy_)
        els.append(b.line((s * (half + px), -py), e1, [ta_r if s > 0 else ta_l, ya], [x1, y1]))
        far = (ex + s * r * dx / lw, hh + r * hh / lw)
        els.append(_arc3(b, e1, e2, far, (xe, yh), ((x1, y1), (x2, y2))))
        els.append(b.line(e2, e3, [x2, y2], [x3, y3]))
    for el in els:
        b.visible_by(el, vis)
