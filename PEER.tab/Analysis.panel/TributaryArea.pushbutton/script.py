# -*- coding: utf-8 -*-
__title__  = 'Tributary\nAreas'
__author__ = 'Dima'
__doc__    = u"""Version = 1.4
Date      = 2026-10-07
Description: Tributary areas and punching points of the slab on a level, with the
             punching check by the company sheet (SI 466.1 amend. 7).
             The model is not changed. All work is done in the interactive plan
             that opens in the browser: loads, slab thickness, supports on/off,
             result and required thickness per point.
How-To:
    1. (optional) select slabs - only they are used.
    2. Run the button and pick a level - the plan opens in the browser.
    3. Slabs & loads tab: enter g, q and, if needed, the slab thickness.
    4. Click a point on the plan: its check, required thickness, factors.
    Shift+click - starting settings (zones, cover, bars, fck).
    Files go to Documents\\PEER_Tributary.
"""
import os
import sys
# lib/ is on sys.path only after a pyRevit reload; make the button self-sufficient
_here = os.path.dirname(__file__)
while _here and not _here.lower().endswith('.extension'):
    _parent = os.path.dirname(_here)
    if _parent == _here:
        break
    _here = _parent
_lib = os.path.join(_here, 'lib')
if os.path.isdir(_lib) and _lib not in sys.path:
    sys.path.append(_lib)

import datetime
from Autodesk.Revit.DB import FilteredElementCollector, Level, Floor, ViewPlan
from pyrevit import forms, script

from tributary import params as P
from tributary import collect as C
from tributary import pipeline, report

try:
    from peer_log import RunLog
except Exception:
    RunLog = None

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()
CFG_SECTION = 'TributaryArea'
CFG_KEYS = ('k_zone', 'c_nom', 'bar_d', 'edge_k', 'grid_mm', 'pylon_ratio', 'use_beams',
            'fck', 'top_d1', 'top_s1', 'top_d2', 'top_s2')
BUTTON_GRID = 150.0


def load_params():
    cfg = script.get_config(CFG_SECTION)
    user = {'grid_mm': BUTTON_GRID}
    for k in CFG_KEYS:
        # get_option(k, None) в pyRevit 5.2 бросает ошибку, если опции нет (None = «без умолчания»)
        if not cfg.has_option(k):
            continue
        v = cfg.get_option(k)
        if v not in (None, ''):
            user[k] = v
    return user


def pick_level():
    levels = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(),
                    key=lambda l: l.Elevation)
    av = doc.ActiveView
    cur = av.GenLevel if isinstance(av, ViewPlan) else None
    names = [l.Name for l in levels]
    if cur is not None and cur.Name in names:
        names.remove(cur.Name)
        names.insert(0, cur.Name)
    name = forms.SelectFromList.show(names, title=u'Tributary areas — pick a level (current first)',
                                     multiselect=False, button_name=u'Select')
    if not name:
        return None
    return [l for l in levels if l.Name == name][0]


def selected_floor_ids():
    ids = []
    for i in uidoc.Selection.GetElementIds():
        if isinstance(doc.GetElement(i), Floor):
            ids.append(i)
    return ids or None


def main():
    log = RunLog('TributaryArea') if RunLog else None
    level = pick_level()
    if level is None:
        return
    p = P.merged(load_params())
    floor_ids = selected_floor_ids()

    data = C.collect(doc, level, p, floor_ids)
    if not data['slabs']:
        forms.alert(u'Level "{}" has no structural slabs.'.format(level.Name))
        if log:
            log.skipped(level.Name, u'no structural slabs')
            log.finish(summary=u'no slabs')
        return
    res = pipeline.run(data, p, with_regions=False)     # зоны рисует сама схема (engine.js)

    out_dir = report.default_out_dir()
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    stem = u'{}_{}_{}'.format(report.safe_name(doc.Title), report.safe_name(level.Name),
                              datetime.datetime.now().strftime('%Y%m%d_%H%M'))
    csv_path = report.write_csv(res, os.path.join(out_dir, stem + u'.csv'))
    html_path = report.write_html(res, os.path.join(out_dir, stem + u'.html'),
                                  u'Tributary areas — {}'.format(level.Name))

    ck = res['check']
    # вся работа — в схеме (там же сводка, замечания и таблица); окно pyRevit не открываем
    try:
        os.startfile(html_path)
    except Exception as e:
        output.print_md(u'Could not open the plan automatically: {}'.format(e))
        output.print_md(u'Plan: `{}`  \nCSV: `{}`'.format(html_path, csv_path))

    if log:
        for r in res['rows']:
            log.processed(u'#{} {} {}'.format(r['n'], r['kind'], r['ids']),
                          u'A={} m² {}'.format(r['A'], r['cls'] or u''))
        for pt in res['dropped']:
            log.skipped(u'{} {}'.format(pt['kind'], pt['ids']), u'outside the slab')
        for s in data['skipped']:
            log.skipped(u'{} {}'.format(s.get('what'), s.get('id')), s.get('reason'))
        log.finish(summary=u'{}: {} punching points, slab area {} m², unsupported {} m²'.format(
            level.Name, len(res['rows']), ck['area_poly_m2'], ck['area_none_m2']))


if __name__ == '__main__':
    main()
