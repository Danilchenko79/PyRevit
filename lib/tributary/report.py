# -*- coding: utf-8 -*-
"""CSV и интерактивная HTML-схема по результату pipeline.run.
Без зависимостей (IronPython 2.7 / CPython 3). Шаблон страницы — report_template.html рядом."""
import datetime
import io
import json
import os

from tributary.punching import COLUMNS

try:
    text_type = unicode  # noqa: F821  (IronPython 2.7)
except NameError:
    text_type = str

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'report_template.html')


def default_out_dir():
    """Папка результатов: Документы\\PEER_Tributary (одна и для кнопки, и для скилла)."""
    return os.path.join(os.path.expanduser('~'), 'Documents', 'PEER_Tributary')


def safe_name(s):
    out = []
    for ch in text_type(s):
        out.append(ch if (ch.isalnum() or ch in u'-_.') and ord(ch) < 128 else u'_')
    return u''.join(out).strip(u'_') or u'x'


def _u(v):
    if v is None:
        return u''
    if isinstance(v, float):
        return u'{:g}'.format(v)
    return text_type(v)


def _q(s):
    return u'"{}"'.format(s.replace(u'"', u'""'))


def write_csv(res, path):
    """',' и точка в числах (английская локаль Excel), utf-8 с BOM.
    BOM пишется вручную и файл — одним write: в IronPython 'utf-8-sig' ставит BOM на каждый write."""
    lines = [u','.join(_q(c[0]) for c in COLUMNS)]
    for r in res['rows']:
        cells = []
        for _t, k in COLUMNS:
            v = r.get(k)
            s = _u(v)
            if isinstance(v, text_type) or ',' in s or '"' in s:
                s = _q(s)
            cells.append(s)
        lines.append(u','.join(cells))
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(u'﻿' + u'\n'.join(lines) + u'\n')
    return path


# ------------------------------------------------------------------ HTML
# Схема считает сама (engine.js — порт этого же пакета): в страницу кладутся исходные данные
# уровня и параметры, поэтому в ней можно отключать опоры и менять параметры с пересчётом.

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'engine.js')


def _i(v):
    return int(round(v))


def _pts(loop):
    return [[round(q[0], 1), round(q[1], 1)] for q in loop]


def html_data(res, title):
    data = res['data']
    p = res['params']
    m = res['meta']
    lvl = m.get('level') or {}
    keep = ('id', 'link', 'name')
    walls = [dict([(k, w.get(k)) for k in keep] + [('p0', _pts([w['p0']])[0]), ('p1', _pts([w['p1']])[0]),
                                                    ('t', w['t'])]) for w in data.get('walls', [])]
    cols = [dict([(k, c.get(k)) for k in keep + ('x', 'y', 'b', 'h', 'ux', 'uy', 'shape')]) for c in data.get('columns', [])]
    beams = [dict([(k, b.get(k)) for k in keep] + [('p0', _pts([b['p0']])[0]), ('p1', _pts([b['p1']])[0]),
                                                    ('b', b.get('b') or 200.0)]) for b in data.get('beams', [])]
    slabs = [{'id': sl.get('id'), 'name': sl.get('name') or u'', 'h': sl['h'], 'outer': _pts(sl['outer']),
              'holes': [_pts(hl) for hl in sl.get('holes', [])]} for sl in data['slabs']]
    return {
        'title': title,
        'meta': {'doc': m.get('doc_title'), 'level': lvl.get('name'), 'level_id': lvl.get('id'),
                 'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')},
        'params': p,
        'defaults': {'g_add': p.get('g_add', 0.0), 'q_live': p.get('q_live', 0.0),
                     'gamma_g': p.get('gamma_g', 1.4), 'gamma_q': p.get('gamma_q', 1.6)},
        'data': {'slabs': slabs, 'walls': walls, 'columns': cols, 'beams': beams},
    }


def html(res, title=u'Tributary areas'):
    with io.open(TEMPLATE, encoding='utf-8') as f:
        tpl = f.read()
    with io.open(ENGINE, encoding='utf-8') as f:
        eng = f.read()
    blob = json.dumps(html_data(res, title), ensure_ascii=True, separators=(',', ':'))
    blob = blob.replace('</', '<\\/')            # «</» внутри <script> закрыл бы тег
    t = (title.replace(u'&', u'&amp;').replace(u'<', u'&lt;'))
    return (tpl.replace(u'/*__ENGINE__*/', eng.replace(u'</script', u'<\\/script'))
            .replace(u'__TITLE__', t).replace(u'__DATA__', text_type(blob)))


def write_html(res, path, title=u'Tributary areas'):
    text = html(res, title)
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def summary(res):
    """Короткая сводка (dict, JSON-совместимый) — для лога и ответа в чат."""
    return {'level': (res['meta'].get('level') or {}).get('name'), 'counts': res['counts'],
            'check': res['check'], 'notes': res['notes'][:20], 'stats': res['stats'],
            'seconds': res['meta'].get('seconds')}


def write_json(res, path):
    out = {'meta': res['meta'], 'params': res['params'], 'check': res['check'],
           'notes': res['notes'], 'counts': res['counts'], 'rows': res['rows']}
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(text_type(json.dumps(out, ensure_ascii=False, indent=1)))
    return path
