# -*- coding: utf-8 -*-
"""Window: what replacing a family in the project changes (load_check.Report).

choice after ShowDialog: 'update' (replace), 'aside' (keep the project family
under another name and load the library one next to it) or None (cancel).
"""

import os

from pyrevit import forms

from System.Windows import FontWeights, HorizontalAlignment, TextWrapping, Thickness, \
    VerticalAlignment, Visibility  # noqa: E402
from System.Windows import Clipboard  # noqa: E402
from System.Windows.Controls import Border, DockPanel, Dock, TextBlock  # noqa: E402

from peer_library import family_diff as D  # noqa: E402
from peer_library import log, strings  # noqa: E402
from peer_library import ui_common as U  # noqa: E402

BTN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       'PEER.tab', 'Library.panel', 'Library.smartbutton')

# level -> (label, text colour, background); no blue (ТЗ)
LOOK = {D.ERROR: (strings.CHECK_L_ERROR, '#7F1D1D', '#FBEBEB'),
        D.WARNING: (strings.CHECK_L_WARNING, '#7C2D12', '#F9EEDA'),
        D.INFO: (strings.CHECK_L_INFO, '#44403C', '#F0EFEC')}
CLEAN = ('#14532D', '#E5F4E4')


class LoadCheckWindow(forms.WPFWindow):

    def __init__(self, report, library_png=None, owner=None):
        forms.WPFWindow.__init__(self, os.path.join(BTN_DIR, 'LoadCheckWindow.xaml'))
        if owner is not None:
            self.Owner = owner
        self.report = report
        self.choice = None
        self.Title = strings.CHECK_TITLE
        self.head.Text = strings.CHECK_HEAD.format(report.family_id)
        lv = report.level
        fg, bg = (LOOK[lv][1], LOOK[lv][2]) if lv in (D.ERROR, D.WARNING) else CLEAN
        self.verdict_box.Background = U.brush(bg)
        self.verdict_box.BorderBrush = U.brush(fg)
        self.verdict_box.BorderThickness = Thickness(1)
        self.verdict.Foreground = U.brush(fg)
        from peer_library import load_check
        self.verdict.Text = load_check.verdict(report)
        self.summary.Text = report.summary or D.trial_summary(report.trial)
        self.summary.Foreground = U.brush(fg)
        self.summary.Visibility = Visibility.Visible if self.summary.Text else Visibility.Collapsed
        self.copy_btn.Content = strings.CHECK_BTN_COPY
        if report.kind == 'family':
            self._family_mode(report)
            return
        self._picture(self.pic_project, self.pic_project_none, report.project_png)
        self._picture(self.pic_library, self.pic_library_none, library_png)
        self.pic_project_label.Text = strings.CHECK_PIC_PROJECT
        self.pic_library_label.Text = strings.CHECK_PIC_LIBRARY
        self.list_label.Text = strings.CHECK_LIST
        for f in report.findings or [(D.INFO, 'clean', strings.CHECK_NOTHING)]:
            self.findings.Children.Add(self._row(f))
        if report.blocking:
            self.update_btn.Content = strings.CHECK_BTN_ANYWAY
            self.update_btn.Background = U.brush('#991B1B')
            self.update_btn.BorderBrush = U.brush('#991B1B')
            self.hint.Text = strings.CHECK_HINT_BREAKS
        else:
            self.update_btn.Content = strings.CHECK_BTN_UPDATE
            self.hint.Text = strings.CHECK_HINT_OK
        self.aside_btn.Content = strings.CHECK_BTN_ASIDE
        self.aside_btn.ToolTip = strings.CHECK_ASIDE_TIP
        self.cancel_btn.Content = strings.CHECK_BTN_CANCEL
        self.cancel_btn.Focus()

    def _family_mode(self, report):
        """Check Family button: the findings only, Close + Copy report."""
        self.Title = strings.FCHECK_TITLE
        self.head.Text = report.family_id
        self.pictures.Visibility = Visibility.Collapsed
        self.list_label.Text = strings.FCHECK_LIST
        for f in report.findings or [(D.INFO, 'clean', strings.FCHECK_NOTHING)]:
            self.findings.Children.Add(self._row(f))
        self.update_btn.Visibility = Visibility.Collapsed
        self.aside_btn.Visibility = Visibility.Collapsed
        self.cancel_btn.Content = strings.FCHECK_CLOSE
        self.hint.Text = report.note
        self.hint.Visibility = Visibility.Visible if report.note else Visibility.Collapsed
        self.cancel_btn.Focus()

    @staticmethod
    def _picture(image, none_text, path):
        src = U.bitmap(path, 400) if path and os.path.isfile(path) else None
        image.Source = src
        none_text.Text = u'' if src is not None else strings.CHECK_NO_PICTURE

    @staticmethod
    def _row(finding):
        lv, code, text = finding
        label, fg, bg = LOOK.get(lv, LOOK[D.INFO])
        row = DockPanel()
        row.Margin = Thickness(0, 4, 0, 4)
        chip = Border()
        chip.Background = U.brush(bg)
        chip.BorderBrush = U.brush(fg)
        chip.BorderThickness = Thickness(1)
        chip.Padding = Thickness(6, 1, 6, 1)
        chip.Width = 66
        chip.Margin = Thickness(0, 1, 10, 0)
        chip.VerticalAlignment = VerticalAlignment.Top
        t = TextBlock()
        t.Text = label
        t.FontSize = 11
        t.FontWeight = FontWeights.SemiBold
        t.Foreground = U.brush(fg)
        t.HorizontalAlignment = HorizontalAlignment.Center
        chip.Child = t
        DockPanel.SetDock(chip, Dock.Left)
        row.Children.Add(chip)
        body = TextBlock()
        body.Text = text
        body.TextWrapping = TextWrapping.Wrap
        body.FontSize = 12.5
        row.Children.Add(body)
        return row

    def on_key(self, sender, args):
        from System.Windows.Input import Key
        if args.Key == Key.Escape:
            self.Close()

    def on_update(self, sender, args):
        if self.report.blocking and not U.ask(strings.CHECK_ANYWAY_ASK, strings.CHECK_TITLE):
            return
        self.choice = 'update'
        self.Close()

    def on_aside(self, sender, args):
        self.choice = 'aside'
        self.Close()

    def on_cancel(self, sender, args):
        self.Close()

    def on_copy(self, sender, args):
        try:
            Clipboard.SetText(self.report.text())
            self.copy_btn.Content = strings.CHECK_COPIED
        except Exception:
            log.write(u'copy report', exc=True)
