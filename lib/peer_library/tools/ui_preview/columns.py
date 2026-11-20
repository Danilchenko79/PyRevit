# -*- coding: utf-8 -*-
"""The new Create Column window off-screen, on made-up columns (no Revit):
    powershell -STA -ExecutionPolicy Bypass -File lib\\peer_library\\tools\\ui_preview\\run.ps1 -Script columns
Pictures: columns_*.png in the output folder."""
from __future__ import print_function
import os
import traceback

execfile(os.path.join(os.path.dirname(__file__), 'stubs.py'))   # noqa: F821

from column_rebar import code466, ui  # noqa: E402

XAML = os.path.join(EXT, 'PEER.tab', 'Columns.panel', 'CreateColumnNew.pushbutton',   # noqa: F821
                    'CreateColumnNewForm.xaml')


def col(i, mark, shape, b, h, qb, qh, d, **k):
    c = {'id': i, 'mark': mark, 'shape': shape, 'b': float(b), 'h': float(h), 'qb': float(qb),
         'qh': float(qh), 'dia': float(d), 'cover': 25.0, 'stirrup_dia': None, 'spacing': None,
         'dense': None, 'transverse': 'auto', 'top_level': u'L1', 'level': u'L1'}
    c.update(k)
    return c


class Source(object):
    def __init__(self):
        self.selected = []
        R, O2, O1 = code466.RECT, code466.ROUND2, code466.ROUND1
        self.cols = [col(1, '1', R, 400, 400, 2, 2, 16), col(2, '2', R, 400, 400, 2, 2, 16),
                     col(3, '3', R, 400, 400, 2, 2, 16), col(4, '5', R, 800, 800, 2, 2, 25),
                     col(5, '6', R, 1500, 600, 5, 1, 20), col(6, '7', R, 1500, 600, 5, 1, 20),
                     col(7, '8', O2, 500, 1250, 3, 6, 20), col(8, '9', O1, 600, 1000, 3, 4, 20),
                     col(9, '10', R, 300, 300, 3, 3, 25), col(10, '11', R, 600, 600, 3, 3, 20, transverse='ties'),
                     col(11, None, R, 400, 400, 2, 2, 16), col(12, '1', R, 500, 500, 2, 2, 20)]

    def levels(self):
        return [u'L1', u'L2']

    def columns(self, level):
        return self.cols if level == u'L1' else []

    def problems(self, level):
        return {'no_mark': [11], 'dups': {'1': [1, 12]}, 'no_level': [99, 100]}

    def select(self, ids):
        self.selected = list(ids)


def run():
    try:
        src = Source()
        win = ui.ColumnWindow(XAML, src, {'view': u'Column 150', 'width_cm': 59.4, 'level': u'L1'})
        show(win)                                   # noqa: F821
        snap(win, OUT, 'columns_1.png')            # noqa: F821
        for i, name in ((3, 'columns_pylon.png'), (5, 'columns_round1.png'), (6, 'columns_bad.png')):
            win.dg_groups.SelectedIndex = i
            pump(400)                               # noqa: F821
            snap(win, OUT, name)                    # noqa: F821
        # an edit: more bars on the bad row -> the row recomputes
        win.table.Rows[6]['Dia'] = u'16'
        win.dg_groups.SelectedIndex = 6
        win._after_edit()
        pump(300)                                   # noqa: F821
        snap(win, OUT, 'columns_edit.png')          # noqa: F821
        print('rows', len(win.groups), [g['marks'] for g in win.groups])
        print('status', [win.table.Rows[i]['Status'] for i in range(win.table.Rows.Count)])
        win.on_select_dups(None, None)
        print('selected dups', src.selected)
        win.Close()
    except Exception:
        traceback.print_exc()


run()
