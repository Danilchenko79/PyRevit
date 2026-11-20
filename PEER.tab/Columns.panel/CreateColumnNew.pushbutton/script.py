# -*- coding: utf-8 -*-
__title__ = "Create Column\n(new)"
__author__ = "Dmitry D"
__doc__ = ("Column sections on a drafting view by SI 466: groups of the level, "
           "stirrup and ties by the rules, live sketch, one Undo. Next to the old Create Column "
           "until the sheets are compared.")
# docs/COLUMNS.md, item 10. Rules - lib/column_rebar/code466.py; the window - lib/column_rebar/ui.py;
# what Create does - lib/column_rebar/button.py. Families: PEER_Column Section / Round2 / Round1
# (new names, so the drawings of the old button are not touched); fallback copies in ./families.

import peer_access; peer_access.require_key()  # one PEER key (lib/peer_library/access.py)
import json
import os

from pyrevit import forms, revit, script
from Autodesk.Revit.DB import ElementId
from System.Collections.Generic import List

from column_rebar import button, grouping, revit_collect, ui
from peer_library import config

doc = revit.doc
uidoc = revit.uidoc
TITLE = button.TITLE
HERE = os.path.dirname(__file__)
SETTINGS = os.path.join(config.appdata_dir(), u'create_column_new.json')


def load_settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(d):
    try:
        with open(SETTINGS, 'w') as f:
            json.dump(d, f)
    except Exception:
        pass


class Source(object):
    """The model for the window - read at the moment the window asks."""

    def levels(self):
        return revit_collect.levels(doc)

    def columns(self, level):
        return revit_collect.level_columns(doc, level)

    def problems(self, level):
        cols = revit_collect.level_columns(doc, level)
        return {'no_mark': [c['id'] for c in cols if grouping.valid_mark(c['mark']) is None],
                'dups': grouping.duplicate_marks(cols),
                'no_level': [c.Id for c in revit_collect.columns(doc) if not revit_collect.level_of(c)]}

    def select(self, ids):
        if ids:
            uidoc.Selection.SetElementIds(List[ElementId](ids))
            forms.alert(u'%d column(s) selected - close the window to see them.' % len(ids), title=TITLE)


def main():
    settings = load_settings()
    win = ui.ColumnWindow(script.get_bundle_file('CreateColumnNewForm.xaml'), Source(), settings)
    win.ShowDialog()
    ch = win.choice
    if not ch:
        return
    save_settings({'view': ch['view'], 'width_cm': ch['width_cm'], 'level': ch['level']})
    out = button.run(doc, ch, os.path.join(HERE, 'families'),
                     lambda text: forms.alert(text, title=TITLE, yes=True, no=True))
    if out['ok'] and out['view'] is not None:
        try:
            uidoc.ActiveView = out['view']
        except Exception:
            pass
    if out['ok'] or out['error']:
        forms.alert(button.summary(out, ch['view']), title=TITLE)


main()
