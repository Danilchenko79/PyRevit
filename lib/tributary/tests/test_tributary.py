# -*- coding: utf-8 -*-
"""Офлайн-тесты: py -3 -m pytest lib/tributary/tests -q"""
import pytest

from tributary import pipeline, supports, params
from tributary.report import html, write_csv


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def slab(x0, y0, x1, y1, h=250.0, holes=()):
    return {'id': 1, 'h': h, 'outer': rect(x0, y0, x1, y1), 'holes': [rect(*hl) for hl in holes]}


def col(i, x, y, b=400.0, h=400.0):
    return {'id': i, 'x': x, 'y': y, 'b': b, 'h': h, 'ux': 1.0, 'uy': 0.0, 'shape': 'rect'}


def wall(i, p0, p1, t=200.0):
    return {'id': i, 'p0': list(p0), 'p1': list(p1), 't': t}


def by_id(res):
    return dict((pt['ids'][0], pt) for pt in res['points'])


P = {'grid_mm': 100.0, 'q_d': 10.0}


# ------------------------------------------------------------- колонны 3×3

@pytest.fixture(scope='module')
def grid3():
    xs = (200.0, 6000.0, 11800.0)
    cols = [col(10 * a + b, xs[a], xs[b]) for a in range(3) for b in range(3)]
    data = {'slabs': [slab(0, 0, 12000, 12000)], 'columns': cols}
    return pipeline.run(data, P)


def test_grid3_classes(grid3):
    pts = by_id(grid3)
    corner = [0, 2, 20, 22]
    edge = [1, 10, 12, 21]
    for i in corner:
        assert pts[i]['cls'] == 'corner', i
    for i in edge:
        assert pts[i]['cls'] == 'edge', i
    assert pts[11]['cls'] == 'int'


def test_grid3_areas(grid3):
    pts = by_id(grid3)
    exp = {'corner': 3.1 * 3.1, 'edge': 5.8 * 3.1, 'int': 5.8 * 5.8}
    for pt in pts.values():
        a = pt['area'] / 1e6
        assert a == pytest.approx(exp[pt['cls']], rel=0.02), (pt['ids'], a)
    ck = grid3['check']
    assert ck['area_points_m2'] == pytest.approx(144.0, rel=0.01)
    assert ck['area_none_m2'] == 0


def test_grid3_beta_vd(grid3):
    r = [x for x in grid3['rows'] if x['ids'] == u'11'][0]
    assert r['beta'] == 1.15
    assert r['Vd'] == pytest.approx(10.0 * 33.64, rel=0.02)
    assert r['calc'] == u'v6: col-int'
    assert r['dm'] == 213


def test_report_renders(grid3, tmp_path):
    import json, re
    s = html(grid3)
    blob = re.search(r'<script type="application/json" id="data">(.*?)</script>', s, re.S).group(1)
    d = json.loads(blob)
    assert len(d['data']['columns']) == 9 and '__DATA__' not in s and '__ENGINE__' not in s
    assert 'TribEngine' in s and d['params']['grid_mm'] == 100.0
    p = write_csv(grid3, str(tmp_path / 'r.csv'))
    lines = open(p, encoding='utf-8-sig').read().splitlines()
    assert len(lines) == 10


# ------------------------------------------------------------- топология стен

def _topo(walls, cols=()):
    p = params.merged()
    return supports.build(walls, list(cols), [], p, lambda x, y: 213.0)


def kinds(topo):
    out = {}
    for pt in topo['points']:
        out[pt['kind']] = out.get(pt['kind'], 0) + 1
    return out


def test_L_corner_and_ends():
    t = _topo([wall(1, (0, 0), (5000, 0)), wall(2, (0, 0), (0, 4000))])
    assert kinds(t) == {'wall_L': 1, 'wall_end': 2}
    L = [p for p in t['points'] if p['kind'] == 'wall_L'][0]
    assert (L['x'], L['y']) == pytest.approx((0, 0), abs=1)
    legs = sorted(g['len'] for g in L['dims']['legs'])
    assert legs == pytest.approx([4000, 5000], abs=1)
    assert L['dims']['angle'] == pytest.approx(90, abs=0.1)


def test_L_corner_face_located_walls():
    # оси не сходятся в точку (привязка по грани): конец одной стены на 100 мм не доходит
    t = _topo([wall(1, (100, 0), (5000, 0)), wall(2, (0, -100), (0, 4000))])
    assert kinds(t) == {'wall_L': 1, 'wall_end': 2}


def test_T_junction():
    # узел T — только вогнутые углы: в точки продавливания не идёт, полки остаются стеной
    t = _topo([wall(1, (0, 0), (6000, 0)), wall(2, (3000, 0), (3000, 4000))])
    assert kinds(t) == {'wall_end': 3}
    assert t['stats']['nodes']['wall_T'] == 1


def test_X_crossing_mid_mid():
    t = _topo([wall(1, (0, 0), (6000, 0)), wall(2, (3000, -3000), (3000, 3000))])
    assert kinds(t) == {'wall_end': 4}
    assert t['stats']['nodes']['wall_X'] == 1


def test_X_from_two_ends_and_passing():
    t = _topo([wall(1, (0, 0), (6000, 0)), wall(2, (3000, 0), (3000, 3000)),
               wall(3, (3000, 0), (3000, -3000))])
    assert t['stats']['nodes']['wall_X'] == 1


def test_continuation_is_not_node():
    t = _topo([wall(1, (0, 0), (3000, 0)), wall(2, (3000, 0), (6000, 0))])
    assert kinds(t) == {'wall_end': 2}
    assert t['stats']['nodes'].get('cont') == 1


def test_pylon_and_parallel_neighbours():
    t = _topo([wall(1, (0, 0), (800, 0), t=250), wall(2, (0, 1000), (5000, 1000)),
               wall(3, (0, 1300), (5000, 1300))])
    k = kinds(t)
    assert k['pylon'] == 1
    assert k['wall_end'] == 4          # параллельные стены рядом — не продолжение


def test_wall_end_at_column_is_join():
    t = _topo([wall(1, (200, 0), (5000, 0))], cols=[col(99, 0, 0)])
    k = kinds(t)
    assert k == {'column': 1, 'wall_end': 1}
    c = [p for p in t['points'] if p['kind'] == 'column'][0]
    assert u'wall attached' in c['flags']


def test_short_legs_zones_do_not_overlap():
    # U-образная стена с короткой перемычкой 500 мм: зоны двух углов делят перемычку пополам
    t = _topo([wall(1, (0, 0), (0, 3000)), wall(2, (0, 0), (500, 0)), wall(3, (500, 0), (500, 3000))])
    Ls = [p for p in t['points'] if p['kind'] == 'wall_L']
    assert len(Ls) == 2
    assert all(u'short leg' in p['flags'] for p in Ls)


# ------------------------------------------------------------- проёмы и стыки плит

def test_hole_near_column_is_edge_and_area_excludes_hole():
    data = {'slabs': [slab(0, 0, 12000, 12000, holes=[(6400, 5500, 7400, 6500)])],
            'columns': [col(1, 6000, 6000)]}
    res = pipeline.run(data, P)
    pt = res['points'][0]
    assert pt['cls'] == 'edge'
    assert u'edge = opening' in pt['flags']
    assert pt['area'] / 1e6 == pytest.approx(144.0 - 1.0, rel=0.01)


def test_area_not_taken_across_shaft():
    # шахта-щель x 5900..6100, y 0..5000. Биссектриса по прямой — x = 5000, но полоса
    # 5000..5900 под щелью закрыта от колонны 2 щелью -> достаётся колонне 1 (~34.5 м², а не 30)
    data = {'slabs': [slab(0, 0, 12000, 6000, holes=[(5900, 0, 6100, 5000)])],
            'columns': [col(1, 3000, 3000), col(2, 7000, 3000)]}
    res = pipeline.run(data, P)
    a = by_id(res)
    total = 72.0 - 0.2 * 5.0
    assert (a[1]['area'] + a[2]['area']) / 1e6 == pytest.approx(total, rel=0.01)
    assert a[1]['area'] / 1e6 == pytest.approx(34.5, rel=0.03)
    assert res['check']['area_none_m2'] == 0


def test_hidden_pocket_gets_assigned():
    # L-плита: колонна только в нижнем крыле; верхнее крыло за входящим углом — не «без опоры»
    data = {'slabs': [{'id': 1, 'h': 250.0, 'holes': [],
                       'outer': [[0, 0], [8000, 0], [8000, 3000], [3000, 3000], [3000, 8000], [0, 8000]]}],
            'columns': [col(1, 7000, 1500)]}
    res = pipeline.run(data, P)
    assert res['check']['area_none_m2'] == 0
    assert res['points'][0]['area'] / 1e6 == pytest.approx(8 * 3 + 3 * 5, rel=0.01)


def test_wall_outside_slab_edge_takes_area():
    # стена снаружи контура: край плиты y=0 по внутренней грани стены (−250..0). Растр 150 лёг так,
    # что первый центр ячейки в 125 от грани — при затравке 0.75·s стена не забирала ничего
    data = {'slabs': [{'id': 1, 'h': 300.0, 'holes': [],
                       'outer': [[0, -250], [1000, -250], [1000, 0], [12000, 0], [12000, 6000], [0, 6000]]}],
            'walls': [wall(5, (3000, -125), (12000, -125), t=250.0)],
            'columns': [col(1, 7500, 5000)]}
    res = pipeline.run(data, {'grid_mm': 150.0})
    a_wall = (sum(pt['area'] for pt in res['points'] if 5 in pt['ids']) +
              sum(ot['area'] for ot in res['others'] if 5 in ot['ids']))
    assert a_wall / 1e6 > 15.0


def test_two_slabs_joint_no_false_edge():
    data = {'slabs': [slab(0, 0, 6000, 6000, h=250), slab(6001, 0, 12000, 6000, h=200)],
            'columns': [col(1, 6000, 3000)]}
    res = pipeline.run(data, P)
    pt = res['points'][0]
    assert pt['cls'] == 'int', pt['flags']
    assert res['check']['area_none_m2'] == 0


def test_params_validation():
    with pytest.raises(ValueError):
        params.merged({'grid_mm': 5})
    p = params.merged({'k_zone': '2', 'beta': {'wall_end': 1.3}})
    assert p['k_zone'] == 2.0 and p['beta']['wall_end'] == 1.3 and p['beta']['wall_L'] == 1.5


def test_raster_area_corrected_to_polygon():
    # край плиты на 50 мм сдвинут относительно сетки — без поправки ошибка до целого ряда ячеек
    data = {'slabs': [slab(0, 0, 15030, 3030)], 'columns': [col(1, 7500, 1500)]}
    res = pipeline.run(dict(data), {'grid_mm': 100.0})
    assert res['points'][0]['area'] / 1e6 == pytest.approx(15.03 * 3.03, rel=0.001)


def test_multipart_slab_pieces_are_not_holes():
    # один Floor из трёх кусков приходит тремя записями с одним id
    parts = [dict(slab(0, 0, 3000, 3000), id=5), dict(slab(10000, 0, 13000, 3000), id=5),
             dict(slab(20000, 0, 23000, 3000), id=5)]
    cols = [col(1, 1500, 1500), col(2, 11500, 1500), col(3, 21500, 1500)]
    res = pipeline.run({'slabs': parts, 'columns': cols}, P)
    assert res['check']['area_poly_m2'] == pytest.approx(27.0, rel=0.001)
    for pt in res['points']:
        assert pt['area'] / 1e6 == pytest.approx(9.0, rel=0.001)


def test_split_loops_disjoint_and_nested():
    from tributary.geom import split_loops
    big = rect(0, 0, 10000, 10000)
    hole = rect(4000, 4000, 6000, 6000)
    island = rect(4500, 4500, 5500, 5500)      # кусок плиты внутри проёма
    far = rect(20000, 0, 23000, 3000)          # отдельный кусок (как балкон 874319)
    parts = split_loops([hole, far, big, island])
    outers = sorted(len(h) for _o, h in parts)
    assert len(parts) == 3 and outers == [0, 0, 1]


def test_beams_need_support_at_both_ends():
    walls = [wall(1, (0, 0), (0, 6000)), wall(2, (8000, 0), (8000, 6000))]
    beams = [{'id': 10, 'p0': [0, 3000], 'p1': [8000, 3000], 'b': 300},            # на двух стенах
             # бортик консоли: П-образные балки, опёрты только двумя концами на стену 2
             {'id': 11, 'p0': [8000, 0], 'p1': [10000, 0], 'b': 200},
             {'id': 12, 'p0': [10000, 0], 'p1': [10000, 6000], 'b': 200},
             {'id': 13, 'p0': [10000, 6000], 'p1': [8000, 6000], 'b': 200},
             # второстепенная балка на главной
             {'id': 14, 'p0': [4000, 3000], 'p1': [4000, 6000], 'b': 250}]
    notes = []
    from tributary.supports import _supported_beams, _Wall
    W = [_Wall(i, w) for i, w in enumerate(walls)]
    got = sorted(b['id'] for b in _supported_beams(beams, W, [], notes))
    assert got == [10]          # 14 опирается на 10 одним концом, второй конец свободен
    beams[4]['p1'] = [4000, 6000]
    walls.append(wall(3, (0, 6000), (8000, 6000)))
    W = [_Wall(i, w) for i, w in enumerate(walls)]
    got = sorted(b['id'] for b in _supported_beams(beams, W, [], []))
    assert got == [10, 14]      # 14 теперь на главной балке и на стене 3; бортик 11-13 — нет



def test_concave_L_corner_is_not_a_punching_point():
    # угол здания: плита только внутри L (0..6000 x 0..6000) — снаружи угла плиты нет
    walls = [wall(1, (0, 0), (6000, 0)), wall(2, (0, 0), (0, 6000))]
    res = pipeline.run({'slabs': [slab(-120, -120, 6000, 6000)], 'walls': walls}, P)
    assert 'wall_L' not in res['counts']
    assert res['stats']['nodes']['wall_L_in'] == 1
    # тот же угол внутри большой плиты — выпуклая сторона нагружена
    res = pipeline.run({'slabs': [slab(-6000, -6000, 6000, 6000)], 'walls': walls}, P)
    assert res['counts'].get('wall_L') == 1


def test_wall_end_at_slab_edge_flagged():
    res = pipeline.run({'slabs': [slab(0, -3000, 6000, 3000)],
                        'walls': [wall(1, (0, 0), (4000, 0))]}, P)
    ends = sorted((p['x'], p['flags']) for p in res['points'] if p['kind'] == 'wall_end')
    assert u'wall end at slab edge' in ends[0][1] and u'wall end at slab edge' not in ends[1][1]


def test_area_by_floor_and_regions():
    from tributary.vector import ring_area
    data = {'slabs': [dict(slab(0, 0, 6000, 6000, h=250), id=1), dict(slab(6000, 0, 12000, 6000, h=200), id=2)],
            'columns': [col(1, 3000, 3000), col(2, 9000, 3000)]}
    res = pipeline.run(data, P)
    a = by_id(res)
    assert a[1]['area_by_floor'][1] / 1e6 == pytest.approx(36.0, rel=0.01)
    assert a[2]['area_by_floor'][2] / 1e6 == pytest.approx(36.0, rel=0.01)
    # векторные зоны: одна на колонну, площадь колец ~ площади зоны + «разлив» за край (pad)
    regs = dict((r['n'], r) for r in res['regions'] if r['type'] == 'point')
    for n, pt in ((p['n'], p) for p in res['points']):
        ra = sum(ring_area(r) for r in regs[n]['rings']) / 1e6
        assert ra == pytest.approx(pt['area'] / 1e6, rel=0.12)
