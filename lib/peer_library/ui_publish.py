# -*- coding: utf-8 -*-
"""Admin publish window (also opened from the inbox with a proposal)."""

import os

from pyrevit import forms

from System.Windows import FontWeights, TextWrapping, Thickness  # noqa: E402
from System.Windows.Controls import Orientation, StackPanel, TextBlock  # noqa: E402
from System.Windows.Input import Cursors, Key  # noqa: E402

from peer_library import checks_file, groups, index, log, publish, strings  # noqa: E402
from peer_library import revit_family  # noqa: E402
from peer_library import ui_common as U  # noqa: E402

LEVEL_LOOK = {'error': (u'ERROR', '#7F1D1D', '#FEE2E2'),
              'warning': (u'WARNING', '#7C2D12', '#FFEDD5'),
              'info': (u'INFO', '#44403C', '#F5F5F4'),
              'ok': (u'OK', '#14532D', '#DCFCE7')}


class PublishWindow(forms.WPFWindow):

    def __init__(self, xaml_path, app, backend, prefill=None):
        forms.WPFWindow.__init__(self, xaml_path)
        self.app, self.backend = app, backend
        self.prefill = prefill or {}
        self.proposal_id = self.prefill.get('proposal_id')
        self.published = None
        self.cards = {}
        self.Title = strings.TITLE_PUBLISH
        self.mode_new.Content = strings.MODE_NEW
        self.mode_update.Content = strings.MODE_UPDATE
        self.accept_box.Content = strings.ACCEPT_WARNINGS
        for g in groups.GROUPS:
            self.group_box.Items.Add(u'{0}  -  {1}'.format(g[0], g[1]))
        self.group_box.SelectedIndex = 0
        try:
            for c in backend.get_index().get('families', []):
                self.cards[c['id']] = c
        except Exception as ex:
            self.status_text.Text = u'{0}'.format(ex)
        for fid in sorted(self.cards, key=lambda x: x.lower()):
            self.existing_box.Items.Add(fid)
        self._apply_prefill()
        self.on_mode(None, None)
        if revit_family.revit_version(app) != checks_file.LIBRARY_REVIT:
            self.status_text.Text = strings.PUBLISH_ONLY_2024.format(checks_file.LIBRARY_REVIT)

    # ---- form ----------------------------------------------------------
    def _apply_prefill(self):
        p = self.prefill
        if p.get('file'):
            self.file_box.Text = p['file']
        if p.get('family_id') and p.get('family_id') in self.cards:
            self.mode_update.IsChecked = True
            self.existing_box.Text = p['family_id']
            self._fill_from_card(self.cards[p['family_id']])
        if p.get('name'):
            self.name_box.Text = p['name']
        if p.get('group') in groups.GROUP_IDS:
            self.group_box.SelectedIndex = groups.GROUP_IDS.index(p['group'])
        if p.get('reason'):
            self.note_box.Text = p['reason']

    def _group(self):
        i = self.group_box.SelectedIndex
        return groups.GROUP_IDS[i] if 0 <= i < len(groups.GROUP_IDS) else groups.GROUP_IDS[0]

    def _fill_from_card(self, c):
        self.id_box.Text = c['id']
        self.name_box.Text = c.get('name') or u''
        self.tags_box.Text = u', '.join(c.get('tags') or [])
        self.desc_box.Text = c.get('description') or u''
        self.help_box.Text = c.get('help_url') or u''
        if c.get('group') in groups.GROUP_IDS:
            self.group_box.SelectedIndex = groups.GROUP_IDS.index(c['group'])

    def on_mode(self, sender, args):
        upd = bool(self.mode_update.IsChecked)
        self.existing_box.IsEnabled = upd
        self.id_box.IsReadOnly = upd
        if upd:
            self.on_existing(None, None)
        else:
            self.on_file_changed(None, None)

    def on_existing(self, sender, args):
        fid = self.existing_box.SelectedItem or self.existing_box.Text
        if fid in self.cards:
            self._fill_from_card(self.cards[fid])

    def on_file_changed(self, sender, args):
        if self.mode_update.IsChecked:
            return
        path = (self.file_box.Text or u'').strip().strip('"')
        if path.lower().endswith('.rfa'):
            base = os.path.splitext(os.path.basename(path))[0]
            if not self.proposal_id or not self.id_box.Text:
                self.id_box.Text = base
            if not self.name_box.Text:
                self.name_box.Text = base

    def on_browse(self, sender, args):
        path = forms.pick_file(file_ext='rfa')
        if path:
            self.file_box.Text = path

    def on_key(self, sender, args):
        if args.Key == Key.Escape:
            self.Close()

    def _draft(self):
        tags = [t.strip() for t in (self.tags_box.Text or u'').split(u',') if t.strip()]
        fid = (self.id_box.Text or u'').strip()
        return index.new_card(id=fid, name=(self.name_box.Text or u'').strip() or fid,
                              group=self._group(), tags=tags,
                              description=(self.desc_box.Text or u'').strip(),
                              help_url=(self.help_box.Text or u'').strip())

    # ---- results -------------------------------------------------------
    def _show_results(self, results):
        self.results_list.Items.Clear()
        if not results:
            results = [('ok', 'ok', u'No problems found')]
        for level, code, text in results:
            label, fg, bg = LEVEL_LOOK.get(level, LEVEL_LOOK['info'])
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            row.Margin = Thickness(2)
            chip = U.chip(label, None)
            chip.Background = U.brush(bg)
            chip.BorderBrush = U.brush(fg)
            chip.Child.Foreground = U.brush(fg)
            chip.Width = 78
            chip.Margin = Thickness(0, 0, 8, 0)
            row.Children.Add(chip)
            t = TextBlock()
            t.Text = text
            t.TextWrapping = TextWrapping.Wrap
            t.MaxWidth = 560
            if level == 'error':
                t.FontWeight = FontWeights.SemiBold
            row.Children.Add(t)
            self.results_list.Items.Add(row)

    def _source(self):
        return (self.file_box.Text or u'').strip().strip('"')

    def _precheck(self):
        src = self._source()
        draft = self._draft()
        res, _ = checks_file.check_file(src, draft['id'] or None)
        if revit_family.revit_version(self.app) != checks_file.LIBRARY_REVIT:
            res.append(('error', 'revit_app',
                        strings.PUBLISH_ONLY_2024.format(checks_file.LIBRARY_REVIT)))
        upd = bool(self.mode_update.IsChecked)
        exists = draft['id'] in self.cards
        if upd and not exists:
            res.append(('error', 'mode', u'Pick an existing family to update'))
        if not upd and any(k.lower() == draft['id'].lower() for k in self.cards):
            res.append(('error', 'mode', u'"{0}" is already in the library - choose '
                                         u'"New version of an existing family"'.format(draft['id'])))
        if upd and not (self.note_box.Text or u'').strip():
            res.append(('error', 'note', strings.NOTE_NEEDED))
        return res, draft

    def on_check(self, sender, args):
        res, _ = self._precheck()
        self._show_results(res)
        self.status_text.Text = u''

    def on_publish(self, sender, args):
        res, draft = self._precheck()
        if checks_file.errors(res):
            self._show_results(res)
            self.status_text.Text = strings.PUBLISH_BLOCKED
            return
        self.Cursor = Cursors.Wait
        self.status_text.Text = u'Publishing {0}… (opening the family in the background)' \
            .format(draft['id'])
        self.publish_btn.IsEnabled = False
        try:
            card, results = publish.publish_one(
                self.app, self.backend, self._source(), draft, (self.note_box.Text or u'').strip(),
                accept_warnings=bool(self.accept_box.IsChecked), proposal_id=self.proposal_id)
        except Exception as ex:
            log.write(u'publish window', exc=True)
            card, results = None, [('error', 'crash', u'{0}'.format(ex))]
        finally:
            self.Cursor = None
            self.publish_btn.IsEnabled = True
        self._show_results(results)
        if card:
            self.published = card
            self.cards[card['id']] = card
            self.status_text.Text = strings.PUBLISH_OK.format(card['id'], card['version'])
            U.info(strings.PUBLISH_OK.format(card['id'], card['version']))
            if self.proposal_id:
                self.Close()
        elif checks_file.errors(results):
            self.status_text.Text = strings.PUBLISH_BLOCKED
        else:
            self.status_text.Text = strings.PUBLISH_NEED_ACCEPT

    # ---- card info in Excel --------------------------------------------------
    def on_csv_export(self, sender, args):
        from peer_library import cards_csv
        path = forms.save_file(file_ext='csv', default_name='PEER library info')
        if not path:
            return
        try:
            n = cards_csv.export(list(self.cards.values()), path)
        except Exception as ex:
            log.write(u'csv export', exc=True)
            U.error(u'{0}'.format(ex))
            return
        self.status_text.Text = strings.CSV_EXPORTED.format(n, path)
        try:
            os.startfile(path)
        except Exception:
            pass

    def on_csv_import(self, sender, args):
        from peer_library import cards_csv
        path = forms.pick_file(file_ext='csv')
        if not path:
            return
        try:
            todo, problems = cards_csv.changes(list(self.cards.values()), path)
        except Exception as ex:
            log.write(u'csv import', exc=True)
            U.error(u'{0}'.format(ex))
            return
        if not todo:
            U.info(strings.CSV_NOTHING + (u'\n\n' + u'\n'.join(problems[:15]) if problems else u''))
            return
        sample = u'\n'.join(u'{0}: {1}'.format(t['id'], u', '.join(sorted(t['fields'])))
                            for t in todo[:12])
        msg = strings.CSV_ASK.format(len(todo), sample)
        if problems:
            msg += u'\n\n' + strings.CSV_PROBLEMS + u'\n' + u'\n'.join(problems[:10])
        if not U.ask(msg):
            return
        ok, failed = 0, []
        with forms.ProgressBar(title=u'Updating {value} of {max_value}') as pb:
            for i, t in enumerate(todo):
                pb.update_progress(i, len(todo))
                try:
                    card = self.backend.update_card(t['id'], t['fields'])
                    self.cards[card['id']] = card
                    ok += 1
                except Exception as ex:
                    failed.append(u'{0}: {1}'.format(t['id'], ex))
        U.info(strings.CSV_DONE.format(ok) + (u'\n\n' + u'\n'.join(failed[:10]) if failed else u''))

    # ---- batch ---------------------------------------------------------
    def on_batch(self, sender, args):
        if revit_family.revit_version(self.app) != checks_file.LIBRARY_REVIT:
            U.error(strings.PUBLISH_ONLY_2024.format(checks_file.LIBRARY_REVIT))
            return
        folder = forms.pick_folder(title=strings.BATCH_TITLE)
        if not folder:
            return
        items = publish.folder_items(folder)
        new = [x for x in items if x[1].lower() not in set(k.lower() for k in self.cards)]
        if not new:
            U.info(u'Nothing new in {0} (expected <group>/<ID>.rfa).'.format(folder))
            return
        if not U.ask(u'{0} new families in {1}.\nEach is opened in the background, '
                     u'checked, versioned and published.\nPublish them now?'
                     .format(len(new), folder)):
            return
        try:
            with forms.ProgressBar(title=u'Publishing {value} of {max_value}', cancellable=True) as pb:
                def progress(i, n, fid):
                    pb.update_progress(i, n)

                counts, report = publish.publish_folder(self.app, self.backend, folder,
                                                        progress, lambda: pb.cancelled)
        except Exception as ex:
            log.write(u'batch publish', exc=True)
            U.error(u'{0}'.format(ex))
            return
        U.info(strings.BATCH_DONE.format(counts['published'], counts['skipped'],
                                         counts['failed'], report))
        self.Close()
