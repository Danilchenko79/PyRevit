# -*- coding: utf-8 -*-
"""Строки результата для продавливания: тип, класс, β, V_d, входы калькуляторов, проверка (check.py)."""
from tributary import check as CH

KIND_LABEL = {
    'column': u'Column',
    'pylon': u'Pier',
    'wall_L': u'Wall corner L',
    'wall_T': u'Wall T-junction',
    'wall_X': u'Wall crossing X',
    'wall_end': u'Wall end',
    'wall_mid': u'Wall (middle)',
    'beam': u'Beam',
}
CLS_LABEL = {'int': u'interior', 'edge': u'edge', 'corner': u'corner'}

# тип элемента в calc-punching-shear-v6 / отдельный калькулятор
CALC = {
    ('column', 'int'): u'v6: col-int',
    ('column', 'edge'): u'v6: col-edge',
    ('column', 'corner'): u'v6: col-corner',
    ('pylon', 'int'): u'v6: wall-int',
    ('pylon', 'edge'): u'v6: wall-edge',
    ('pylon', 'corner'): u'v6: wall-corner',
    ('wall_L', None): u'wall-corner_v2',
    ('wall_T', None): u'—',
    ('wall_X', None): u'—',
    ('wall_end', None): u'—',
}

COLUMNS = [
    (u'#', 'n'), (u'Support type', 'kind_label'), (u'Position', 'cls_label'),
    (u'Calculator', 'calc'), (u'A_trib, m²', 'A'), (u'β', 'beta'),
    (u'V_d, kN', 'Vd'), (u'β·V_d, kN', 'bVd'), (u'h, mm', 'h'), (u'd_m, mm', 'dm'),
    (u'c1 / la, mm', 'c1'), (u'c2 / lb, mm', 'c2'), (u't_a, mm', 'ta'), (u't_b, mm', 'tb'),
    (u'Angle, °', 'angle'), (u'To edge, mm', 'edge_dist'),
    (u'u0, m', 'u0'), (u'u1, m', 'u1'), (u'A_u1, m²', 'Au1'), (u'K', 'K'), (u'ρ', 'rho'),
    (u'V_Rd,c, kN', 'VRdc'), (u'V_Rd,max, kN', 'VRdmax'), (u'V_eq, kN', 'Veq'), (u'η = V_eq/V_Rd,c', 'eta'),
    (u'Punching check', 'check'), (u'A_sw, cm²/perimeter', 'Asw'),
    (u'X, m', 'x'), (u'Y, m', 'y'),
    (u'ElementId', 'ids'), (u'Link', 'link'), (u'Flags', 'flags'),
]


def _r(v, nd=0):
    if v is None:
        return None
    return int(round(v)) if nd == 0 else round(v, nd)


def row(pt, p):
    kind = pt['kind']
    cls = pt.get('cls')
    key = u'{}:{}'.format(kind, cls) if kind in ('column', 'pylon') else kind
    beta = p['beta'].get(key)
    A = pt['area'] / 1e6
    q = p['q_d']
    Vd = q * A if q > 0 else None
    r = {
        'n': pt['n'], 'kind': kind, 'kind_label': KIND_LABEL.get(kind, kind),
        'cls': cls, 'cls_label': CLS_LABEL.get(cls, u'—') if cls else u'—',
        'calc': CALC.get((kind, cls if kind in ('column', 'pylon') else None), u'—'),
        'A': round(A, 2), 'beta': beta,
        'Vd': _r(Vd, 1), 'bVd': _r(beta * Vd, 1) if (Vd is not None and beta) else None,
        'h': _r(pt['h']), 'dm': _r(pt['dm']),
        'c1': None, 'c2': None, 'ta': None, 'tb': None, 'angle': None,
        'edge_dist': _r(pt.get('edge_dist')),
        'x': round(pt['x'] / 1000.0, 3), 'y': round(pt['y'] / 1000.0, 3),
        'ids': u', '.join(u'{}'.format(i) for i in pt['ids']),
        'link': u', '.join(sorted(set(l for l in pt['links'] if l))),
        'flags': u'; '.join(pt['flags']),
        'u0': None, 'u1': None, 'Au1': None, 'K': None, 'rho': None, 'VRdc': None, 'VRdmax': None,
        'Veq': None, 'eta': None, 'check': None, 'Asw': None,
    }
    geo = CH.perim_of(pt)
    if geo:
        r['u0'], r['u1'], r['Au1'] = round(geo['u0'], 3), round(geo['u1'], 3), round(geo['A'], 3)
        c = CH.punch(geo, pt['dm'], Vd, q, beta, CH.inputs(p))
        if c:
            r['K'], r['rho'] = round(c['K'], 3), round(c['rho'], 5)
            r['VRdc'], r['VRdmax'], r['Veq'] = _r(c['VRdc'], 1), _r(c['VRdmax'], 1), _r(c['Veq'], 1)
            r['eta'] = round(c['eta'], 2) if c['eta'] is not None else None
            r['check'] = c['label'] + (u' · ' + u'; '.join(c['warn']) if c['warn'] else u'')
            r['Asw'] = _r(c['Asw'], 2)
    dims = pt['dims']
    if kind in ('column', 'pylon'):
        if dims.get('shape') == 'round':
            r['c1'] = r['c2'] = _r(dims['b'])
            r['flags'] = u'; '.join([u'round D{}'.format(_r(dims['b']))] + pt['flags'])
        else:
            r['c1'], r['c2'] = _r(dims['b']), _r(dims['h'])
    else:
        legs = sorted(dims.get('legs', []), key=lambda g: -g['len'])
        if kind == 'wall_L' and len(legs) >= 2:
            r['c1'], r['c2'] = _r(legs[0]['len']), _r(legs[1]['len'])
            r['ta'], r['tb'] = _r(legs[0]['t']), _r(legs[1]['t'])
            r['angle'] = _r(dims.get('angle'))
        elif legs:
            r['c1'] = _r(legs[0]['len'])
            r['ta'] = _r(legs[0]['t'])
            if len(legs) > 1:
                r['c2'] = _r(legs[1]['len'])
                r['tb'] = _r(legs[1]['t'])
    return r
