# -*- coding: utf-8 -*-
"""Wall Rebar 2D dialog (pyrevit.forms.WPFWindow, modal).

Only the per-floor decision lives here: which bar diameters may be used and
the minimum diameter at wall ends. Every other rule is in settings.py.

After the dialog closes:
    window.action  -> 'run' | 'dry' | 'cancel'
    window.S       -> full settings dict (dialog edits only its own keys)
"""

from pyrevit import forms

DIA_BOXES = (8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 32)
STAGE_BOXES = (('cbRebar', 'stage_rebar'), ('cbStirIn', 'stage_stirrup_in'),
               ('cbStirDet', 'stage_stirrup_detail'), ('cbTags', 'place_tags'),
               ('cbTagLines', 'stage_tag_lines'))


def _i(v, default):
    try:
        return int(round(float(unicode(v).replace(',', '.').strip())))
    except (ValueError, TypeError, AttributeError):
        return default


class SettingsWindow(forms.WPFWindow):

    def __init__(self, xaml_path, S, view_name=u'', existing=0, **_ignored):
        forms.WPFWindow.__init__(self, xaml_path)
        self.S = S
        self.action = 'cancel'

        self.FindName('lblView').Text = u'View: {0}'.format(view_name)
        self.FindName('lblExisting').Text = (
            u'{0} reinforcement elements already on this view: they will be updated in place.'
            .format(existing) if existing else u'')

        allowed = set(S.get('allowed_diameters') or [])
        for d in DIA_BOXES:
            self.FindName('d%d' % d).IsChecked = (d in allowed)
        self.FindName('tbMinDia').Text = unicode(S.get('edge_min_diameter', 12))
        for box, key in STAGE_BOXES:
            self.FindName(box).IsChecked = bool(S.get(key, key != 'stage_tag_lines'))

        self.FindName('btnRun').Click += self.on_run
        self.FindName('btnDry').Click += self.on_dry
        self.FindName('btnCancel').Click += self.on_cancel

    def read(self):
        dias = [d for d in DIA_BOXES if self.FindName('d%d' % d).IsChecked]
        if not dias:
            return u'Tick at least one diameter.'
        dmin = _i(self.FindName('tbMinDia').Text, 12)
        if dmin > max(dias):
            return u'Minimum diameter at ends is larger than every ticked diameter.'
        stages = dict((key, bool(self.FindName(box).IsChecked)) for box, key in STAGE_BOXES)
        if not any(stages.values()):
            return u'Tick at least one stage.'
        self.S['allowed_diameters'] = dias
        self.S['edge_min_diameter'] = dmin
        self.S.update(stages)
        return None

    def _go(self, action):
        err = self.read()
        if err:
            self.FindName('lblStatus').Text = err
            return
        self.action = action
        self.Close()

    def on_run(self, sender, args):
        self._go('run')

    def on_dry(self, sender, args):
        self._go('dry')

    def on_cancel(self, sender, args):
        self.action = 'cancel'
        self.Close()
