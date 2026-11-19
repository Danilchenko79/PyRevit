# -*- coding: utf-8 -*-
"""Propose a family: from a file, from the selected element, or the family
open in the editor. Checks are shown and attached, never block sending."""

import os
import shutil

from Autodesk.Revit import DB
from pyrevit import forms

from System.Windows.Input import Cursors, Key  # noqa: E402

from peer_library import checks_file, groups, log, strings  # noqa: E402
from peer_library import ui_common as U  # noqa: E402


def _tmp_dir():
    base = os.environ.get('TEMP') or os.path.expanduser('~')
    d = os.path.join(base, 'PEER', 'propose')
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


def selected_family(doc, uidoc):
    """Family of the single selected element, or None."""
    ids = list(uidoc.Selection.GetElementIds())
    if len(ids) != 1:
        return None
    el = doc.GetElement(ids[0])
    fam = None
    if isinstance(el, DB.FamilyInstance):
        fam = el.Symbol.Family
    elif isinstance(el, DB.FamilySymbol):
        fam = el.Family
    elif el is not None:
        t = doc.GetElement(el.GetTypeId())
        if isinstance(t, DB.FamilySymbol):
            fam = t.Family
    if fam is None or fam.IsInPlace or not fam.IsEditable:
        return None
    return fam


def export_family(doc, fam):
    """Save the family of the project into a temp file; the project is not changed."""
    fd = doc.EditFamily(fam)
    path = os.path.join(_tmp_dir(), fam.Name + '.rfa')
    try:
        so = DB.SaveAsOptions()
        so.OverwriteExistingFile = True
        fd.SaveAs(path, so)
    finally:
        fd.Close(False)
    return path


class ProposeWindow(forms.WPFWindow):

    def __init__(self, xaml_path, doc, uidoc, backend, preset_file=None):
        forms.WPFWindow.__init__(self, xaml_path)
        self.doc, self.uidoc, self.backend = doc, uidoc, backend
        self.sent = None
        self.Title = strings.TITLE_PROPOSE
        self.src_file.Content = strings.SRC_FILE
        self.src_selected.Content = strings.SRC_SELECTED
        self.src_editor.Content = strings.SRC_EDITOR
        self.kind_new.Content = strings.KIND_NEW
        self.kind_fix.Content = strings.KIND_FIX
        for g in groups.GROUPS:
            self.group_box.Items.Add(u'{0}  -  {1}'.format(g[0], g[1]))
        self.group_box.SelectedIndex = 0
        try:
            for c in backend.get_index().get('families', []):
                self.existing_box.Items.Add(c['id'])
        except Exception as ex:
            log.write(u'propose index: {0}'.format(ex))
        self.fam = None
        if preset_file:                       # from Library -> This project
            self.src_file.IsChecked = True
            self.file_box.Text = preset_file
            self.name_box.Text = os.path.splitext(os.path.basename(preset_file))[0]
        elif doc.IsFamilyDocument:
            self.src_editor.IsChecked = True
        elif selected_family(doc, uidoc) is not None:
            self.src_selected.IsChecked = True
        self.on_source(None, None)
        self.on_kind(None, None)

    def on_key(self, sender, args):
        if args.Key == Key.Escape:
            self.Close()

    def on_kind(self, sender, args):
        self.existing_box.IsEnabled = bool(self.kind_fix.IsChecked)

    def on_source(self, sender, args):
        is_file = bool(self.src_file.IsChecked)
        self.file_box.IsEnabled = is_file
        self.browse_btn.IsEnabled = is_file
        self.src_info.Text = u''
        self.fam = None
        if self.src_selected.IsChecked:
            self.fam = selected_family(self.doc, self.uidoc) if not self.doc.IsFamilyDocument else None
            self.src_info.Text = self.fam.Name if self.fam else strings.PROPOSE_NO_SELECTION
            if self.fam and not self.name_box.Text:
                self.name_box.Text = self.fam.Name
        elif self.src_editor.IsChecked:
            if not self.doc.IsFamilyDocument:
                self.src_info.Text = u'Open the family in the editor and run the button there.'
            elif not self.doc.PathName or self.doc.IsModified:
                self.src_info.Text = strings.PROPOSE_SAVE_EDITOR
            else:
                self.src_info.Text = self.doc.PathName
                if not self.name_box.Text:
                    self.name_box.Text = os.path.splitext(os.path.basename(self.doc.PathName))[0]

    def on_browse(self, sender, args):
        p = forms.pick_file(file_ext='rfa')
        if p:
            self.file_box.Text = p
            if not self.name_box.Text:
                self.name_box.Text = os.path.splitext(os.path.basename(p))[0]

    def on_shot(self, sender, args):
        p = forms.pick_file(file_ext='png')
        if p:
            self.shot_box.Text = p

    def _source_file(self):
        if self.src_file.IsChecked:
            p = (self.file_box.Text or u'').strip().strip('"')
            return p if os.path.isfile(p) else None
        if self.src_selected.IsChecked:
            return export_family(self.doc, self.fam) if self.fam else None
        if self.doc.IsFamilyDocument and self.doc.PathName and not self.doc.IsModified:
            return self.doc.PathName
        return None

    def _checks(self, path):
        res, year = checks_file.check_file(path)
        lines = [u'{0}: {1}'.format(r[0].upper(), r[2]) for r in res if r[0] != 'info']
        self.checks_text.Text = u'\n'.join(lines) or u'No problems found'
        return res, year

    def on_check(self, sender, args):
        try:
            path = self._source_file()
        except Exception as ex:
            log.write(u'propose export', exc=True)
            self.status_text.Text = u'{0}'.format(ex)
            return
        if not path:
            self.status_text.Text = self.src_info.Text or u'Choose the family file.'
            return
        self._checks(path)

    def on_send(self, sender, args):
        name = (self.name_box.Text or u'').strip()
        reason = (self.reason_box.Text or u'').strip()
        if not name or not reason:
            self.status_text.Text = strings.PROPOSE_NEED
            return
        self.Cursor = Cursors.Wait
        try:
            path = self._source_file()
            if not path:
                self.status_text.Text = self.src_info.Text or u'Choose the family file.'
                return
            res, year = self._checks(path)
            i = self.group_box.SelectedIndex
            fix = bool(self.kind_fix.IsChecked)
            meta = {'name': name, 'reason': reason,
                    'group': groups.GROUP_IDS[i] if i >= 0 else u'',
                    'kind': 'fix' if fix else 'new',
                    'family_id': (self.existing_box.Text or u'').strip() if fix else
                    os.path.splitext(os.path.basename(path))[0],
                    'revit': year,
                    'checks': [{'level': r[0], 'code': r[1], 'text': r[2]} for r in res]}
            shot = (self.shot_box.Text or u'').strip().strip('"') or None
            self.sent = self.backend.send_proposal(meta, path, shot)
        except Exception as ex:
            log.write(u'propose send', exc=True)
            self.status_text.Text = u'{0}'.format(ex)
            return
        finally:
            self.Cursor = None
        U.info(strings.PROPOSE_SENT)
        self.Close()
