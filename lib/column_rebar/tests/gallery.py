# -*- coding: utf-8 -*-
"""Gallery of column sections: what the program draws and says for each case.

    py -3 lib/column_rebar/tests/gallery.py      ->  lib/column_rebar/tests/out/gallery.html
"""

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from column_rebar import code466, sketch  # noqa: E402
from column_rebar.code466 import RECT, CIRCLE  # noqa: E402

# (title, shape, b, h, cover, bar dia, bars along b, bars along h, overrides)
CASES = [
    (u'Пример из руководства', RECT, 400, 600, 25, 20, 3, 4, {}),
    (u'Стержни близко — шпилька через один', RECT, 600, 600, 25, 16, 5, 5, {}),
    (u'Стержни далеко — шпилька на каждый', RECT, 800, 800, 25, 25, 4, 4, {'transverse': 'ties'}),
    (u'То же, авто: два шпильки → один внутренний хомут', RECT, 800, 800, 25, 25, 4, 4, {}),
    (u'1000×1000: хомуты парами, средний — шпилькой', RECT, 1000, 1000, 25, 20, 7, 7, {}),
    (u'Пилон 1500×600, авто: короткие шпильки + треугольники', RECT, 1500, 600, 25, 20, 7, 3, {}),
    (u'Пилон 1500×600 только шпильками (длинная вдоль)', RECT, 1500, 600, 25, 20, 7, 3, {'transverse': 'ties'}),
    (u'Пилон 1500×600 хомутами парами', RECT, 1500, 600, 25, 20, 7, 3, {'transverse': 'hoops'}),
    (u'Типовая 500×700', RECT, 500, 700, 25, 20, 4, 5, {}),
    (u'Только 4 угловых — мало стержней', RECT, 400, 400, 25, 20, 2, 2, {}),
    (u'Мало арматуры (ρ < 0,4 %)', RECT, 400, 600, 25, 12, 3, 3, {}),
    (u'Пониженный минимум (0,4–0,8 %)', RECT, 300, 300, 25, 12, 2, 2, {}),
    (u'Слишком много стержней — мало в свету', RECT, 300, 300, 25, 25, 5, 5, {}),
    (u'Больше 4 % и мало в свету', RECT, 300, 300, 25, 32, 4, 4, {}),
    (u'Широкая сторона без промежуточных', RECT, 800, 400, 25, 16, 2, 2, {}),
    (u'Это стена, а не колонна', RECT, 200, 1200, 25, 16, 2, 7, {}),
    (u'Хомут тоньше нормы (задан Ø8 при Ø36)', RECT, 600, 600, 25, 36, 4, 4, {'stirrup_dia': 8}),
    (u'Шаг задан больше нормы (300)', RECT, 400, 600, 25, 20, 3, 4, {'spacing': 300}),
    (u'Круглая D500, 8Ø16', CIRCLE, 500, None, 30, 16, 8, None, {}),
    (u'Круглая D1200, 6Ø20 — шаг по дуге велик', CIRCLE, 1200, None, 30, 20, 6, None, {}),
]

CSS = u"""
:root{--bg:#f6f5f2;--card:#fff;--ink:#222;--muted:#666;--line:#ddd}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 'Segoe UI',Arial,sans-serif}
header{padding:20px 24px 8px}h1{font-size:20px;margin:0 0 4px}p.lead{margin:0;color:var(--muted)}
.legend{display:flex;gap:16px;flex-wrap:wrap;padding:8px 24px 16px;color:var(--muted);font-size:13px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:-2px;margin-right:5px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;padding:0 24px 32px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px;display:flex;flex-direction:column;gap:8px}
.card.red{border-left:5px solid #d0302f}.card.yellow{border-left:5px solid #c98a00}.card.ok{border-left:5px solid #2a8a3a}
.card h2{font-size:15px;margin:0}.inp{color:var(--muted);font-size:12px}
.res{font-weight:600}.svg{display:flex;justify-content:center}.svg svg{max-width:100%;height:auto}
ul{margin:0;padding-left:18px}li.red{color:#b02020}li.yellow{color:#8a6000}li small{color:var(--muted)}
.okmsg{color:#2a7a35}
"""


def card(case):
    title, shape, b, h, cover, dia, nb, nh, ov = case
    r = code466.design(shape, b, h, cover, dia, nb, nh, **ov)
    levels = set(x['level'] for x in r['messages'])
    cls = 'red' if code466.RED in levels else ('yellow' if code466.YELLOW in levels else 'ok')
    if shape == CIRCLE:
        inp = u'D%d, слой %d, %d×Ø%d' % (b, cover, nb, dia)
    else:
        inp = u'%d×%d, слой %d, Ø%d, вдоль b %d, вдоль h %d (с угловыми)' % (b, h, cover, dia, nb, nh)
    if ov:
        inp += u'; ' + u', '.join(u'%s=%s' % kv for kv in sorted(ov.items()))
    res = []
    if r['bars']:
        res.append(u'%d×Ø%d' % (len(r['bars']), dia))
    if r['rho'] is not None:
        res.append(u'ρ = %.2f %%' % (r['rho'] * 100))
    if r['label']:
        res.append(u'хомуты ' + r['label'])
    if r['ties']:
        res.append(u'шпилек %d' % len(r['ties']))
    rect = [x for x in r.get('hoops') or [] if x['kind'] == 'rect']
    tri = [x for x in r.get('hoops') or [] if x['kind'] == 'triangle']
    if rect:
        res.append(u'внутр. хомутов %d' % len(rect))
    if tri:
        res.append(u'треугольных %d (угол %d°)' % (len(tri), round(tri[0]['apex_angle'])))
    if r.get('set_length') and shape == RECT:
        alt = []
        for mode, name in ((code466.TIES, u'шпильками'), (code466.HOOPS, u'хомутами'), (code466.AUTO, u'авто')):
            o = dict(ov, transverse=mode)
            alt.append(u'%s %.2f' % (name, code466.design(shape, b, h, cover, dia, nb, nh, **o)['set_length'] / 1000.0))
        res.append(u'<br>поперечка на комплект %.2f м (%s)' % (r['set_length'] / 1000.0, u', '.join(alt)))
    msgs = u''.join(u'<li class="%s">%s <small>(%s)</small></li>' % (x['level'], x['text'], x['clause'])
                    for x in r['messages']) or u'<li class="okmsg">Замечаний нет</li>'
    pic = sketch.svg(r, b, h, cover, dia) if r['stirrup'] else u'<em>сечение не построено</em>'
    return (u'<div class="card %s"><h2>%s</h2><div class="inp">%s</div><div class="svg">%s</div>'
            u'<div class="res">%s</div><ul>%s</ul></div>' % (cls, title, inp, pic, u' · '.join(res), msgs))


def main():
    body = u''.join(card(c) for c in CASES)
    html = (u'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            u'<meta name="viewport" content="width=device-width,initial-scale=1">'
            u'<title>Сечения колонн — проверка</title><style>%s</style></head><body>'
            u'<header><h1>Сечения колонн: что получится при разном армировании</h1>'
            u'<p class="lead">Каждый эскиз нарисован по результату code466.design(); сообщения — те, что увидит '
            u'пользователь (в окне будут на английском).</p></header>'
            u'<div class="legend"><span><i style="background:#111"></i>закреплённый стержень</span>'
            u'<span><i style="background:#9a9a9a"></i>незакреплённый (≤ 150 от закреплённого)</span>'
            u'<span><i style="background:#1f5fbf"></i>хомут</span><span><i style="background:#2a8a3a"></i>шпилька</span><span><i style="background:#8a3fc1"></i>внутренний / треугольный хомут</span>'
            u'<span><i style="background:#d0302f"></i>сторона с ошибкой</span></div>'
            u'<div class="grid">%s</div></body></html>' % (CSS, body))
    out = os.path.join(HERE, 'out')
    if not os.path.isdir(out):
        os.makedirs(out)
    path = os.path.join(out, 'gallery.html')
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(path)


if __name__ == '__main__':
    main()
