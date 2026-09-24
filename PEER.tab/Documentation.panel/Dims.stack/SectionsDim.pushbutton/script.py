# -*- coding: utf-8 -*-
__title__ = 'Sections Dim'
__author__ = 'Dima'
__doc__ = u'''Version = 1.2
Date      = 2026-09-24
Description:
    Dimensions and level marks on beam / lintel sections: a vertical chain
    of heights on the left (concrete faces incl. the adjacent slabs), the
    element width below, the slab thickness at its far end and the floor
    level mark (typical floor: O.K. symbol, regular floor: Spot Elevation).
    Everything is kept inside the view crop (offsets in paper mm); the
    chain goes outside the left crop edge when a slab is on the left.
    Re-run replaces the marks placed by the previous run.
How-To:
    1. Open a section (dresses it) or any other view (asks for a prefix and
       dresses all "{prefix}_S*" sections; #REF dummies are skipped).
    2. Choose the floor mode.
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
from Autodesk.Revit.DB import FilteredElementCollector, ViewSection

import kz_dims as KD
from peer_log import RunLog

doc = revit.doc
output = script.get_output()
log = RunLog('SectionsDim')

active = revit.active_view
views = []
if isinstance(active, ViewSection) and not active.IsTemplate:
    views = [active]
else:
    prefix = forms.ask_for_string(
        default=u'', prompt=u'Section name prefix ({prefix}_S*):',
        title=u'Sections Dim')
    if not prefix:
        script.exit()
    for v in FilteredElementCollector(doc).OfClass(ViewSection):
        try:
            if v.IsTemplate:
                continue
            nm = v.Name
            if nm.startswith(u'{}_S'.format(prefix)) and u'#REF' not in nm:
                views.append(v)
        except Exception:
            pass
    if not views:
        forms.alert(u'No sections "{}_S*" found.'.format(prefix),
                    exitscript=True)

mode = forms.CommandSwitchWindow.show(
    [u'Typical floor (O.K. symbol)', u'Regular floor (Spot Elevation)'],
    message=u'Floor level mark:')
if not mode:
    script.exit()
typical = mode.startswith(u'Typical')

done, warns, placed = KD.annotate_views(doc, views, typical)

rows = [[n, u', '.join(items) if items else u'-'] for n, items in placed]
output.print_table(table_data=rows, columns=[u'Section', u'Placed'])
for w in warns:
    log.error(u'-', w)
    output.print_md(u'- {}'.format(w))
summary = u'Dressed {} of {} sections | {}'.format(
    done, len(views), u'typical floor' if typical else u'regular floor')
output.print_md(u'**{}**'.format(summary))
for n, items in placed:
    log.processed(n, u'; '.join(items))
log.finish(summary=summary)
