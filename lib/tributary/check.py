# -*- coding: utf-8 -*-
"""Проверка продавливания по Excel компании «חישוב חדירה» (лист «עמוד פנימי»,
ת"י 466.1 изм. 7, арматура 500 МПа). Только плита («תקרה»), периметр u1 на 2d.

Формулы Excel переведены из т/м в кН/м (1 МПа·м² = 1000 кН; в Excel 1 МПа = 100 т/м²):
    Veq    = β·V_d − β·q_d·A_u1
    K      = min(2, 1 + √(200/d))
    ρ      = Σ As / d        (Ø1@s1 + Ø2@s2 верхней арматуры над опорой)
    V_Rd,c = max(0.035·K^1.5·√(0.7fck) + 0.1σcp ; 0.12·K·(100ρ·0.7fck)^(1/3) + 0.1σcp)·u1·d
    V_Rd,max = 0.24·(1 − 0.7fck/250)·0.93·(0.7/1.5)·fck·u0·d
    Итог: β·V_d > V_Rd,max или Veq > 1.5·V_Rd,c — увеличить толщину;
          V_Rd,c > Veq — арматура не нужна; иначе — поперечная арматура (Asw, Asα, Asb, s, m).

Периметры (d = d_m; колонна a — большая сторона, a' = min(a, 3d), b — как в Excel, без ограничения):
    колонна/пилон внутр.   u0 = 2a'+2b      u1 = u0 + 4πd   A = a'b + 4d(a'+b) + 4πd²
    круглая внутр.         u0 = πD          u1 = π(D+4d)    A = π(D+4d)²/4
    торец стены («קיר קצה»)  u0 = t+3d      u1 = u0 + 2πd   A = 6d² + 2td + 2πd²
    угол L («קיר פינה»)      u0 = 3d        u1 = u0 + πd    A = 6d² + πd²
    колонна крайняя / угловая — в Excel нет; по EC2 6.4.2 с краем по грани колонны
    (решение пользователя 30.09.2026), те же формулы, что у торца / угла стены:
      крайняя  c∥' = min(c∥, 3d), c⊥' = min(c⊥, 1.5d): u0 = c∥'+2c⊥'  u1 = u0 + 2πd
               A = c∥'c⊥' + 2d·c∥' + 4d·c⊥' + 2πd²
      угловая  c1' = min(c1, 1.5d), c2' = min(c2, 1.5d): u0 = c1'+c2'  u1 = u0 + πd
               A = c1'c2' + 2d(c1'+c2') + πd²
      круглая у края — квадрат равной площади, флаг.

Чистый Python (IronPython 2.7 / CPython 3). Порт — engine.js: perim/punch (сверка в tests).
"""
import math

PI = math.pi

# Входные данные проверки по умолчанию (переопределяются в params / в HTML-схеме).
DEFAULTS = {
    'fck': 30.0,       # МПа (кубиковая, как в ת"י 466; в формулах 0.7·fck)
    'top_d1': 0.0,     # Ø1 верхних стержней над опорой, мм (0 -> bar_d)
    'top_s1': 200.0,   # шаг Ø1, мм
    'top_d2': 0.0,     # Ø2 дополнительных стержней, мм (0 -> нет)
    'top_s2': 200.0,   # шаг Ø2, мм
    'sigma_cp': 0.0,   # МПа, обжатие (преднапряжение)
    'sr': 0.0,         # шаг периметров хомутов, мм (0 -> 0.75·d_m, вниз до 10 мм)
    'alpha_w': 90.0,   # наклон хомутов, град
    'alpha_b': 45.0,   # наклон отгибов, град
}

RESULT_LABEL = {
    'ok': u'OK — no punching reinforcement',
    'reinf': u'Punching reinforcement required',
    'thick_max': u'Increase slab thickness (β·V_d > V_Rd,max)',
    'thick_c': u'Increase slab thickness (V_eq > 1.5·V_Rd,c)',
}

SHAPE_LABEL = {
    'col_int': u'column interior', 'round_int': u'round column interior',
    'col_edge': u'column at edge (EC2)', 'col_corner': u'column at corner (EC2)',
    'wall_end': u'wall end', 'wall_L': u'wall corner',
}


def inputs(p, over=None):
    """Входы проверки: DEFAULTS <- params <- правки точки. Ø1 = 0 -> bar_d."""
    r = dict(DEFAULTS)
    for k in DEFAULTS:
        if p and p.get(k) is not None:
            r[k] = float(p[k])
    if over:
        for k, v in over.items():
            if k in DEFAULTS and v is not None and v != u'':
                r[k] = float(v)
    if not r['top_d1'] > 0:
        r['top_d1'] = float((p or {}).get('bar_d') or 12.0)
    return r


def perim(kind, cls, c1, c2, shape, t, dm, eax=None):
    """Периметры по типу точки. c1, c2, t, dm — мм (c1 вдоль оси u сечения, c2 — вдоль v).
    eax — ось грани у края для крайней колонны ('u' | 'v'). -> dict, длины м, площадь м²."""
    d = dm / 1000.0
    flags = []
    if kind in ('column', 'pylon'):
        a1, a2 = (c1 or 0.0) / 1000.0, (c2 or 0.0) / 1000.0
        rnd = shape == 'round'
        if cls in ('edge', 'corner') and rnd:
            a1 = a2 = a1 * math.sqrt(PI) / 2.0
            rnd = False
            flags.append(u'round column at edge: equivalent square')
        if cls == 'edge':
            perp, par = (a1, a2) if eax != 'v' else (a2, a1)
            cp, cq = min(par, 3.0 * d), min(perp, 1.5 * d)
            u0 = cp + 2.0 * cq
            return {'shape': 'col_edge', 'u0': u0, 'u1': u0 + 2.0 * PI * d,
                    'A': cp * cq + 2.0 * d * cp + 4.0 * d * cq + 2.0 * PI * d * d,
                    'sk': 1.0 / PI, 'flags': flags}
        if cls == 'corner':
            q1, q2 = min(a1, 1.5 * d), min(a2, 1.5 * d)
            u0 = q1 + q2
            return {'shape': 'col_corner', 'u0': u0, 'u1': u0 + PI * d,
                    'A': q1 * q2 + 2.0 * d * (q1 + q2) + PI * d * d, 'sk': 2.0 / PI, 'flags': flags}
        if rnd:
            D = a1
            return {'shape': 'round_int', 'u0': PI * D, 'u1': PI * (D + 4.0 * d),
                    'A': PI * (D + 4.0 * d) ** 2 / 4.0, 'sk': None, 'D': D, 'flags': flags}
        a, b = max(a1, a2), min(a1, a2)
        a_ = min(a, 3.0 * d)
        u0 = 2.0 * a_ + 2.0 * b
        return {'shape': 'col_int', 'u0': u0, 'u1': u0 + 4.0 * PI * d,
                'A': a_ * b + 4.0 * d * (a_ + b) + 4.0 * PI * d * d, 'sk': 1.0 / (2.0 * PI), 'flags': flags}
    if kind == 'wall_end':
        B = (t or 0.0) / 1000.0
        u0 = B + 3.0 * d
        return {'shape': 'wall_end', 'u0': u0, 'u1': u0 + 2.0 * PI * d,
                'A': 6.0 * d * d + 2.0 * B * d + 2.0 * PI * d * d, 'sk': 1.0 / PI, 'flags': flags}
    if kind == 'wall_L':
        u0 = 3.0 * d
        return {'shape': 'wall_L', 'u0': u0, 'u1': u0 + PI * d, 'A': 6.0 * d * d + PI * d * d,
                'sk': 2.0 / PI, 'flags': flags}
    return None


def rho_top(dm, inp):
    """ρ = (As1 + As2) / d, As — мм²/м."""
    As = 0.0
    for dk, sk in (('top_d1', 'top_s1'), ('top_d2', 'top_s2')):
        if inp[dk] > 0 and inp[sk] > 0:
            As += PI / 4.0 * inp[dk] ** 2 * 1000.0 / inp[sk]
    return As / (1000.0 * dm) if dm > 0 else 0.0


def punch(geo, dm, Vd, qd, beta, inp):
    """Проверка одной точки. geo — perim(); dm — мм; Vd — кН; qd — кН/м²; inp — inputs().
    -> dict (кН, м, см²) или None, если нечего проверять."""
    if not geo or not dm or dm <= 0 or Vd is None or not beta:
        return None
    d = dm / 1000.0
    fck, scp = inp['fck'], inp['sigma_cp']
    fc = 0.7 * fck
    K = min(2.0, 1.0 + math.sqrt(200.0 / dm))
    rho = rho_top(dm, inp)
    v_min = 0.035 * K ** 1.5 * math.sqrt(fc) + 0.1 * scp
    v_c = 0.12 * K * (100.0 * rho * fc) ** (1.0 / 3.0) + 0.1 * scp
    v = max(v_min, v_c)
    u0, u1, Au1 = geo['u0'], geo['u1'], geo['A']
    VRdc = v * u1 * d * 1000.0
    VRdmax = 0.24 * (1.0 - 0.7 * fck / 250.0) * 0.93 * 0.7 / 1.5 * fck * u0 * d * 1000.0
    Veq = beta * Vd - beta * qd * Au1
    bVd = beta * Vd
    if bVd > VRdmax:
        res = 'thick_max'
    elif Veq > 1.5 * VRdc:
        res = 'thick_c'
    elif VRdc > Veq:
        res = 'ok'
    else:
        res = 'reinf'
    need = Veq > VRdc
    rho_min = 0.005 if need else max(0.0013, 0.28 * 0.3 * fc ** (2.0 / 3.0) / 500.0)
    rho_max = 0.02 if need else 0.04
    out = {'res': res, 'label': RESULT_LABEL[res], 'shape': geo['shape'],
           'u0': u0, 'u1': u1, 'Au1': Au1, 'K': K, 'rho': rho, 'rho_min': rho_min, 'rho_max': rho_max,
           'v_min': v_min, 'v_c': v_c, 'VRdc': VRdc, 'VRdmax': VRdmax, 'Veq': Veq, 'bVd': bVd,
           'eta': Veq / VRdc if VRdc > 0 else None, 'eta_max': bVd / VRdmax if VRdmax > 0 else None,
           'u_out': None, 's_out': None, 'sr': None, 'Asw': None, 'Asa': None, 'Asb': None, 'm': None,
           'warn': list(geo.get('flags') or [])}
    if res == 'reinf' and rho < rho_min:
        out['warn'].append(u'ρ < ρ_min: increase top reinforcement')
    if rho > rho_max:
        out['warn'].append(u'ρ > ρ_max')
    if need:
        out['Asb'] = Veq * 1000.0 / 435.0 / 100.0
        u_out = Veq / (v * d * 1000.0)
        out['u_out'] = u_out
        if geo['shape'] == 'round_int':
            s_out = 0.5 * (u_out / PI - geo['D'])
        else:
            s_out = (u_out - u0) * geo['sk']
        out['s_out'] = s_out
        if Veq <= VRdmax:
            sr = inp['sr'] / 1000.0 if inp['sr'] > 0 else math.floor(0.75 * dm / 10.0) * 10.0 / 1000.0
            fy = min(250.0 + 0.25 * dm, 435.0)
            dV = (Veq - 0.75 * VRdc) * 1000.0
            out['sr'] = sr
            out['Asw'] = dV / (1.5 * (d / sr) * fy * math.sin(math.radians(inp['alpha_w']))) / 100.0
            out['Asa'] = dV / (fy * math.sin(math.radians(inp['alpha_b']))) / 100.0
            m = int(math.ceil((s_out - 2.0 * d) / sr - 1e-9))
            out['m'] = max(m, 2)
            if m < 2:
                out['warn'].append(u'perimeters: min 2 (EC2 9.4.3)')
    return out


def perim_of(pt):
    """Периметры точки из pipeline (kind, cls, dims, dm, edge_axis)."""
    dims = pt.get('dims') or {}
    if pt['kind'] in ('column', 'pylon'):
        return perim(pt['kind'], pt.get('cls'), dims.get('b'), dims.get('h'), dims.get('shape'), None,
                     pt['dm'], pt.get('edge_axis'))
    legs = sorted(dims.get('legs', []), key=lambda g: -g['len'])
    return perim(pt['kind'], None, None, None, None, legs[0]['t'] if legs else None, pt['dm'], None)
