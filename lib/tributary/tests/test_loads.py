# -*- coding: utf-8 -*-
"""Сборные плиты, колонны с балками, режим «нагрузки на опоры»."""
import pytest

from tributary import pipeline, oneway, loads


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def wall(i, p0, p1, t=200.0):
    return {'id': i, 'p0': list(p0), 'p1': list(p1), 't': t}


def col(i, x, y, b=400.0):
    return {'id': i, 'x': x, 'y': y, 'b': b, 'h': b, 'ux': 1.0, 'uy': 0.0, 'shape': 'rect'}


def others_by_id(res):
    return dict((o['ids'][0], o) for o in res['others'])


def test_is_precast():
    he = u'לוחדים'          # לוחדים
    assert oneway.is_precast(u'FL ' + he + u' 30+5')
    assert oneway.is_precast(u'‏' + he)                # с невидимым RLM
    assert oneway.is_precast(u'Slab 20 + 5 cm')
    assert oneway.is_precast(u'HC plank', u'hc')
    assert oneway.is_precast(u'Precast 25', u'PRECAST,HOLLOW')
    assert not oneway.is_precast(u'Slab 250')
    assert not oneway.is_precast(u'C30/37 250', u'PRECAST')
    assert not oneway.is_precast(u'1234+56789')


def test_auto_dir_short_side():
    assert oneway.auto_dir(rect(0, 0, 6000, 10000)) == (1.0, 0.0)
    assert oneway.auto_dir(rect(0, 0, 10000, 6000)) == (0.0, 1.0)


def precast_box(oneway_flag=None, name=u'HC 20+5'):
    sl = {'id': 1, 'name': name, 'h': 250, 'outer': rect(0, 0, 6000, 10000), 'holes': []}
    if oneway_flag is not None:
        sl['oneway'] = oneway_flag
    walls = [wall(1, (0, 0), (0, 10000)), wall(2, (6000, 0), (6000, 10000)),
             wall(3, (0, 0), (6000, 0)), wall(4, (0, 10000), (6000, 10000))]
    return {'slabs': [sl], 'walls': walls}


def test_precast_loads_only_cross_span_walls():
    res = pipeline.run(precast_box(), {'grid_mm': 100, 'mode': 'loads'})
    o = others_by_id(res)
    A = dict((i, o[i]['area'] / 1e6) for i in o)
    assert A[1] == pytest.approx(30.0, rel=0.02) and A[2] == pytest.approx(30.0, rel=0.02)
    assert A[3] < 0.5 and A[4] < 0.5                      # стены вдоль пролёта почти пустые
    assert res['check']['area_none_m2'] == 0.0
    assert any(u'precast' in n for n in res['notes'])


def test_two_way_override_gives_trapezoids():
    res = pipeline.run(precast_box(oneway_flag=False), {'grid_mm': 100, 'mode': 'loads'})
    o = others_by_id(res)
    assert o[3]['area'] / 1e6 == pytest.approx(9.0, rel=0.05)     # треугольник 6×3/2
    assert o[1]['area'] / 1e6 == pytest.approx(21.0, rel=0.05)    # трапеция


def test_precast_span_override():
    d = precast_box()
    d['slabs'][0]['span'] = [0, 1]                        # пролёт вдоль длинной стороны
    o = others_by_id(pipeline.run(d, {'grid_mm': 100, 'mode': 'loads'}))
    assert o[3]['area'] / 1e6 == pytest.approx(30.0, rel=0.02) and o[1]['area'] / 1e6 < 0.5


def frame():
    """Плита 12×6 на 4 колоннах, балки по контуру + второстепенная посередине."""
    cols = [col(1, 0, 0), col(2, 12000, 0), col(3, 12000, 6000), col(4, 0, 6000)]
    beams = [{'id': 11, 'p0': [0, 0], 'p1': [12000, 0], 'b': 300},
             {'id': 12, 'p0': [12000, 0], 'p1': [12000, 6000], 'b': 300},
             {'id': 13, 'p0': [12000, 6000], 'p1': [0, 6000], 'b': 300},
             {'id': 14, 'p0': [0, 6000], 'p1': [0, 0], 'b': 300},
             {'id': 15, 'p0': [6000, 0], 'p1': [6000, 6000], 'b': 300}]
    sl = {'id': 7, 'h': 200, 'outer': rect(-150, -150, 12150, 6150), 'holes': []}
    return {'slabs': [sl], 'columns': cols, 'beams': beams}


def test_columns_with_beams_not_punching_points():
    res = pipeline.run(frame(), {'grid_mm': 100})
    assert not [pt for pt in res['points'] if pt['kind'] == 'column']
    cb = [o for o in res['others'] if o['kind'] == 'column_b']
    assert sorted(o['ids'][0] for o in cb) == [1, 2, 3, 4]
    assert any(u'beams framing in' in n for n in res['notes'])


def test_beam_rests_and_order():
    res = pipeline.run(frame(), {'grid_mm': 100, 'mode': 'loads'})
    bm = [o for o in res['others'] if o['kind'] == 'beam']
    ids = [b['ids'][0] for b in bm]
    sec = bm[ids.index(15)]
    assert ids.index(15) > ids.index(11) and ids.index(15) > ids.index(13)
    assert [r['t'] for r in sec['sup']] == ['b', 'b']
    assert sec['sup'][0]['at'] == pytest.approx(6000.0) and sec['sup'][1]['s'] == pytest.approx(6000.0)
    assert [r['t'] for r in bm[ids.index(11)]['sup']] == ['c', 'c']


def test_resolve_equilibrium_and_reactions():
    res = pipeline.run(frame(), {'grid_mm': 100, 'mode': 'loads'})
    q = {7: 10.0}
    r = loads.resolve(res['points'], res['others'], q)
    area = sum(o['area'] for o in res['points'] + res['others']) / 1e6
    N = sum(c['N'] for c in r['columns'].values())
    assert N == pytest.approx(q[7] * area, rel=1e-9)        # всё дошло до колонн
    assert area == pytest.approx(12.3 * 6.3, rel=0.01)
    # симметрия: все колонны одинаковы
    Ns = sorted(c['N'] for c in r['columns'].values())
    assert Ns[0] == pytest.approx(Ns[-1], rel=0.02)
    b15 = [b for b in r['beams'] if b['ids'] == [15]][0]
    assert b15['R'][0] == pytest.approx(b15['R'][1], rel=0.05)    # ничьи растра на биссектрисах
    assert b15['qmax'] > 0


def test_wall_line_load_profile():
    res = pipeline.run(precast_box(), {'grid_mm': 100, 'mode': 'loads'})
    r = loads.resolve(res['points'], res['others'], {1: 10.0})
    w1 = r['walls'][u'w::1']
    assert w1['W'] == pytest.approx(300.0, rel=0.02)
    assert w1['qmax'] == pytest.approx(30.0, rel=0.02)     # 10 кН/м² × 3 м


def test_profile_has_no_raster_edge_spike():
    """Плита по краям растра: крайний столбец ячеек не должен завышать последний участок эпюры."""
    for x0 in (0.0, 30.0, 50.0, 70.0):
        d = precast_box()
        d['slabs'][0]['outer'] = rect(x0, 0, 6000 + x0, 10000)
        d['slabs'][0]['span'] = [0, 1]
        for w in d['walls']:
            w['p0'][0] += x0
            w['p1'][0] += x0
        res = pipeline.run(d, {'grid_mm': 100, 'mode': 'loads'})
        r = loads.resolve(res['points'], res['others'], {1: 10.0})
        assert r['walls'][u'w::3']['qmax'] == pytest.approx(50.0, rel=0.01), x0


def continuous():
    cols = [col(1, 1000, 0), col(2, 7000, 0), col(3, 13000, 0),
            col(4, 1000, 6000), col(5, 7000, 6000), col(6, 13000, 6000)]
    beams = [{'id': 21, 'p0': [0, 0], 'p1': [14000, 0], 'b': 300},
             {'id': 22, 'p0': [0, 6000], 'p1': [14000, 6000], 'b': 300}]
    return {'slabs': [{'id': 1, 'name': u'D=26.5+7', 'h': 335, 'outer': rect(0, 0, 14000, 6000), 'holes': []}],
            'columns': cols, 'beams': beams}


def test_continuous_beam_over_columns_with_overhangs():
    """Неразрезная балка над тремя колоннами, концы консолями за крайние колонны: опора,
    колонны — не точки продавливания, нагрузка делится по пролётам."""
    res = pipeline.run(continuous(), {'grid_mm': 100, 'mode': 'loads'})
    bm = dict((o['ids'][0], o) for o in res['others'] if o['kind'] == 'beam')
    assert sorted(bm) == [21, 22]
    assert [r['s'] for r in bm[21]['sup']] == [1000.0, 7000.0, 13000.0]
    assert not [p for p in res['points'] if p['kind'] == 'column']
    # сборная плита (26.5+7) пролётом поперёк балок: вся площадь на балки, без опоры — 0
    assert res['check']['area_none_m2'] == 0.0
    r = loads.resolve(res['points'], res['others'], {1: 10.0})
    assert sum(c['N'] for c in r['columns'].values()) == pytest.approx(10.0 * 84.0, rel=0.01)
    N = dict((c['ids'][0], c['N']) for c in r['columns'].values())
    # средняя колонна: половина двух пролётов 6 м × 3 м полосы × 10 = 180; крайняя: 3 + консоль 1 = 4 м × 3 × 10 = 120
    assert N[2] == pytest.approx(180.0, rel=0.02) and N[1] == pytest.approx(120.0, rel=0.02)


def test_precast_auto_span_follows_supports():
    """Опоры только по коротким сторонам (пролёт вдоль длинной): направление выбирается по опорам."""
    d = precast_box()
    d['walls'] = [w for w in d['walls'] if w['id'] in (3, 4)]
    res = pipeline.run(d, {'grid_mm': 100, 'mode': 'loads'})
    assert res['dirs'][0] == (0.0, 1.0)
    assert res['check']['area_none_m2'] == 0.0
