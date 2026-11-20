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
        return ('M %s %s ' % (_n(X(o)), _n(Y(o))) + top + 'L %s %s Z' % (_n(X(b - o)), _n(Y(o))))

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
        if rounded:
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
    for t in result['ties']:
        w = max(1.2, t['dia'] * k)
        shift = dl / 2.0 + t['dia'] / 2.0
        if t.get('kind') == 'v':
            pts = ' '.join('%s,%s' % (_n(X(px)), _n(Y(py))) for px, py in t['points'])
            out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s" '
                       'stroke-linejoin="round"/>' % (pts, TIE, _n(w)))
            for px, py in t['points']:
                out.append('<circle cx="%s" cy="%s" r="%s" fill="none" stroke="%s" stroke-width="%s"/>'
                           % (_n(X(px)), _n(Y(py)), _n(shift * k), TIE, _n(w)))
            continue
        if t['direction'] == code466.VERTICAL:
            ends = [(x, y) for x, y in result['bars'] if abs(x - t['at']) < 0.5]
            if len(ends) < 2:
                continue
            (x1, y1), (x2, y2) = min(ends, key=lambda p: p[1]), max(ends, key=lambda p: p[1])
            out.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s"/>'
                       % (_n(X(x1 - shift)), _n(Y(y1)), _n(X(x2 - shift)), _n(Y(y2)), TIE, _n(w)))
        else:
            ends = [(x, y) for x, y in result['bars'] if abs(y - t['at']) < 0.5]
            if len(ends) < 2:
                continue
            (x1, y1), (x2, y2) = min(ends), max(ends)
            out.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s"/>'
                       % (_n(X(x1)), _n(Y(y1 + shift)), _n(X(x2)), _n(Y(y2 + shift)), TIE, _n(w)))
        for x, y in ((x1, y1), (x2, y2)):
            out.append('<circle cx="%s" cy="%s" r="%s" fill="none" stroke="%s" stroke-width="%s"/>'
                       % (_n(X(x)), _n(Y(y)), _n(shift * k), TIE, _n(w)))

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
