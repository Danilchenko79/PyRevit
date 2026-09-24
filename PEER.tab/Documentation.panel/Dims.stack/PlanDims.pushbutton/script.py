# -*- coding: utf-8 -*-
__title__ = 'Plan Dims'
__author__ = 'Dima'
__doc__ = u'''Version = 1.3
Date      = 2026-09-11
Description:
    Linear dimension chains on a slab plan (RE view): outer chains along
    each facade run plus an overall chain per side, interior chains along
    the main wall lines (every wall gets located), balcony and slab-opening
    extents, and optionally a grid chain outermost of all. Witness points
    are element faces; chains that would cut geometry or text move outward.
    Geometry is read from the host and from every loaded Revit link that
    carries structure, so a documentation model can dimension linked
    concrete.
How-To:
    1. Open the RE view (or another view - a name prefix is asked).
    2. Pre-select elements to dimension only those, or nothing for all.
       Pre-selecting a link instance means "everything from that link".
    3. Choose Place or Preview, then answer the grid question.
    Rerunning removes only the chains this button made; one Ctrl+Z undoes
    the whole run.
'''

import os as _os, sys as _sys
_ext = _os.path.dirname(_os.path.abspath(__file__))
while _ext and not _ext.endswith('.extension'):
    _parent = _os.path.dirname(_ext)
    if _parent == _ext:
        break
    _ext = _parent
_lib = _os.path.join(_ext, 'lib')
if _os.path.isdir(_lib) and _lib not in _sys.path:
    _sys.path.append(_lib)

from pyrevit import revit, script, forms
from Autodesk.Revit.DB import (FilteredElementCollector, ViewPlan,
                               BuiltInCategory)

import kz_plandims as KP
import kz_links
from peer_log import RunLog

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()
log = RunLog('PlanDims')

active = revit.active_view
views = []
if isinstance(active, ViewPlan) and not active.IsTemplate:
    views = [active]
else:
    prefix = forms.ask_for_string(
        default=u'', prompt=u'Plan view name starts with:',
        title=u'Plan Dims')
    if not prefix:
        script.exit()
    for v in FilteredElementCollector(doc).OfClass(ViewPlan):
        try:
            if v.IsTemplate:
                continue
            if v.Name.startswith(prefix):
                views.append(v)
        except Exception:
            pass
    if not views:
        forms.alert(u'No plan view starting with "{}".'.format(prefix),
                    exitscript=True)

odd = [v.Name for v in views
       if KP.TEMPLATE_HINT not in KP.template_name(doc, v)]
if odd:
    if not forms.alert(
            u'These views do not use the {} template:\n{}\n\nContinue?'
            .format(KP.TEMPLATE_HINT, u'\n'.join(odd[:8])),
            yes=True, no=True):
        script.exit()

# Where the geometry comes from: the host first, then every loaded link
# that carries structure. Worth stating on the sheet report - a chain bound
# to a link breaks when that link is unloaded.
used = []
seen = set()
rotated = []
view_sources = {}
for v in views:
    srcs = KP.plan_sources(doc, v)
    view_sources[v.Id.IntegerValue] = srcs
    for s in srcs:
        if s.name not in seen:
            seen.add(s.name)
            used.append(s)
        if s.is_link and not kz_links.is_axis_aligned(s.xform) and s.name not in rotated:
            rotated.append(s.name)
src_line = kz_links.describe(used)
output.print_md(u'**Sources:** {}'.format(src_line))

# Chains are built on the world axes, so a link turned off them offers
# almost no axis-aligned faces. Say so and carry on.
for nm in rotated:
    msg = (u'link "{}" is rotated off the world axes: chains run on world '
           u'axes, so few or no faces of it can be dimensioned'.format(nm))
    output.print_md(u'- {}'.format(msg))
    log.skipped(nm, msg)

# Pre-selected elements limit the run to them; nothing selected means the
# whole view. A selected link instance stands for everything in that link.
only = set()
try:
    for eid in uidoc.Selection.GetElementIds():
        only.add(eid.IntegerValue)
except Exception:
    only = set()
if only:
    if not forms.alert(
            u'{} elements are selected.\n\nDimension only those?'.format(len(only)),
            yes=True, no=True):
        only = set()

mode = forms.CommandSwitchWindow.show(
    [u'Place dimensions', u'Preview only (no change)'],
    message=u'Plan dimensions:')
if not mode:
    script.exit()

# The grid chain is the engineer's call: the reference sheets never use
# grids, but a plan that has them may want their spacings shown.
n_grids = 0
for v in views:
    for s in view_sources[v.Id.IntegerValue]:
        try:
            # a link is not filtered by a host view id, so count all of it
            col = (FilteredElementCollector(s.doc) if s.is_link
                   else FilteredElementCollector(s.doc, v.Id))
            n_grids += (col.OfCategory(BuiltInCategory.OST_Grids)
                        .WhereElementIsNotElementType().GetElementCount())
        except Exception:
            pass
use_grids = False
if n_grids:
    ans = forms.CommandSwitchWindow.show(
        [u'No, faces only', u'Yes, add a grid chain'],
        message=u'{} grids on the view. Dimension grid spacings?'.format(n_grids))
    if not ans:
        script.exit()
    use_grids = ans.startswith(u'Yes')
KP.set_options(grid_rows=use_grids)

scope = u'selection ({})'.format(len(only)) if only else u'whole view'
if mode.startswith(u'Preview'):
    report, warns = KP.preview_views(doc, views, only=only or None)
    for name, lines in report:
        output.print_md(u'**{}**'.format(name))
        for line in lines:
            output.print_md(u'- {}'.format(line))
        log.skipped(name, u'preview, {} chains'.format(len(lines)))
    for w in warns:
        output.print_md(u'- {}'.format(w))
    log.finish(summary=u'Preview of {} view(s), {}, grids={}, sources: {}, '
               u'nothing created'.format(len(views), scope, use_grids, src_line))
    script.exit()

done, warns, report = KP.annotate_views(doc, views, only=only or None)

rows = [[name, u', '.join(items) if items else u'-'] for name, items in report]
output.print_table(table_data=rows, columns=[u'View', u'Placed'])
for w in warns:
    log.error(u'-', w)
    output.print_md(u'- {}'.format(w))
summary = u'Dimensioned {} of {} view(s), {}, grids={}, sources: {}'.format(
    done, len(views), scope, use_grids, src_line)
output.print_md(u'**{}**'.format(summary))
for name, items in report:
    log.processed(name, u'; '.join(items))
log.finish(summary=summary)
