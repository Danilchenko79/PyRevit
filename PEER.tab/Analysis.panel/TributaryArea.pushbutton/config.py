# -*- coding: utf-8 -*-
"""Shift+click on Tributary Areas: calculation settings in one window."""
import os
import sys
_here = os.path.dirname(__file__)
while _here and not _here.lower().endswith('.extension'):
    _parent = os.path.dirname(_here)
    if _parent == _here:
        break
    _here = _parent
_lib = os.path.join(_here, 'lib')
if os.path.isdir(_lib) and _lib not in sys.path:
    sys.path.append(_lib)

from pyrevit import forms, script
from tributary import params as P

CFG_SECTION = 'TributaryArea'
NUM_KEYS = ('k_zone', 'edge_k', 'pylon_ratio', 'grid_mm', 'c_nom', 'bar_d',
            'fck', 'top_d1', 'top_s1', 'top_d2', 'top_s2')
BUTTON_GRID = 150.0


def defaults():
    d = dict(P.DEFAULTS)
    d['grid_mm'] = BUTTON_GRID
    return d


def _f(s):
    return float(unicode(s).replace(u',', u'.').strip())


class SettingsWindow(forms.WPFWindow):

    def __init__(self, xaml_path, cur):
        forms.WPFWindow.__init__(self, xaml_path)
        self.saved = None
        self.fill(cur)
        self.FindName('btnSave').Click += self.on_save
        self.FindName('btnCancel').Click += lambda s, a: self.Close()
        self.FindName('btnDefaults').Click += lambda s, a: self.fill(defaults())

    def fill(self, vals):
        for k in NUM_KEYS:
            self.FindName(k).Text = u'{:g}'.format(float(vals[k]))
        self.FindName('use_beams').IsChecked = float(vals['use_beams']) > 0
        self.FindName('lblStatus').Text = u''

    def on_save(self, sender, args):
        new = {}
        for k in NUM_KEYS:
            try:
                new[k] = _f(self.FindName(k).Text)
            except ValueError:
                self.FindName('lblStatus').Text = u'Not a number: {}'.format(self.FindName(k).Text)
                return
        new['use_beams'] = 1.0 if self.FindName('use_beams').IsChecked else 0.0
        try:
            P.merged(new)
        except ValueError as e:
            self.FindName('lblStatus').Text = u'Invalid value: {}'.format(e)
            return
        self.saved = new
        self.Close()


def main():
    cfg = script.get_config(CFG_SECTION)
    cur = defaults()
    for k in NUM_KEYS + ('use_beams',):
        if cfg.has_option(k):
            try:
                cur[k] = float(cfg.get_option(k))
            except (TypeError, ValueError):
                pass
    w = SettingsWindow(script.get_bundle_file('SettingsForm.xaml'), cur)
    w.ShowDialog()
    if not w.saved:
        return
    for k, v in w.saved.items():
        cfg.set_option(k, v)
    script.save_config()


main()
