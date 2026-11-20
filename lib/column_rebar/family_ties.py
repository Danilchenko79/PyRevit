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
                    hooks round the end bars with returns along the legs

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


def build_vtie(app, folder):
    from Autodesk.Revit.DB import Arc, XYZ
    b = Builder(app)
    try:
        def go():
            b.ensure_type('V-tie')
            W, H, R, C = b.param('W'), b.param('H'), b.param('R'), b.param('C')
            w, hh, r, c = 400.0, 300.0, 15.0, 70.0
            for p, v in ((W, w), (H, hh), (R, r), (C, c)):
                b.fm.Set(p, v / FT)
            Lw, Px, Py, Cx, Cy = (b.param(n) for n in ('Lw', 'Px', 'Py', 'Cx', 'Cy'))
            b.fm.SetFormula(Lw, 'sqrt((W / 2) ^ 2 + H ^ 2)')
            b.fm.SetFormula(Px, 'R * H / Lw')
            b.fm.SetFormula(Py, 'R * (W / 2) / Lw')
            b.fm.SetFormula(Cx, 'C * (W / 2) / Lw')
            b.fm.SetFormula(Cy, 'C * H / Lw')
            lw = math.hypot(w / 2, hh)
            px, py, cx_, cy_ = r * hh / lw, r * (w / 2) / lw, c * (w / 2) / lw, c * hh / lw
            xl = b.plane('Left end', True, -w / 2)
            xr = b.plane('Right end', True, w / 2)
            yh = b.plane('Ends', False, hh)
            b.dim([xl.GetReference(), b.cx.GetReference(), xr.GetReference()], True, -150, None, equal=True)
            b.dim([xl.GetReference(), xr.GetReference()], True, -250, W)
            b.dim([b.cy.GetReference(), yh.GetReference()], False, w / 2 + 150, H)
            # the apex: bent round the middle bar, from one leg's tangent point to the other's
            xa_l = b.plane('Apex left', True, -px)
            xa_r = b.plane('Apex right', True, px)
            ya = b.plane('Apex', False, -py)
            b.dim([xa_l.GetReference(), b.cx.GetReference()], True, -400, Px)
            b.dim([b.cx.GetReference(), xa_r.GetReference()], True, -400, Px)
            b.dim([ya.GetReference(), b.cy.GetReference()], False, w / 2 + 250, Py)
            arc = Arc.Create(XYZ(-px / FT, -py / FT, 0), XYZ(px / FT, -py / FT, 0), XYZ(0, -r / FT, 0))
            el = b.fc.NewDetailCurve(b.view, arc)
            b._style(el)
            b.fd.Regenerate()
            for pl in (b.cx, b.cy):
                b.fc.NewAlignment(b.view, pl.GetReference(), el.CenterPointReference)
            g = el.GeometryCurve
            for i, pls in ((0, (xa_l, ya)), (1, (xa_r, ya))):
                for pl in pls:
                    b.fc.NewAlignment(b.view, pl.GetReference(), g.GetEndPointReference(i))
            y1 = b.plane('Leg end', False, hh - py)
            y2 = b.plane('Hook end', False, hh + py)
            y3 = b.plane('Return end', False, hh + py - cy_)
            b.dim([y1.GetReference(), yh.GetReference()], False, w / 2 + 300, Py)
            b.dim([yh.GetReference(), y2.GetReference()], False, w / 2 + 300, Py)
            b.dim([y3.GetReference(), y2.GetReference()], False, w / 2 + 350, Cy)
            for s, xe in ((-1, xl), (1, xr)):
                ex = s * w / 2
                x1 = b.plane('Leg end %d' % s, True, ex + s * px)
                x2 = b.plane('Hook end %d' % s, True, ex - s * px)
                x3 = b.plane('Return end %d' % s, True, ex - s * px - s * cx_)
                # distances always measured outwards-positive, labels are lengths
                if s < 0:
                    b.dim([x1.GetReference(), xe.GetReference()], True, -300, Px)
                    b.dim([xe.GetReference(), x2.GetReference()], True, -300, Px)
                    b.dim([x2.GetReference(), x3.GetReference()], True, -350, Cx)
                else:
                    b.dim([xe.GetReference(), x1.GetReference()], True, -300, Px)
                    b.dim([x2.GetReference(), xe.GetReference()], True, -300, Px)
                    b.dim([x3.GetReference(), x2.GetReference()], True, -350, Cx)
                e1 = (ex + s * px, hh - py)                 # leg meets the end bar (outside)
                e2 = (ex - s * px, hh + py)                 # hook comes round to the inside
                e3 = (ex - s * px - s * cx_, hh + py - cy_)  # return back along the leg
                b.line((s * px, -py), e1, [xa_r if s > 0 else xa_l, ya], [x1, y1])
                far = (ex + s * r * (w / 2) / lw, hh + r * hh / lw)
                arc = Arc.Create(XYZ(e1[0] / FT, e1[1] / FT, 0), XYZ(e2[0] / FT, e2[1] / FT, 0),
                                 XYZ(far[0] / FT, far[1] / FT, 0))
                el = b.fc.NewDetailCurve(b.view, arc)
                b._style(el)
                b.fd.Regenerate()
                for pl in (xe, yh):
                    b.fc.NewAlignment(b.view, pl.GetReference(), el.CenterPointReference)
                g = el.GeometryCurve
                for i, pls in ((0, (x1, y1)), (1, (x2, y2))):
                    for pl in pls:
                        b.fc.NewAlignment(b.view, pl.GetReference(), g.GetEndPointReference(i))
                b.line(e2, e3, [x2, y2], [x3, y3])
        res = run(b.fd, 'PEER_Col_VTie', go)
        if res[1] == 'Committed':
            b.save(os.path.join(folder, 'PEER_Col_VTie.rfa'))
        return res
    finally:
        b.close()
