# -*- coding: utf-8 -*-
"""Window of the new Create Column button (IronPython 2.7, pyRevit forms).
It knows nothing about Revit: the data comes from a source object, so the
window opens off-screen too (ui_preview). The button's script gives the
source over the model:

    source.levels()            -> [PR_Level values]
    source.columns(level)      -> [column dicts as revit_collect.read]
    source.problems(level)     -> {'no_mark': [ids], 'dups': {mark: [ids]}, 'no_level': [ids]}
    source.select(ids)         -> selects the elements in the model

After ShowDialog: win.choice = {'level', 'view', 'width_cm', 'groups'} or None.
"""

import clr
clr.AddReference('System.Data')
from System import Action
from System.Data import DataTable
from System.Windows import TextWrapping, Thickness
from System.Windows.Controls import TextBlock
from System.Windows.Media import BrushConverter
from System.Windows.Threading import DispatcherPriority

from pyrevit import forms

from column_rebar import code466, grouping, revit_collect, sketch_wpf

SHAPE_TEXT = {code466.RECT: u'Rectangular', code466.ROUND2: u'Rounded 2 ends',
              code466.ROUND1: u'Rounded 1 end', code466.CIRCLE: u'Round'}
MODES = [u'Auto', u'Ties', u'Hoops']
# contour of a rounded column (code466.CONTOUR_*); a rectangular row shows nothing
CONTOURS = [u'Hoop + U-bars', u'One stirrup']


def contour_text(g):
    if g['shape'] not in code466.ROUNDED:
        return u''
    return CONTOURS[1] if g.get('contour') == code466.CONTOUR_ONE else CONTOURS[0]


def contour_of(text):
    return code466.CONTOUR_ONE if (text or u'') == CONTOURS[1] else code466.CONTOUR_SPLIT
_bc = BrushConverter()
COLORS = {code466.RED: u'#B02020', code466.YELLOW: u'#8A6000'}


def _num(text, default=None):
    t = u'{0}'.format(text or u'').strip().replace(u',', u'.')
    if not t:
        return default
    try:
        return float(t)
    except ValueError:
        return default


def status_of(result):
    levels = set(m['level'] for m in result['messages'])
    if code466.RED in levels or not result.get('stirrup'):
        return u'red'
    return u'yellow' if code466.YELLOW in levels else u'ok'


class ColumnWindow(forms.WPFWindow):

    def __init__(self, xaml, source, settings):
        forms.WPFWindow.__init__(self, xaml)
        self.source = source
        self.choice = None
        self.groups, self.results = [], []
        self.problems = {'no_mark': [], 'dups': {}, 'no_level': []}
        self.tb_view.Text = settings.get('view', u'Column 150')
        self.tb_width.Text = u'{0}'.format(settings.get('width_cm', 59.4))
        self.col_mode.ItemsSource = MODES
        self.col_contour.ItemsSource = CONTOURS
        for lv in source.levels():
            self.cb_level.Items.Add(lv)
        last = settings.get('level')
        self.cb_level.SelectedIndex = (list(self.cb_level.Items).index(last)
                                       if last in list(self.cb_level.Items) else
                                       (0 if self.cb_level.Items.Count else -1))
        if self.cb_level.SelectedIndex < 0:
            self.tb_problems.Text = u'No column has PR_Level.'

    # ---- data ------------------------------------------------------------
    def level(self):
        return self.cb_level.SelectedItem

    def load(self):
        lv = self.level()
        if lv is None:
            return
        cols = self.source.columns(lv)
        self.groups, _ = grouping.make_groups(cols)
        self.problems = self.source.problems(lv)
        self.results = [revit_collect.design(g) for g in self.groups]
        self.fill()

    def fill(self):
        dt = DataTable()
        for c in ('Idx', 'ShapeText', 'Marks', 'Size', 'Dia', 'Qb', 'Qh', 'Stirrup', 'Mode', 'Contour', 'Result', 'Status'):
            dt.Columns.Add(c)
        for i, (g, r) in enumerate(zip(self.groups, self.results)):
            row = dt.NewRow()
            row['Idx'] = u'%d' % i
            row['ShapeText'] = SHAPE_TEXT.get(g['shape'], g['shape'])
            row['Marks'] = u', '.join(grouping.sorted_marks(g['marks']))
            row['Size'] = u'%d / %d' % (round(g['b']), round(g['h']))
            row['Dia'] = u'%g' % g['dia'] if g['dia'] else u''
            row['Qb'] = u'%d' % round(g['qb'])
            row['Qh'] = u'%d' % round(g['qh'])
            row['Stirrup'] = u'%g' % g['stirrup_dia'] if g.get('stirrup_dia') else u''
            row['Mode'] = (g.get('transverse') or u'auto').capitalize()
            row['Contour'] = contour_text(g)
            self._result_cells(row, r)
            dt.Rows.Add(row)
        self.table = dt
        self.dg_groups.ItemsSource = dt.DefaultView
        p = self.problems
        self.tb_problems.Text = (u'Without mark: %d    Duplicate marks: %d    Without PR_Level: %d'
                                 % (len(p['no_mark']), len(p['dups']), len(p['no_level'])))
        if self.groups:
            self.dg_groups.SelectedIndex = 0
        else:
            self.show(None)

    def _result_cells(self, row, r):
        red = [m for m in r['messages'] if m['level'] == code466.RED]
        row['Result'] = red[0]['text'] if red else (code466.summary(r) or u'-')
        row['Status'] = status_of(r)

    def show(self, i):
        self.ic_messages.Items.Clear()
        if i is None or i >= len(self.groups):
            self.tb_selected.Text = u'Select a row'
            self.tb_label.Text = u''
            self.cv_sketch.Children.Clear()
            return
        g, r = self.groups[i], self.results[i]
        a = revit_collect.design_args(g)
        self.tb_selected.Text = u'%s  %d x %d   marks %s' % (SHAPE_TEXT.get(g['shape']), round(g['b']),
                                                           round(g['h']), u', '.join(grouping.sorted_marks(g['marks'])))
        rho = u'   reinforcement %.2f %%' % (r['rho'] * 100) if r.get('rho') else u''
        self.tb_label.Text = (code466.summary(r) or u'') + rho
        sketch_wpf.render(self.cv_sketch, r, g['b'], g['h'], a['cover'], g['dia'] or 16.0)
        msgs = r['messages'] or [{'level': 'ok', 'text': u'No remarks.', 'clause': u''}]
        for m in msgs:
            t = TextBlock()
            t.TextWrapping = TextWrapping.Wrap
            t.Margin = Thickness(0, 0, 0, 4)
            t.Text = m['text'] + ((u'  (%s)' % m['clause']) if m.get('clause') else u'')
            t.Foreground = _bc.ConvertFromString(COLORS.get(m['level'], u'#2A7A35'))
            self.ic_messages.Items.Add(t)

    def selected_index(self):
        i = self.dg_groups.SelectedIndex
        return i if 0 <= i < len(self.groups) else None

    # ---- events ------------------------------------------------------------
    def on_level_changed(self, sender, args):
        self.load()

    def on_refresh(self, sender, args):
        self.load()

    def on_row_selected(self, sender, args):
        self.show(self.selected_index())

    def on_cell_edit_ending(self, sender, args):
        # the DataTable has the new value only after the edit is committed
        self.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(self._after_edit))

    def _after_edit(self):
        i = self.selected_index()
        if i is None:
            return
        row = self.table.Rows[i]
        g = self.groups[i]
        g['dia'] = _num(row['Dia'], g['dia']) or 0.0
        g['qb'] = float(int(_num(row['Qb'], g['qb']) or 0))
        g['qh'] = float(int(_num(row['Qh'], g['qh']) or 0))
        g['stirrup_dia'] = _num(row['Stirrup'], None)
        g['transverse'] = (u'{0}'.format(row['Mode'] or u'Auto')).lower()
        if g['shape'] in code466.ROUNDED:
            g['contour'] = contour_of(u'{0}'.format(row['Contour'] or u''))
        else:
            row['Contour'] = u''
        self.results[i] = r = revit_collect.design(g)
        self._result_cells(row, r)
        self.show(i)

    def on_split(self, sender, args):
        i = self.selected_index()
        if i is None or len(self.groups[i]['marks']) < 2:
            return
        self.groups = grouping.split_group(self.groups, i)
        self.results = [revit_collect.design(g) for g in self.groups]
        self.fill()
        self.dg_groups.SelectedIndex = i

    def on_select_nomark(self, sender, args):
        self.source.select(self.problems['no_mark'])

    def on_select_dups(self, sender, args):
        ids = []
        for v in self.problems['dups'].values():
            ids.extend(v)
        self.source.select(ids)

    def on_select_nolevel(self, sender, args):
        self.source.select(self.problems['no_level'])

    def on_ok(self, sender, args):
        self.dg_groups.CommitEdit()
        view = (self.tb_view.Text or u'').strip()
        width = _num(self.tb_width.Text, 0) or 0
        if self.level() is None or not self.groups:
            forms.alert(u'No columns to draw on this level.', title=u'Create Column')
            return
        if not view:
            forms.alert(u'Give the name of the drafting view.', title=u'Create Column')
            return
        if width < 10:
            forms.alert(u'Sheet width: at least 10 cm.', title=u'Create Column')
            return
        red = [g for g, r in zip(self.groups, self.results) if status_of(r) == u'red']
        if red and not forms.alert(u'%d row(s) have red messages - they will be skipped. Draw the rest?'
                                   % len(red), title=u'Create Column', yes=True, no=True):
            return
        self.choice = {'level': self.level(), 'view': view, 'width_cm': width,
                       'groups': grouping.merge_groups(self.groups)}
        self.DialogResult = True
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()
