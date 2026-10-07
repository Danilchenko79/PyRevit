# -*- coding: utf-8 -*-
__title__  = u'Wall\nRebar 2D'
__author__ = 'Dima'
__doc__    = u'''Version = 0.21
Date      = 2026-10-07
Description:
    2D vertical wall reinforcement on the active plan (Detail Items).
    Only walls cut by the view cut plane are taken. A wall is split by openings and
    beams, not by crossing walls: As = b*L/1000 per one end is computed from that
    wall length and placed at the ends of each pier.
    Nodes (L / T / X) get the corner family; a stub up to 15 cm past a crossing wall
    is not an intersection and gets no reinforcement of its own.
    An opening over the whole wall (from a node to the next node or to the wall end)
    means there is no wall on that side: that node is not an intersection there.
    A wall up to 2 m is detailed: inner row, stirrup contour inside the wall (thin
    detail lines) and a stirrup detail beside it.
    Everything runs in stages you tick in the dialog, so each step can be checked on
    its own; an unticked stage is left exactly as it is.
    Before placing anything the script checks that the required families, tag types
    and parameters exist - if something is missing it stops and reports it.
    Floor diameters are set in the dialog, every other rule lives in
    lib/wallrebar2d/settings.py.
How-To:
    1. Open a floor (or ceiling) plan. Walls can be pre-selected - then only those are used.
    2. Press the button and check the settings in the dialog.
    3. "Test run (no changes)" - everything is calculated and placed, then rolled back.
    4. "Run" - placement in a single transaction (one Undo step).
    Families: a family or tag missing in the project is loaded from the .rfa next to
    this script (file name = family name); families already in the project are not touched.
    Settings: %AppData%/WallRebar2D/settings.json
    Report:   %TEMP%/peer_revit_logs/wallrebar2d_report.json
'''

import os as _os
import sys as _sys

_ext = _os.path.dirname(_os.path.abspath(__file__))
while _ext and not _ext.endswith('.extension'):
    _parent = _os.path.dirname(_ext)
    if _parent == _ext:
        break
    _ext = _parent
_lib = _os.path.join(_ext, 'lib')
if _os.path.isdir(_lib) and _lib not in _sys.path:
    _sys.path.append(_lib)
for _m in [m for m in list(_sys.modules) if m.startswith('wallrebar2d')]:
    del _sys.modules[_m]

from Autodesk.Revit.DB import Transaction, TransactionGroup, ViewType, Wall, ElementId
from System.Collections.Generic import List
from pyrevit import script, forms

from peer_log import RunLog
from wallrebar2d import core, store, revit_io
from wallrebar2d.settings import BAR_AREA_CM2 as AREAS
from wallrebar2d.ui import SettingsWindow

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
view = doc.ActiveView
output = script.get_output()

XAML = _os.path.join(_lib, 'wallrebar2d', 'ui.xaml')
# .rfa рядом со script.py: чего нет в проекте — грузится отсюда (имя файла = имя семейства)
BUTTON_DIR = _os.path.dirname(_os.path.abspath(__file__))
PLAN_TYPES = (ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.AreaPlan)


# Кликабельная ссылка на стену в таблицах отчёта. linkify на СОТНЯХ строк рендерится
# минутами и вешает Revit (CLAUDE.md, 17.09) — поэтому строк не больше MAX_ROWS,
# остальное уходит в JSON-отчёт.
MAX_ROWS = 150


def wlink(wid):
    try:
        return output.linkify(ElementId(int(wid)), title=unicode(wid))
    except Exception:
        return unicode(wid)


def cut_rows(rows, title):
    if len(rows) > MAX_ROWS:
        output.print_md(u'_{0}: first {1} of {2} rows shown, the rest is in the JSON report._'
                        .format(title, MAX_ROWS, len(rows)))
    return rows[:MAX_ROWS]


def try_add_missing_params(missing, plan, S, log):
    """Недостающие параметры скрипт добавляет сам: берёт определения из файла общих параметров
    проекта, а чего там нет - создаёт (в своём файле, если проектный недоступен), и привязывает
    к категориям как параметры проекта. Спрашивает один раз; потом проверка гоняется заново."""
    names = revit_io.missing_param_names(missing)
    if not names:
        return missing
    br = chr(10)
    cp = revit_io.central_problem(doc)
    if cp:
        # без доступа к центральной Revit не даст привязать параметры проекта
        msg = (u'These parameters are missing: ' + u', '.join(names) + br + br +
               u'They cannot be added: the central model is not accessible from this computer:' + br +
               u'    ' + cp['central'] + br + br +
               u'This file was opened from:' + br + u'    ' + cp['local'] + br + br +
               u'Close the model, open it again with "Detach from Central" ' +
               u'(Detach and preserve worksets), save it to a project folder and run again.')
        output.print_md(u'**Stopped: the central model is not accessible, project parameters '
                        u'cannot be added.** Central: `{0}`'.format(cp['central']))
        forms.alert(msg, title=u'Wall Rebar 2D: central model not accessible')
        return missing
    st = revit_io.shared_param_status(doc, names)
    cats = revit_io.param_categories(doc, S)
    listed = u', '.join(names)
    from_file = sorted(st['found'])
    to_create = sorted(st['absent'])
    if st['path'] and not st.get('exists'):
        where = (u'The shared parameter file of this project cannot be opened:' + br +
                 u'    ' + st['path'] + br +
                 u'(path does not exist - network drive offline?), so they go into' + br +
                 u'    ' + revit_io.own_spf_path())
    elif not st['path']:
        where = (u'This project has no shared parameter file, so they go into' + br +
                 u'    ' + revit_io.own_spf_path())
    else:
        where = u'Shared parameter file:' + br + u'    ' + st['path']
    msg = u'These parameters are missing:' + br + u'    ' + listed + br + br + where + br + br
    if from_file:
        msg += u'Taken from the file: ' + u', '.join(from_file) + br
    if to_create:
        msg += u'Created by the script: ' + u', '.join(to_create) + br
    msg += (u'Bound as project parameters (instance, text) to: ' +
            u', '.join(c.Name for c in cats) + br + br + u'Do it now?')
    if not forms.alert(msg, title=u'Wall Rebar 2D: add missing parameters', yes=True, no=True):
        output.print_md(u'**Stopped: parameters are missing and were not added.**')
        return missing
    res = revit_io.ensure_and_bind(doc, names, cats, log)
    output.print_md(u'Shared parameter file: `{0}`'.format(res['path']))
    output.print_md(u'Created in the file: **{0}**; bound as project parameters: **{1}**'.format(
        u', '.join(res['created']) if res['created'] else u'none',
        u', '.join(res['added']) if res['added'] else u'none'))
    if res['errors']:
        output.print_table([[a, b] for a, b in res['errors']],
                           columns=[u'Parameter', u'Why it failed'])
    if not res['added']:
        return missing
    return revit_io.preflight(doc, view, S, plan, log)


# ----------------------------------------------------------------------
def print_view_info(info):
    output.print_md(u'### View and View Range')
    output.print_md(
        u'**{0}** ({1}), level **{2}** at {3} mm. '
        u'Level above: {4} / {5} mm. Level below: {6} / {7} mm.'.format(
            info.get('view'), info.get('view_type'), info.get('level'), info.get('level_z'),
            info.get('level_above'), info.get('level_above_z'),
            info.get('level_below'), info.get('level_below_z')))
    if info.get('range_error'):
        output.print_md(u'View Range cannot be read: `{0}`'.format(info['range_error']))
    rows = [[r['plane'], r['level'], r['offset_mm'], r['abs_mm']] for r in info.get('range', [])]
    if rows:
        output.print_table(rows, columns=[u'Plane', u'Level', u'Offset, mm', u'Elevation, mm'])
    output.print_md(u'Cut plane: **{0}** mm. Rule used: **{1}** ({2}).'.format(
        info.get('cut_z'), info.get('rule_used'), info.get('rule_title', u'')))


def print_walls(verdicts):
    rows = []
    for v in sorted(verdicts, key=lambda x: (not x['taken'], x['id'])):
        z = v['z_mm']
        rows.append([wlink(v['id']), v['type'], v['t_cm'],
                     u'{0} … {1}'.format(z[0], z[1]) if z[0] is not None else u'',
                     u'YES' if v['taken'] else u'no', v['reason']])
    output.print_md(u'### Wall selection: {0} of {1} taken'.format(
        len([v for v in verdicts if v['taken']]), len(verdicts)))
    output.print_table(cut_rows(rows, u'Wall selection'),
                       columns=[u'Wall', u'Type', u'b, cm', u'Bottom … top, mm',
                                u'Taken', u'Reason'])


def print_design(results, nodes, S):
    rows = []
    for r in results:
        p = r['pier']
        e = r['edge']
        edge_txt = u'{0}Ø{1}'.format(e['n'], e['dia'])
        if r['single_group']:
            edge_txt = u'single {0}Ø{1}'.format(r['single_per_row'] * e['rows'], e['dia'])
        if r.get('stub'):
            edge_txt = u'stub: corner only'
        if r.get('column'):
            edge_txt = u'column {0}Ø{1}@{2:.0f}'.format(r['column']['n'], r['column']['dia'],
                                                        r['column']['spacing_mm'])
        inner_txt = u'Ø{0}@{1}'.format(r['inner']['dia'], r['inner']['spacing_mm']) if r['inner'] else u''
        rows.append([wlink(p.chain.pieces[0][3]), u'{0:.0f}'.format(p.L / 10),
                     u'{0:.0f}'.format(r.get('L_wall_cm', p.L / 10)), u'{0:.0f}'.format(p.t / 10),
                     u'detailed' if r['short'] else u'plain',
                     u' / '.join(k for k, _ in r['edges']), edge_txt,
                     u'{0:.1f} → {1:.1f}'.format(e['As_req'], e['As_prov']), inner_txt])
    output.print_md(u'### Piers  (As = b·L/1000 per one end, L = WALL length between openings)')
    output.print_table(cut_rows(rows, u'Piers'),
                       columns=[u'Wall', u'Pier, cm', u'Wall L, cm', u'b, cm', u'Type',
                                u'Ends', u'Edge', u'As req → prov', u'Inner'])

    nrows = []
    total_chosen = 0.0
    for nd in nodes:
        d = nd.design
        if not d:
            nrows.append([nd.id, u'', nd.kind, u'', u'', u'no', u'', u''])
            continue
        total_chosen += d['As_prov']
        alts = [o for o in d.get('options', []) if o['ok'] and not (o['n'] == d['n'] and o['dia'] == d['dia'])]
        nxt = u''
        if alts:
            nxt = u'{0}Ø{1} heavier by {2:.0f}%'.format(
                alts[0]['n'], alts[0]['dia'], (alts[0]['As_prov'] / d['As_prov'] - 1) * 100)
        nrows.append([nd.id, wlink(d['from_pier'].chain.pieces[0][3]), nd.kind,
                      u' / '.join(u'{0:.0f}'.format(x) for x in d['leg_L_cm']),
                      u'{0:.2f}'.format(d['As_req']),
                      u'{0}Ø{1}'.format(d['n'], d['dia']),
                      u'{0:.2f} (+{1:.0f}%)'.format(d['As_prov'], (d['As_prov'] / d['As_req'] - 1) * 100),
                      nxt])
    output.print_md(u'### Corners and nodes (lightest option that passes)')
    output.print_table(cut_rows(nrows, u'Nodes'),
                       columns=[u'Node', u'Wall', u'Type', u'Legs, cm', u'As req',
                                u'Bars', u'As prov', u'Next option'])

    edge_As = inner_As = 0.0
    for r in results:
        a = AREAS[r['edge']['dia']]
        if r['single_group']:
            edge_As += r['single_per_row'] * r['edge']['rows'] * a
        else:
            edge_As += r['edge']['n'] * len([k for k, _ in r['edges']
                                             if k in ('start', 'end', 'opening')]) * a
        if r['inner']:
            inner_As += r['inner']['n'] * AREAS[r['inner']['dia']]
    total = total_chosen + edge_As + inner_As
    output.print_md(
        u'**Total vertical reinforcement:** corners {0:.1f} + edges {1:.1f} + inner {2:.1f} = '
        u'**{3:.1f} cm²**, i.e. {4:.1f} kg per metre of storey height.'.format(
            total_chosen, edge_As, inner_As, total, total * 0.785))


def ask_mode(existing):
    """Диалог, когда на виде уже есть армирование."""
    opts = [u'Update: check and fix what changed',
            u'Recreate: delete own elements and place again',
            u'Calculate only, do not touch the model']
    got = forms.CommandSwitchWindow.show(
        opts, message=u'This view already holds {0} elements from this tool'.format(existing))
    if got == opts[0]:
        return 'update'
    if got == opts[1]:
        return 'recreate'
    if got == opts[2]:
        return 'calc'
    return None


# ----------------------------------------------------------------------
def main():
    if view.ViewType not in PLAN_TYPES:
        forms.alert(u'Open a floor plan (or a ceiling plan).')
        return

    S = store.load()
    existing = revit_io.count_existing(doc, view, S)

    win = SettingsWindow(XAML, S, view_name=view.Name, existing=existing,
                         family_names=revit_io.detail_item_families(doc),
                         tag_names=revit_io.tag_families(doc))
    win.show_dialog()
    if win.action == 'cancel':
        return
    S = win.S
    path = store.save(S)
    if win.action == 'save':
        output.print_md(u'Settings saved: {0}'.format(path))
        return
    dry = (win.action == 'dry')

    # Одна группа на весь прогон: загрузка семейств, параметры, расстановка — один Undo;
    # тестовый прогон откатывает и загруженные семейства.
    tg = TransactionGroup(doc, u'Wall Rebar 2D')
    tg.Start()
    try:
        run(S, dry, existing)
    finally:
        if tg.HasStarted() and not tg.HasEnded():
            if dry:
                tg.RollBack()
            else:
                tg.Assimilate()


def run(S, dry, existing):
    log = RunLog('WallRebar2D')
    loaded, _absent, failed = revit_io.load_missing_families(doc, BUTTON_DIR, S, log)
    if loaded:
        output.print_md(u'Loaded from the button folder: **{0}**{1}'.format(
            u', '.join(loaded), u' (test run: rolled back at the end)' if dry else u''))
    for n, why in failed:
        output.print_md(u'Family **{0}** could not be loaded: `{1}`'.format(n, why))
    try:
        syms = revit_io.find_symbols(doc, S)
    except Exception as ex:
        forms.alert(unicode(ex))
        return

    pre = set()
    for eid in uidoc.Selection.GetElementIds():
        if isinstance(doc.GetElement(eid), Wall):
            pre.add(eid.IntegerValue)
    only = pre if pre else None

    walls, openings, columns, verdicts, info = revit_io.read_view(doc, view, S, log, only_ids=only)
    info['preselected'] = sorted(pre)
    print_view_info(info)
    print_walls(verdicts)

    if not walls:
        rep = revit_io.write_report([], view, {}, True,
                                    extra={'walls': verdicts, 'view_info': info,
                                           'piers': [], 'nodes': []})
        output.print_md(u'Report: {0}'.format(rep))
        log.finish(summary=u'no suitable walls')
        forms.alert(u'No wall passed the check.' + chr(10) +
                    u'The output window lists every wall with its elevations and the cut plane.'
                    + chr(10) +
                    u'You can also select walls by hand and run again.')
        return

    if info.get('cut_gaps'):
        output.print_md(u'Walls not cut by the view plane along part of their length (no opening '
                        u'there) - treated as openings: **{0}** - {1}'.format(
                            len(info['cut_gaps']),
                            u', '.join(u'{0} [{1}..{2}]'.format(wlink(w), a, b)
                                       for w, a, b in info['cut_gaps'][:30])))
    chains, nodes = core.build(walls, openings, columns, S)
    results = core.design(chains, nodes, S, AREAS)
    problems = core.check_piers(results, S)
    for x in problems:
        log.error(u'self-check: wall %s [%s] %s' % (x['wall'], x['s0'], x['kind']), x['text'])
    if problems:
        output.print_md(u'### SELF-CHECK: {0} problem(s) found (overlaps, bars outside the wall)'
                        .format(len(problems)))
        output.print_table([[wlink(x['wall']), x['s0'], x['kind'], x['text']]
                            for x in problems[:MAX_ROWS]],
                           columns=[u'Wall', u'Pier start, mm', u'What', u'Details'])
    else:
        output.print_md(u'Self-check: no overlaps, no bars outside walls.')
    if core.DROPPED_STUBS:
        output.print_md(u'Stubs (up to {0} cm past the crossing wall) are not intersections; walls skipped: **{1}** — {2}'
                        .format(S.get('stub_max_cm', 15), len(core.DROPPED_STUBS),
                                u', '.join(wlink(x) for x in core.DROPPED_STUBS[:40])))
    if core.OPEN_LEGS:
        output.print_md(u'Opening over the whole wall - no intersection there; wall legs removed from nodes: **{0}** — {1}'
                        .format(len(core.OPEN_LEGS),
                                u', '.join(u'{0} at ({1}, {2})'.format(wlink(w), x, y)
                                           for w, x, y in core.OPEN_LEGS[:40])))
    print_design(results, nodes, S)

    mode = S.get('run_mode', 'ask')
    if mode == 'ask':
        mode = ask_mode(existing) if existing else 'update'
        if mode is None:
            output.print_md(u'Cancelled: the model was not touched.')
            return

    pier_ok = syms.get('pier') is not None
    if S.get('use_pier_family') and not pier_ok:
        output.print_md(u'Pier family "{0}" is not loaded — standalone piers are '
                        u'placed with three families instead.'.format(S['families'].get('pier')))
    stirrup_ok = syms.get('stirrup') is not None
    if S.get('stirrup_on') and not stirrup_ok:
        output.print_md(u'Stirrup family "{0}" is not loaded — stirrups at short walls are '
                        u'skipped.'.format(S['families'].get('stirrup')))
    hairpin_ok = syms.get('hairpin') is not None
    if S.get('hairpin_on', True) and not hairpin_ok:
        output.print_md(u'Hairpin family "{0}" is not loaded — hairpin details beside walls are '
                        u'skipped (the lines inside walls are still drawn).'
                        .format(S['families'].get('hairpin')))
    plan = revit_io.build_plan(results, nodes, S, pier_ok=pier_ok, stirrup_ok=stirrup_ok, walls=walls,
                               hairpin_ok=hairpin_ok)
    n_hp = len([r for r in results if r.get('hairpin')])
    if n_hp:
        output.print_md(u'Hairpins (U-bars Ø{0}@{1}, lap {2}Ø past the node) at short piers inside '
                        u'longer walls: **{3}**.'.format(S.get('hairpin_diameter', 8),
                                                          S.get('hairpin_spacing_mm', 200),
                                                          S.get('hairpin_lap_d', 65), n_hp))
    n_st = len([i for i in plan if i['fam'] == 'stirrup'])
    if n_st:
        output.print_md(u'Stirrup details at short walls: **{0}** (Ø{1}@{2}, outside).'.format(
            n_st, S.get('stirrup_diameter'), S.get('stirrup_spacing_mm')))

    # --- проверка ПЕРЕД работой: семейства, типы тегов, параметры внутри них ---
    missing = revit_io.preflight(doc, view, S, plan, log)
    if missing:
        missing = try_add_missing_params(missing, plan, S, log)
    if missing:
        output.print_md(u'### PRE-CHECK FAILED: missing families / parameters — {0}'
                        .format(len(missing)))
        output.print_table([[m['kind'], m['name'], m['detail']] for m in missing],
                           columns=[u'Missing', u'Family / type', u'Details'])
        br = chr(10)
        lines = [u'{0}{3}    {1}{3}    {2}'.format(m['kind'], m['name'], m['detail'], br)
                 for m in missing[:12]]
        if len(missing) > 12:
            lines.append(u'...and {0} more, see the full list in the output window.'
                         .format(len(missing) - 12))
        forms.alert(u'Cannot run - the project is missing:' + br + br + (br + br).join(lines) +
                    br + br + u'Load the families / add the parameters and run again.',
                    title=u'Wall Rebar 2D: pre-check failed', ok=True, cancel=False)
        output.print_md(u'**Stopped: nothing was placed, the model was not touched.**')
        log.finish(summary=u'stopped: missing families / parameters (%d)' % len(missing))
        return
    output.print_md(u'Pre-check: all families and parameters are in place.')

    if mode == 'calc':
        rep = revit_io.write_report([], view, {}, True,
                                    extra={'walls': verdicts, 'view_info': info,
                                           'plan': [dict(key=i['key'], fam=i['fam'], label=i['label'])
                                                    for i in plan]})
        output.print_md(u'**Calculation only: the model was not changed.** Planned elements: {0}. '
                        u'Report: {1}'.format(len(plan), rep))
        log.finish(summary=u'calculation only, %d planned elements' % len(plan))
        return

    n_tags = 0
    with Transaction(doc, u'Wall Rebar 2D') as t:
        t.Start()
        instances, counts = revit_io.apply_plan(doc, view, syms, plan, S, mode, log)
        n_lines = None
        if S.get('stage_stirrup_in', True):
            n_lines = revit_io.draw_stirrup_lines(doc, view, results, S, log)
        doc.Regenerate()
        n_tags = revit_io.place_tags(doc, view, instances, S, log, walls=walls)
        n_tag_lines = None
        if S.get('stage_tag_lines', False):
            doc.Regenerate()
            n_tag_lines = revit_io.draw_tag_lines(doc, view, instances, S, log)
        doc.Regenerate()
        placed = revit_io.report_placed(doc, view, S)
        if dry:
            t.RollBack()
        else:
            t.Commit()

    counts['tags'] = n_tags
    rep_path = revit_io.write_report(
        placed, view, counts, dry,
        extra={'walls': verdicts, 'view_info': info, 'mode': mode,
               'plan': [dict(key=i['key'], fam=i['fam'], label=i['label']) for i in plan]})

    if dry:
        ids = List[ElementId]()
        for w in walls:
            ids.Add(ElementId(w['id']))
        uidoc.Selection.SetElementIds(ids)
        output.print_md(u'**TEST RUN: everything was calculated, placed and rolled back. The model is unchanged.** '
                        u'The taken walls are selected — check they are the right ones.')

    output.print_md(u'### What was done (mode: {0})'.format(
        {'update': u'update', 'recreate': u'recreate'}.get(mode, mode)))
    stage_names = [(u'rebar dots', 'stage_rebar'), (u'stirrup lines in wall', 'stage_stirrup_in'),
                   (u'stirrup details', 'stage_stirrup_detail'), (u'tags', 'place_tags'),
                   (u'tag lines', 'stage_tag_lines')]
    output.print_md(u'Stages: ' + u', '.join(
        u'**{0}** — {1}'.format(n, u'yes' if S.get(k, k != 'stage_tag_lines') else u'left as is')
        for n, k in stage_names))
    if n_tag_lines is not None:
        output.print_md(u'Tag lines: redrawn for **{0}** tags (at their current position).'
                        .format(n_tag_lines))
    if n_lines is not None:
        output.print_md(u'Stirrup inside wall (lines): **{0}** contours drawn, {1} old lines removed.'
                        .format(n_lines[0], n_lines[1]))
    output.print_table([[counts.get('created', 0), counts.get('recreated', 0), counts.get('updated', 0),
                         counts.get('manual', 0), counts.get('kept', 0), counts.get('deleted', 0),
                         counts.get('held', 0), n_tags]],
                       columns=[u'Created', u'Recreated', u'Updated', u'Manual edits',
                                u'Unchanged', u'Deleted', u'Left as is (stage off)', u'Tags'])
    output.print_md(u'Report: {0}'.format(rep_path))
    log.finish(summary=u'created {created}, recreated {recreated}, updated {updated}, '
                       u'manual {manual}, unchanged {kept}, deleted {deleted}, tags {tags}'
               .format(**counts))


main()
