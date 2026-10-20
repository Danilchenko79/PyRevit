# -*- coding: utf-8 -*-
"""engine.js (движок HTML-схемы) обязан считать так же, как Python. Нужен node; без него — skip."""
import json
import math
import os
import shutil
import subprocess

import pytest

from tributary import pipeline, params, check

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'engine.js')
NODE = shutil.which('node')
REAL = os.path.join(os.path.expanduser('~'), 'Documents', 'PEER_Tributary',
                    'KRM-ST-BLD_B-R25_160_MAIN_FL04.json')

pytestmark = pytest.mark.skipif(NODE is None, reason='нет node')

RUNNER = r"""
const E = require(process.argv[1]);
let s = ''; process.stdin.on('data', c => s += c); process.stdin.on('end', () => {
  const inp = JSON.parse(s);
  const opts = {regions: true};
  if (inp.off) opts.off = new Set(inp.off);
  const r = E.run(inp.data, inp.p, opts);
  process.stdout.write(JSON.stringify({points: r.points.map(p => ({key: p.key, n: p.n, cls: p.cls, a: p.areaMm2,
    flags: p.flags, c1: p.c1, c2: p.c2, eax: p.eax, geo: p.geo})), others: r.others.map(o => ({kind: o.kind, ids: o.ids, A: o.A})),
    check: r.check, stats: r.stats, regions: r.regions.length}));
});
"""


def js_run(data, p, off=None):
    inp = json.dumps({'data': data, 'p': p, 'off': off or []})
    out = subprocess.run([NODE, '-e', RUNNER, ENGINE], input=inp.encode('utf-8'),
                         capture_output=True, timeout=120)
    assert out.returncode == 0, out.stderr.decode('utf-8', 'replace')
    return json.loads(out.stdout.decode('utf-8'))


def py_keys(points):
    """Ключи точек как в engine.js: kind:ids, дубликатам (два торца одной стены) — @x,y в 0.1 м."""
    base = [u'{}:{}'.format(q['kind'], u','.join(str(i) for i in q['ids'])) for q in points]
    out = []
    for k, q in zip(base, points):
        if base.count(k) > 1:
            k += u'@{},{}'.format(int(math.floor(round(q['x']) / 100.0 + 0.5)),
                                  int(math.floor(round(q['y']) / 100.0 + 0.5)))
        out.append(k)
    return out


def compare(data, user):
    p = params.merged(user)
    py = pipeline.run(data, user)
    js = js_run(data, p)
    pk = dict(zip(py_keys(py['points']), py['points']))
    jk = dict((q['key'], q) for q in js['points'])
    assert len(pk) == len(py['points']) and len(jk) == len(js['points'])      # ключи уникальны
    assert set(pk) == set(jk)
    for k, q in pk.items():
        assert jk[k]['a'] == pytest.approx(q['area'], rel=1e-9, abs=1e-6), k
        assert jk[k]['n'] == q['n'] and jk[k]['cls'] == q.get('cls') and jk[k]['flags'] == q['flags'], k
        assert jk[k]['eax'] == q.get('edge_axis'), k
        g = check.perim_of(q)
        assert jk[k]['geo']['u1'] == pytest.approx(g['u1'], rel=1e-12) and jk[k]['geo']['A'] == pytest.approx(g['A'], rel=1e-12), k
    assert js['check'] == py['check']
    assert js['stats'] == py['stats']
    assert js['regions'] == len(py['regions'])
    return py, js


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_parity_columns_holes():
    cols = [{'id': 10 * a + b, 'x': x, 'y': y, 'b': 400, 'h': 400, 'ux': 1, 'uy': 0}
            for a, x in enumerate((200.0, 6000.0, 11800.0)) for b, y in enumerate((200.0, 6000.0, 11800.0))]
    data = {'slabs': [{'id': 1, 'h': 250, 'outer': rect(0, 0, 12000, 12000), 'holes': [rect(6400, 5500, 7400, 6500)]}],
            'columns': cols}
    compare(data, {'grid_mm': 100})


def test_parity_walls_beams():
    walls = [{'id': 1, 'p0': [0, 0], 'p1': [8000, 0], 't': 200}, {'id': 2, 'p0': [0, 0], 'p1': [0, 6000], 't': 200},
             {'id': 3, 'p0': [4000, 0], 'p1': [4000, 3000], 't': 250}, {'id': 4, 'p0': [6000, 4000], 'p1': [6800, 4000], 't': 250},
             {'id': 5, 'p0': [8000, 0], 'p1': [8000, 6000], 't': 200}]
    beams = [{'id': 9, 'p0': [0, 6000], 'p1': [8000, 6000], 'b': 300}, {'id': 8, 'p0': [8000, 3000], 'p1': [10000, 3000], 'b': 200}]
    data = {'slabs': [{'id': 1, 'h': 250, 'outer': rect(-2000, -2000, 10000, 8000), 'holes': []},
                      {'id': 2, 'h': 200, 'outer': rect(10000, -2000, 12000, 8000), 'holes': []}],
            'walls': walls, 'beams': beams}
    py, js = compare(data, {'grid_mm': 100})
    # отключение стены в схеме = расчёт без неё
    js2 = js_run(data, params.merged({'grid_mm': 100}), off=['w::3'])
    py2 = pipeline.run(dict(data, walls=[w for w in walls if w['id'] != 3]), {'grid_mm': 100})
    assert sorted(q['key'] for q in js2['points']) == sorted(py_keys(py2['points']))


@pytest.mark.skipif(not os.path.exists(REAL), reason='нет выгрузки FL04')
def test_parity_real_floor():
    with open(REAL) as f:
        data = json.load(f)
    compare(data, {'grid_mm': 150})
