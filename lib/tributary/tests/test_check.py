# -*- coding: utf-8 -*-
"""check.py против Excel компании «חישוב חדירה» (значения, сохранённые в файле) и формул листа «sheet»."""
import json
import math
import os
import shutil
import subprocess

import pytest

from tributary import check as C

T = 10.0   # кН в тонне (в Excel 1 МПа = 100 т/м²)


def test_excel_cached_example():
    # Пример из файла: fck 50, dm 1 м, 600×600, Vd 795 т, β 1.15, q 2.6 т/м², Ø22@10 + Ø16@10 см, sr 0.2, α 90/45.
    # Периметры в файле — «יסוד» (u1 на 1d), подставляем их как есть: проверяются формулы после периметров.
    geo = {'shape': 'col_int', 'u0': 2.4, 'u1': 8.684, 'A': 5.902, 'sk': 1.0 / (2 * math.pi), 'flags': []}
    inp = C.inputs({'fck': 50, 'top_d1': 22, 'top_s1': 100, 'top_d2': 16, 'top_s2': 100, 'sr': 200})
    r = C.punch(geo, 1000.0, 795 * T, 2.6 * T, 1.15, inp)
    assert r['K'] == pytest.approx(1.4472135954999579)
    assert r['rho'] == pytest.approx(0.005811946409141119)
    assert r['Veq'] / T == pytest.approx(896.6030199999999)
    assert r['VRdc'] / T == pytest.approx(411.683609276728)
    assert r['VRdmax'] / T == pytest.approx(1074.9311999999998)
    assert r['u_out'] == pytest.approx(18.91282637984815)
    assert r['s_out'] == pytest.approx(2.627757221490794, rel=2e-4)   # в Excel π = 3.142
    assert r['Asw'] == pytest.approx(18.01809388635874)
    assert r['Asa'] == pytest.approx(191.11074556650212)
    assert r['Asb'] == pytest.approx(206.11563678160917)
    assert r['m'] == 4
    assert r['res'] == 'thick_c'           # Excel: «יש להגדיל עובי פלטה - Veq>1.5*VRdc»
    assert r['rho_min'] == 0.005           # плита; в файле 0.002 — фундамент


def excel_slab(kind, a, b, dm):
    """Лист «sheet», строки «תקרה …» — дословно (π = 3.142 там, где так в Excel)."""
    K4 = dm
    if kind == 'rect':
        K5 = min(a / 2, 1.5 * dm) * 2
        K6 = b
        u0 = 2 * K5 + 2 * K6
        return u0, u0 + 4 * 3.142 * K4, K4 * 4 * (K5 + K6 + 3.142 * K4 + K5 * K6 / (K4 * 4))
    if kind == 'round':
        return 3.142 * a, (a + 4 * K4) * math.pi, (a + 4 * K4) ** 2 * math.pi / 4
    if kind == 'end':
        u0 = 3 * K4 + a
        return u0, u0 + 3.142 * K4 * 2, 6 * K4 * K4 + a * K4 * 2 + 3.142 * K4 * K4 * 2
    u0 = 3 * K4
    return u0, u0 + 3.142 * K4, 6 * K4 * K4 + 3.142 * K4 * K4


@pytest.mark.parametrize('a,b,dm', [(0.6, 0.4, 0.2), (1.5, 0.25, 0.17), (0.3, 0.3, 0.25)])
def test_perim_column_int(a, b, dm):
    g = C.perim('column', 'int', b * 1000, a * 1000, 'rect', None, dm * 1000)
    e = excel_slab('rect', a, b, dm)
    assert (g['u0'], g['u1'], g['A']) == pytest.approx(e, rel=2e-4)


def test_perim_round_end_corner():
    g = C.perim('column', 'int', 500, 500, 'round', None, 200)
    assert (g['u0'], g['u1'], g['A']) == pytest.approx(excel_slab('round', 0.5, 0, 0.2), rel=2e-4)
    g = C.perim('wall_end', None, 3000, None, None, 250, 190)
    assert (g['u0'], g['u1'], g['A']) == pytest.approx(excel_slab('end', 0.25, 0, 0.19), rel=2e-4)
    g = C.perim('wall_L', None, 3000, 2000, None, 250, 190)
    assert (g['u0'], g['u1'], g['A']) == pytest.approx(excel_slab('L', 0, 0, 0.19), rel=2e-4)


def test_perim_edge_corner_columns():
    d = 200.0
    # крайняя: грань у края по оси u -> c⊥ = c1 (b), c∥ = c2 (h)
    g = C.perim('column', 'edge', 400, 600, 'rect', None, d, 'u')
    cp, cq, dd = 0.6, 0.3, 0.2                  # c∥' = min(0.6, 3d) = 0.6, c⊥' = min(0.4, 1.5d) = 0.3
    assert g['u0'] == pytest.approx(cp + 2 * cq)
    assert g['u1'] == pytest.approx(cp + 2 * cq + 2 * math.pi * dd)
    assert g['A'] == pytest.approx(cp * cq + 2 * dd * cp + 4 * dd * cq + 2 * math.pi * dd * dd)
    g2 = C.perim('column', 'edge', 400, 600, 'rect', None, d, 'v')
    assert g2['u0'] == pytest.approx(0.4 + 2 * 0.3)
    # угловая с большими сторонами = угол стены по u0/u1 (обе полки 1.5d)
    gc = C.perim('column', 'corner', 800, 900, 'rect', None, d)
    gl = C.perim('wall_L', None, 3000, 3000, None, 200, d)
    assert gc['u0'] == pytest.approx(gl['u0']) and gc['u1'] == pytest.approx(gl['u1'])
    assert gc['A'] == pytest.approx(gl['A'] + (1.5 * 0.2) ** 2)
    gr = C.perim('column', 'edge', 500, 500, 'round', None, d, 'u')
    assert gr['flags']


def test_results_and_defaults():
    inp = C.inputs({'bar_d': 14})
    assert inp['top_d1'] == 14 and inp['fck'] == 30
    geo = C.perim('column', 'int', 400, 400, 'rect', None, 200)
    assert C.punch(geo, 200, 100.0, 10.0, 1.15, inp)['res'] == 'ok'
    r = C.punch(geo, 200, 450.0, 10.0, 1.15, inp)
    assert r['res'] == 'reinf' and r['Asw'] > 0 and r['m'] >= 2 and r['sr'] == pytest.approx(0.15)
    assert C.punch(geo, 200, 900.0, 10.0, 1.15, inp)['res'] == 'thick_max'
    assert C.punch(geo, 200, 600.0, 10.0, 1.15, inp)['res'] == 'thick_c'
    assert C.punch(geo, 200, None, 10.0, 1.15, inp) is None
    over = C.inputs({'bar_d': 14}, {'fck': 40, 'top_d1': ''})
    assert over['fck'] == 40 and over['top_d1'] == 14


NODE = shutil.which('node')
ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'engine.js')
RUNNER = r"""
const E = require(process.argv[1]);
let s = ''; process.stdin.on('data', c => s += c); process.stdin.on('end', () => {
  const cases = JSON.parse(s);
  process.stdout.write(JSON.stringify(cases.map(c => {
    const g = E.perim(c.kind, c.cls, c.c1, c.c2, c.shape, c.t, c.dm, c.eax);
    return {g: g, r: E.punch(g, c.dm, c.Vd, c.qd, c.beta, E.punchInputs(c.p, c.over))};
  })));
});
"""


@pytest.mark.skipif(NODE is None, reason='нет node')
def test_engine_parity_check():
    cases = []
    for kind, cls, c1, c2, shape, t, eax in [
            ('column', 'int', 400, 600, 'rect', None, None), ('column', 'int', 500, 500, 'round', None, None),
            ('column', 'edge', 400, 900, 'rect', None, 'u'), ('column', 'edge', 400, 900, 'rect', None, 'v'),
            ('column', 'corner', 300, 500, 'rect', None, None), ('column', 'edge', 500, 500, 'round', None, 'u'),
            ('pylon', 'int', 1600, 250, 'rect', None, None), ('wall_end', None, 3000, None, None, 250, None),
            ('wall_L', None, 3000, 2000, None, 200, None)]:
        for Vd in (80.0, 400.0, 900.0, 2500.0):
            cases.append({'kind': kind, 'cls': cls, 'c1': c1, 'c2': c2, 'shape': shape, 't': t, 'eax': eax,
                          'dm': 213.0, 'Vd': Vd, 'qd': 14.5, 'beta': 1.4,
                          'p': {'bar_d': 12, 'fck': 40, 'top_d2': 10, 'top_s2': 150}, 'over': {'sigma_cp': 0.5}})
    out = subprocess.run([NODE, '-e', RUNNER, ENGINE], input=json.dumps(cases).encode('utf-8'),
                         capture_output=True, timeout=60)
    assert out.returncode == 0, out.stderr.decode('utf-8', 'replace')
    js = json.loads(out.stdout.decode('utf-8'))
    for c, j in zip(cases, js):
        g = C.perim(c['kind'], c['cls'], c['c1'], c['c2'], c['shape'], c['t'], c['dm'], c['eax'])
        r = C.punch(g, c['dm'], c['Vd'], c['qd'], c['beta'], C.inputs(c['p'], c['over']))
        for k in ('u0', 'u1', 'A'):
            assert j['g'][k] == pytest.approx(g[k], rel=1e-12), (c, k)
        assert j['g']['flags'] == g['flags']
        for k, v in r.items():
            if isinstance(v, float):
                assert j['r'][k] == pytest.approx(v, rel=1e-12), (c, k)
            else:
                assert j['r'][k] == v, (c, k)
