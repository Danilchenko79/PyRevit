# -*- coding: utf-8 -*-
"""SVG sketch of a column section from code466.design(). Pure Python.

The sketch is drawn from the design result only (bar coordinates, ties,
stirrup), so it shows exactly what the program decided. Used by the
gallery of test cases now and as the live preview of the window later.
"""

import math

from column_rebar import code466

CONCRETE, EDGE, STIRRUP, TIE, HOOP = '#e6e3dc', '#6b6b6b', '#1f5fbf', '#2a8a3a', '#8a3fc1'
FIXED, FREE, BAD, WARN, TEXT = '#111111', '#9a9a9a', '#d0302f', '#c98a00', '#333333'


def _n(v):
    return ('%.1f' % v).rstrip('0').rstrip('.')


def svg(result, b, h=None, cover=25.0, bar_dia=16.0, size=260.0, margin=56.0):
    """SVG text of the section. b, h, cover, bar_dia as given to design()."""
    circle = result['shape'] == code466.CIRCLE
    h = b if circle else h
    k = size / float(max(b, h))
    W, H = b * k + 2 * margin, h * k + 2 * margin
    X = lambda x: margin + x * k
    Y = lambda y: margin + (h - y) * k
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s %s" width="%s" height="%s" '
           'font-family="Segoe UI, Arial, sans-serif" font-size="11">' % (_n(W), _n(H), _n(W), _n(H))]
    bad = set(x['where'] for x in result['messages'] if x.get('where') and x['level'] == code466.RED)

    rounded = result['shape'] in code466.ROUNDED

    def outline(o):
        """SVG path of the rounded outline offset inwards by o."""
        R = b / 2.0 - o
        top = 'L %s %s A %s %s 0 0 1 %s %s ' % (_n(X(o)), _n(Y(h - b / 2.0)), _n(R * k), _n(R * k),
                                               _n(X(b - o)), _n(Y(h - b / 2.0)))
        if result['shape'] == code466.ROUND2:
            return ('M %s %s ' % (_n(X(o)), _n(Y(b / 2.0))) + top +
                    'L %s %s A %s %s 0 0 1 %s %s Z' % (_n(X(b - o)), _n(Y(b / 2.0)), _n(R * k), _n(R * k),
                                                       _n(X(o)), _n(Y(b / 2.0))))
        # ROUND1: round end at the bottom, flat end on top (as the family)
        return ('M %s %s L %s %s L %s %s L %s %s A %s %s 0 0 1 %s %s Z'
                % (_n(X(o)), _n(Y(b / 2.0)), _n(X(o)), _n(Y(h - o)), _n(X(b - o)), _n(Y(h - o)),
                   _n(X(b - o)), _n(Y(b / 2.0)), _n(R * k), _n(R * k), _n(X(o)), _n(Y(b / 2.0))))

    # concrete
    if rounded:
        out.append('<path d="%s" fill="%s" stroke="%s" stroke-width="1.2"/>' % (outline(0), CONCRETE, EDGE))
        if 'h' in bad:
            for x in (0, b):
                out.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="4"/>'
                           % (_n(X(x)), _n(Y(b / 2.0)), _n(X(x)), _n(Y(h - b / 2.0)), BAD))
    elif circle:
        out.append('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="%s" stroke-width="1.2"/>'
                   % (_n(X(b / 2.0)), _n(Y(b / 2.0)), _n(b / 2.0 * k), CONCRETE, EDGE))
    else:
        out.append('<rect x="%s" y="%s" width="%s" height="%s" fill="%s" stroke="%s" stroke-width="1.2"/>'
                   % (_n(X(0)), _n(Y(h)), _n(b * k), _n(h * k), CONCRETE, EDGE))
        for side, segs in (('b', ((0, 0, b, 0), (0, h, b, h))), ('h', ((0, 0, 0, h), (b, 0, b, h)))):
            if side in bad:
                for x1, y1, x2, y2 in segs:
                    out.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="4"/>'
                               % (_n(X(x1)), _n(Y(y1)), _n(X(x2)), _n(Y(y2)), BAD))

    st = result['stirrup']
    if st:
        dw = st['dia']
        w = max(1.2, dw * k)
        off = cover + dw / 2.0
        r = code466.mandrel(dw) / 2.0 + dw / 2.0
        if rounded and st.get('contour') == code466.CONTOUR_SPLIT:
            # rectangular hoop over the straight part + half-round U-bar(s) on the round end(s)
            R, rr = b / 2.0, b / 2.0 - off
            y0 = R - bar_dia / 2.0 - dw / 2.0
            y1 = (h - R + bar_dia / 2.0 + dw / 2.0) if result['shape'] == code466.ROUND2 else h - off
            out.append('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="none" stroke="%s" '
                       'stroke-width="%s"/>' % (_n(X(off)), _n(Y(y1)), _n((b - 2 * off) * k), _n((y1 - y0) * k),
                                                _n(r * k), STIRRUP, _n(w)))
            # the U-bar a stirrup diameter outside the hoop, so the lap reads as two lines
            leg, uo = st['u']['leg'], off - dw
            rr = b / 2.0 - uo
            ends = [(R, 1)] + ([(h - R, -1)] if result['shape'] == code466.ROUND2 else [])
            for yc, sgn in ends:
                ye = yc + sgn * leg
                out.append('<path d="M %s %s L %s %s A %s %s 0 0 %d %s %s L %s %s" fill="none" stroke="%s" '
                           'stroke-width="%s" stroke-linejoin="round"/>'
                           % (_n(X(uo)), _n(Y(ye)), _n(X(uo)), _n(Y(yc)), _n(rr * k), _n(rr * k),
                              0 if sgn > 0 else 1, _n(X(b - uo)), _n(Y(yc)), _n(X(b - uo)), _n(Y(ye)),
                              STIRRUP, _n(w)))
        elif rounded:
            out.append('<path d="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round"/>'
                       % (outline(off), STIRRUP, _n(w)))
        elif circle:
            out.append('<circle cx="%s" cy="%s" r="%s" fill="none" stroke="%s" stroke-width="%s"/>'
                       % (_n(X(b / 2.0)), _n(Y(b / 2.0)), _n((b / 2.0 - off) * k), STIRRUP, _n(w)))
        else:
            out.append('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="none" stroke="%s" '
                       'stroke-width="%s"/>' % (_n(X(off)), _n(Y(h - off)), _n((b - 2 * off) * k),
                                                _n((h - 2 * off) * k), _n(r * k), STIRRUP, _n(w)))
            # 135 degree hooks at the top left corner
            cx, cy = off + r, h - off - r
            for ang in (135.0,):
                a = math.radians(ang)
                px, py = cx + r * math.cos(a), cy + r * math.sin(a)
                L = max(6.0 * dw, 50.0)
                d = math.radians(-45.0)
                out.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s" '
                           'stroke-linecap="round"/>' % (_n(X(px)), _n(Y(py)), _n(X(px + L * math.cos(d))),
                                                         _n(Y(py + L * math.sin(d))), STIRRUP, _n(w)))

    # ties: along the tied bars, hooks drawn as rings round the end bars
    dl = bar_dia

    def poly(pts, w, dash=''):
        out.append(('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s" '
                    'stroke-linejoin="round"' + dash + '/>')
                   % (' '.join('%s,%s' % (_n(X(px)), _n(Y(py))) for px, py in pts), TIE, _n(w)))

    def arc(c, r, a0, a1, n=14):
        return [(c[0] + r * math.cos(a0 + (a1 - a0) * i / float(n)),
                 c[1] + r * math.sin(a0 + (a1 - a0) * i / float(n))) for i in range(n + 1)]

    # ties as the family draws them (the user's Rebar_Shape 61): beside the bars,
    # a half circle round each end bar and a straight return
    for t in result['ties']:
        dw = t['dia']
        w = max(1.2, dw * k)
        R = dl / 2.0 + dw / 2.0
        C = max(50.0 + 2 * dw, 7.0 * dw)
        dash = ' stroke-dasharray="3 2"' if t.get('alt') else ''   # placed in turn with the mirror tie
        if t.get('kind') == 'v' and t.get('flat'):
            # V with a flat end round two bars (user 2026-11-21): a bend round each,
            # the flat piece behind them, legs and hooks as the plain V
            p1, _, p2 = t['points']
            A1, A2 = t['flat']
            fl = math.hypot(A2[0] - A1[0], A2[1] - A1[1])
            f = ((A2[0] - A1[0]) / fl, (A2[1] - A1[1]) / fl)
            nb = (-f[1], f[0])
            if nb[0] * (p1[0] - A1[0]) + nb[1] * (p1[1] - A1[1]) > 0:
                nb = (f[1], -f[0])                         # behind the bars, away from the legs
            poly([(A1[0] + R * nb[0], A1[1] + R * nb[1]), (A2[0] + R * nb[0], A2[1] + R * nb[1])], w)
            for E, A, other in ((p1, A1, A2), (p2, A2, A1)):
                L = math.hypot(E[0] - A[0], E[1] - A[1])
                u = ((E[0] - A[0]) / L, (E[1] - A[1]) / L)
                n = (-u[1], u[0])
                if n[0] * (other[0] - A[0]) + n[1] * (other[1] - A[1]) > 0:
                    n = (u[1], -u[0])                      # the outside of the V
                b0, b1 = math.atan2(nb[1], nb[0]), math.atan2(n[1], n[0])
                dd = (b1 - b0 + math.pi) % (2 * math.pi) - math.pi
                poly(arc(A, R, b0, b0 + dd), w)
                st_ = (A[0] + R * n[0], A[1] + R * n[1])
                en_ = (E[0] + R * n[0], E[1] + R * n[1])
                an = math.atan2(n[1], n[0])
                au = math.atan2(u[1], u[0])
                dd = math.pi if math.cos(an + math.pi / 2 - au) > 0 else -math.pi
                hook = arc(E, R, an, an + dd)
                back = hook[-1]
                ret = (back[0] - C * u[0], back[1] - C * u[1])
                poly([st_, en_] + hook[1:] + [ret], w)
            continue
        if t.get('kind') == 'v':
            p1, A, p2 = t['points']
            pts_all = []
            legs = []
            for E, other in ((p1, p2), (p2, p1)):
                L = math.hypot(E[0] - A[0], E[1] - A[1])
                u = ((E[0] - A[0]) / L, (E[1] - A[1]) / L)
                n = (-u[1], u[0])
                if n[0] * (other[0] - A[0]) + n[1] * (other[1] - A[1]) > 0:
                    n = (u[1], -u[0])                      # the outside of the V
                legs.append((E, u, n))
            # apex: an arc round the middle bar between the two legs, on the outside
            a1 = math.atan2(legs[0][2][1], legs[0][2][0])
            a2 = math.atan2(legs[1][2][1], legs[1][2][0])
            bis = (legs[0][1][0] + legs[1][1][0], legs[0][1][1] + legs[1][1][1])
            far = math.atan2(-bis[1], -bis[0])
            d = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
            mid = a1 + d / 2.0
            if math.cos(mid - far) < 0:
                d = d - 2 * math.pi if d > 0 else d + 2 * math.pi
            poly(arc(A, R, a1, a1 + d), w)
            for E, u, n in legs:
                st_ = (A[0] + R * n[0], A[1] + R * n[1])
                en_ = (E[0] + R * n[0], E[1] + R * n[1])
                an = math.atan2(n[1], n[0])
                au = math.atan2(u[1], u[0])
                dd = math.pi if math.cos(an + math.pi / 2 - au) > 0 else -math.pi
                hook = arc(E, R, an, an + dd)
                back = hook[-1]
                ret = (back[0] - C * u[0], back[1] - C * u[1])
                poly([st_, en_] + hook[1:] + [ret], w)
            continue
        if t['direction'] == code466.VERTICAL:
            ends = [(x, y) for x, y in result['bars'] if abs(x - t['at']) < 0.5]
            if len(ends) < 2:
                continue
            (x1, y1), (x2, y2) = min(ends, key=lambda p: p[1]), max(ends, key=lambda p: p[1])
            poly([(x1 - R, y1 + C)] + arc((x1, y1), R, math.pi, 2 * math.pi) +
                 arc((x2, y2), R, 0.0, math.pi) + [(x2 - R, y2 - C)], w, dash)
        else:
            ends = [(x, y) for x, y in result['bars'] if abs(y - t['at']) < 0.5]
            if len(ends) < 2:
                continue
            (x1, y1), (x2, y2) = min(ends), max(ends)
            poly([(x1 + C, y1 + R)] + arc((x1, y1), R, math.pi / 2, 3 * math.pi / 2) +
                 arc((x2, y2), R, -math.pi / 2, math.pi / 2) + [(x2 - C, y2 + R)], w, dash)

    # inner hoops (rectangles round two bars of each face)
    for hp in result.get('hoops') or []:
        w = max(1.2, hp['dia'] * k)
        off = dl / 2.0 + hp['dia'] / 2.0
        if hp['kind'] == 'rect':
            x0, y0, x1, y1 = hp['box']
            r = code466.mandrel(hp['dia']) / 2.0 + hp['dia'] / 2.0
            out.append('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="none" stroke="%s" '
                       'stroke-width="%s"/>' % (_n(X(x0 - off)), _n(Y(y1 + off)), _n((x1 - x0 + 2 * off) * k),
                                                _n((y1 - y0 + 2 * off) * k), _n(r * k), HOOP, _n(w)))
        else:
            pts = ' '.join('%s,%s' % (_n(X(px)), _n(Y(py))) for px, py in hp['points'])
            out.append('<polygon points="%s" fill="none" stroke="%s" stroke-width="%s" '
                       'stroke-linejoin="round"/>' % (pts, HOOP, _n(w)))
            for px, py in hp['points']:
                out.append('<circle cx="%s" cy="%s" r="%s" fill="none" stroke="%s" stroke-width="%s"/>'
                           % (_n(X(px)), _n(Y(py)), _n(off * k), HOOP, _n(w)))

    # bars
    for (x, y), fixed in zip(result['bars'], result['restrained']):
        out.append('<circle cx="%s" cy="%s" r="%s" fill="%s"/>'
                   % (_n(X(x)), _n(Y(y)), _n(max(2.0, dl / 2.0 * k)), FIXED if fixed else FREE))

    # dimensions and bar spacing
    out.append('<text x="%s" y="%s" text-anchor="middle" fill="%s">%s</text>'
               % (_n(X(b / 2.0)), _n(Y(0) + 18), TEXT, ('D' + _n(b)) if circle else _n(b)))
    if not circle:
        out.append('<text x="%s" y="%s" text-anchor="middle" fill="%s" transform="rotate(-90 %s %s)">%s</text>'
                   % (_n(X(0) - 12), _n(Y(h / 2.0)), TEXT, _n(X(0) - 12), _n(Y(h / 2.0)), _n(h)))
        for side, coord in (() if rounded else (('b', 0), ('h', 1))):
            pos = sorted(set(round(p[coord], 3) for p in result['bars']
                             if abs(p[1 - coord] - min(q[1 - coord] for q in result['bars'])) < 0.5)) \
                if result['bars'] else []
            if len(pos) < 2:
                continue
            step = pos[1] - pos[0]
            col = BAD if side in bad else TEXT
            txt = u'%s: %s c/c, %s clear' % (side, _n(round(step)), _n(round(step - dl)))
            if side == 'b':
                out.append('<text x="%s" y="%s" text-anchor="middle" fill="%s">%s</text>'
                           % (_n(X(b / 2.0)), _n(Y(0) + 34), col, txt))
            else:
                out.append('<text x="%s" y="%s" text-anchor="middle" fill="%s" transform="rotate(-90 %s %s)">%s</text>'
                           % (_n(X(b) + 16), _n(Y(h / 2.0)), col, _n(X(b) + 16), _n(Y(h / 2.0)), txt))
    out.append('</svg>')
    return u'\n'.join(out)
