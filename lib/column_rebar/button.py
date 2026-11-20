# -*- coding: utf-8 -*-
"""What the new Create Column button does after the window's Create (Revit,
IronPython 2.7). Separate from the button script so it can be run on a test
project without the window (tests/revit_e2e.py).

    result = button.run(doc, choice, families_folder, ask, require_families=True)

choice  = {'view', 'width_cm', 'groups'} from the window (grouping groups)
ask     = callable(text) -> bool for a yes / no question (the script: forms.alert)
Returns {'ok', 'drawn', 'skipped', 'notes', 'loaded', 'view', 'error'}.
Everything changes in ONE TransactionGroup (one Undo); all checks come first.
"""

from Autodesk.Revit.DB import (ElementId, FilteredElementCollector, TransactionGroup, ViewDrafting,
                               ViewFamily, ViewFamilyType)
from System.Collections.Generic import List

from column_rebar import code466, numbering, revit_collect, revit_draw, revit_params, slots
from column_rebar.family_build import run as tx

TITLE = u'Create Column (new)'


def status_of(result):
    levels = set(m['level'] for m in result['messages'])
    if code466.RED in levels or not result.get('stirrup') or not result.get('bars'):
        return u'red'
    return u'yellow' if code466.YELLOW in levels else u'ok'


def find_view(doc, name):
    for v in FilteredElementCollector(doc).OfClass(ViewDrafting):
        if not v.IsTemplate and v.Name == name:
            return v
    return None


def clearable(doc, view):
    """What 'replace everything on the view' may delete: details, annotations,
    dimensions, texts, lines, regions. NOT everything the view owns - that takes
    its sketch plane and other internals with it, and the next drawing fails
    ('the referenced object is not valid'; REVIT_BASE: clean 2D by category)."""
    from Autodesk.Revit.DB import (BuiltInCategory, CategoryType, CurveElement, Dimension, FamilyInstance,
                                   FilledRegion, Group, IndependentTag, TextNote)
    keep_cls = (FamilyInstance, Dimension, TextNote, IndependentTag, CurveElement, FilledRegion, Group)
    out = []
    for e in FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
        if e.Id == view.Id or e.OwnerViewId != view.Id:
            continue
        cat = e.Category
        if isinstance(e, keep_cls) or (cat is not None and cat.CategoryType == CategoryType.Annotation):
            out.append(e.Id)
    return out


def plan(groups):
    """(todo [(group, result, slot values)], skipped [text]) - pure, no model change."""
    todo, skipped = [], []
    for g in groups:
        r = revit_collect.design(g)
        a = revit_collect.design_args(g)
        if status_of(r) == u'red':
            reds = [m['text'] for m in r['messages'] if m['level'] == code466.RED]
            skipped.append(u'%s: %s' % (u', '.join(g['marks']), reds[0] if reds else u'no section'))
            continue
        try:
            vals = slots.params(r, g['b'], g['h'], a['cover'], g['dia'], a['nb'], a['nh'], g['shape'])
        except ValueError as ex:
            skipped.append(u'%s: %s' % (u', '.join(g['marks']), ex))
            continue
        todo.append((g, r, vals))
    return todo, skipped


def run(doc, choice, families_folder, ask, require_families=True):
    out = {'ok': False, 'drawn': 0, 'skipped': [], 'notes': [], 'loaded': [], 'view': None, 'error': None}
    todo, out['skipped'] = plan(choice['groups'])
    if not todo:
        out['error'] = u'Nothing to draw.'
        return out
    if require_families:
        from peer_library import require
        res = require.families(doc, revit_draw.REQUIRED, folder=families_folder)
        out['loaded'] = [n for n, s in res.loaded]
        if not res.ok:
            out['error'] = res.message()
            return out
    types = revit_draw.find_types(doc)
    lost = [revit_draw.SECTION_FAMILY[s] for s in set(g['shape'] for g, _, _ in todo) if types[s] is None]
    if lost:
        out['error'] = u'Families not in the project: ' + u', '.join(lost)
        return out
    if types['missing'] and not ask(u'Not in the project (the drawing goes without them): ' +
                                    u', '.join(types['missing']) + u'\nContinue?'):
        return out
    if find_view(doc, choice['view']) is not None and \
            not ask(u'The view "%s" exists. Replace everything on it?' % choice['view']):
        return out

    report = {'notes': []}
    st = {}
    tg = TransactionGroup(doc, TITLE)
    tg.Start()
    try:
        def params():
            revit_params.ensure_params(doc)
            doc.Regenerate()
            for g, r, _ in todo:
                revit_draw.write_columns(doc, g, r)

        def make_view():
            v = find_view(doc, choice['view'])
            if v is None:
                vft = [t for t in FilteredElementCollector(doc).OfClass(ViewFamilyType)
                       if t.ViewFamily == ViewFamily.Drafting][0]
                v = ViewDrafting.Create(doc, vft.Id)
                v.Name = choice['view']
                v.Scale = 25
            else:
                ids = clearable(doc, v)
                if ids:
                    doc.Delete(List[ElementId](ids))
            st['v'] = v

        def draw():
            v = st['v']
            revit_draw.activate(types)
            pos = revit_draw.pack([g for g, _, _ in todo], [r for _, r, _ in todo],
                                  choice['width_cm'] * 10.0 * (v.Scale or 25))
            for (g, r, vals), p in zip(todo, pos):
                revit_draw.draw_group(doc, v, g, r, vals, p, types, report)

        def numbers():
            doc.Regenerate()                 # Rebar_Length is a formula of the shape
            n = numbering.number_view(doc, st['v'])
            st['numbers'] = n
            if n['written'] < n['details']:
                report['notes'].append(u'bar numbers: %d of %d details have no Rebar_Number'
                                       % (n['details'] - n['written'], n['details']))

        steps = [(u'parameters', params), (u'view', make_view), (u'drawing', draw), (u'numbers', numbers)]
        for name, fn in steps:
            r = tx(doc, u'Create Column: ' + name, fn)
            if r[1] != 'Committed':
                tg.RollBack()
                out['error'] = u'Nothing was changed - %s: %s %s' % (name, r[1], u'; '.join(r[2]))
                return out
        tg.Assimilate()
    finally:
        if tg.HasStarted() and not tg.HasEnded():
            tg.RollBack()
    out.update(ok=True, drawn=len(todo), notes=report['notes'], view=st.get('v'), numbers=st.get('numbers'))
    return out


def summary(out, view_name):
    if out['error']:
        return out['error']
    lines = [u'Drawn: %d group(s) on "%s".' % (out['drawn'], view_name)]
    n = out.get('numbers')
    if n:
        lines.append(u'Bar numbers: %d positions on %d details of the view.' % (n['positions'], n['details']))
    if out['skipped']:
        lines.append(u'\nNot drawn (red):\n' + u'\n'.join(out['skipped']))
    if out['notes']:
        lines.append(u'\nNotes:\n' + u'\n'.join(out['notes']))
    if out['loaded']:
        lines.append(u'\nLoaded: ' + u', '.join(out['loaded']))
    return u'\n'.join(lines)
