# -*- coding: utf-8 -*-
"""Admin inbox: proposals with author, date and check results.
Open in the editor (work folder), publish (publish window prefilled), reject."""

import os

from pyrevit import forms

from System.Windows import Thickness, TextWrapping  # noqa: E402
from System.Windows.Controls import Orientation, StackPanel, TextBlock  # noqa: E402
from System.Windows.Input import Cursors, Key  # noqa: E402

from peer_library import config, groups, loader, log, strings  # noqa: E402
from peer_library import ui_common as U  # noqa: E402

LOOK = {'pending': (strings.P_PENDING, loader.UNKNOWN),
        'accepted': (strings.P_ACCEPTED, loader.CURRENT),
        'rejected': (strings.P_REJECTED, loader.NEWER)}


def work_folder(proposal_id):
    return os.path.join(config.work_dir(), proposal_id)


class InboxWindow(forms.WPFWindow):

    def __init__(self, xaml_path, backend, publish_xaml, app):
        forms.WPFWindow.__init__(self, xaml_path)
        self.backend, self.publish_xaml, self.app = backend, publish_xaml, app
        self.items = []
        self.open_path = None
        self.Title = strings.TITLE_INBOX
        self._fill()

    def on_key(self, sender, args):
        if args.Key == Key.Escape:
            self.Close()

    def on_done(self, sender, args):
        self._fill()

    def _fill(self):
        self.list.Items.Clear()
        try:
            self.items = self.backend.list_proposals(include_done=bool(self.show_done.IsChecked))
        except Exception as ex:
            self.status_text.Text = u'{0}'.format(ex)
            self.items = []
        self.items.sort(key=lambda p: (p.get('status') != 'pending', p.get('sent', u'')))
        for p in self.items:
            sp = StackPanel()
            sp.Margin = Thickness(6, 4, 6, 4)
            head = StackPanel()
            head.Orientation = Orientation.Horizontal
            label, code = LOOK.get(p.get('status'), LOOK['pending'])
            ch = U.chip(label, code)
            ch.Margin = Thickness(0, 0, 8, 0)
            head.Children.Add(ch)
            kind = TextBlock()
            kind.Text = strings.KIND_LABELS.get(p.get('kind') or 'new', strings.KIND_NEW) + u':  '
            kind.Foreground = U.brush(U.MUTED)
            head.Children.Add(kind)
            t = TextBlock()
            t.Text = p.get('name') or p['id']
            head.Children.Add(t)
            sp.Children.Add(head)
            s = TextBlock()
            s.Foreground = U.brush(U.MUTED)
            s.Text = u'{0} · {1}'.format(p.get('author', u''),
                                             (p.get('sent') or u'')[:16].replace(u'T', u' '))
            sp.Children.Add(s)
            self.list.Items.Add(sp)
        pending = sum(1 for p in self.items if p.get('status') == 'pending')
        self.status_text.Text = u'{0} waiting for review'.format(pending)
        self._show(None)

    def _current(self):
        i = self.list.SelectedIndex
        return self.items[i] if 0 <= i < len(self.items) else None

    def on_select(self, sender, args):
        self._show(self._current())

    def _show(self, p):
        has = p is not None
        pending = has and p.get('status') == 'pending'
        fileless = has and p.get('kind') in ('request', 'issue')
        self.open_btn.IsEnabled = pending and not fileless
        self.publish_btn.IsEnabled = pending and not fileless
        self.done_btn.IsEnabled = pending and fileless
        self.reject_btn.IsEnabled = pending
        if not has:
            for t in (self.d_name, self.d_meta, self.d_reason, self.d_checks, self.d_work):
                t.Text = u''
            self.d_shot.Source = None
            return
        self.d_name.Text = p.get('name') or p['id']
        kind = strings.KIND_LABELS.get(p.get('kind') or 'new', strings.KIND_NEW)
        self.d_meta.Text = u'{0} · {1} · {2} · {3} {4}\nRevit {5}'.format(
            p.get('author', u''), (p.get('sent') or u'')[:16].replace(u'T', u' '),
            groups.title(p.get('group')), kind, p.get('family_id') or u'', p.get('revit') or u'?')
        self.d_reason.Text = p.get('reason') or u''
        checks = [u'{0}: {1}'.format(c.get('level', u'').upper(), c.get('text', u''))
                  for c in p.get('checks') or [] if c.get('level') != 'info']
        self.d_checks.Text = u'\n'.join(checks) or u'No problems found'
        self.comment_box.Text = p.get('comment') or u''
        work = work_folder(p['id'])
        self.d_work.Text = u'Work folder: {0}'.format(work) if os.path.isdir(work) else u''
        shot = None
        if p.get('has_screenshot'):
            # separate folder: never overwrite the admin's edited family.rfa in the work folder
            preview = work + u'.preview'
            shot = os.path.join(preview, 'screenshot.png')
            if not os.path.isfile(shot):
                try:
                    self.backend.download_proposal(p['id'], preview)
                except Exception:
                    log.write(u'inbox preview {0}'.format(p['id']), exc=True)
        self.d_shot.Source = U.bitmap(shot, 600) if shot and os.path.isfile(shot) else None

    def _work_file(self, p):
        work = work_folder(p['id'])
        path = os.path.join(work, 'family.rfa')
        if not os.path.isfile(path):
            self.backend.download_proposal(p['id'], work)
        return path

    def on_open(self, sender, args):
        p = self._current()
        if p is None:
            return
        try:
            self.open_path = self._work_file(p)
        except Exception as ex:
            U.error(u'{0}'.format(ex))
            return
        self.Close()          # the family is opened after the window closes

    def on_publish(self, sender, args):
        p = self._current()
        if p is None:
            return
        try:
            path = self._work_file(p)
        except Exception as ex:
            U.error(u'{0}'.format(ex))
            return
        from peer_library.ui_publish import PublishWindow
        prefill = {'file': path, 'name': p.get('name'), 'group': p.get('group'),
                   'family_id': p.get('family_id') if p.get('kind') == 'fix' else None,
                   'reason': p.get('reason'), 'proposal_id': p['id']}
        if p.get('kind') != 'fix':
            prefill['family_id'] = None
        win = PublishWindow(self.publish_xaml, self.app, self.backend, prefill)
        if p.get('kind') != 'fix':
            # new family: ID proposed by the author (file name), never the work file "family"
            proposed = p.get('family_id') or u''
            if proposed and proposed.lower() != u'family':
                win.id_box.Text = proposed
        win.ShowDialog()
        if win.published:
            self._fill()

    def on_reject(self, sender, args):
        p = self._current()
        if p is None:
            return
        comment = (self.comment_box.Text or u'').strip()
        if not comment:
            self.status_text.Text = strings.REJECT_NEED
            self.comment_box.Focus()
            return
        self.Cursor = Cursors.Wait
        try:
            self.backend.resolve_proposal(p['id'], 'rejected', comment)
        except Exception as ex:
            log.write(u'reject', exc=True)
            U.error(u'{0}'.format(ex))
            return
        finally:
            self.Cursor = None
        self._fill()

    def on_done_req(self, sender, args):
        """Request / problem handled (family published or fixed): close it with a note."""
        p = self._current()
        if p is None:
            return
        comment = (self.comment_box.Text or u'').strip() or u'Done'
        try:
            self.backend.resolve_proposal(p['id'], 'accepted', comment)
        except Exception as ex:
            log.write(u'mark done', exc=True)
            U.error(u'{0}'.format(ex))
            return
        self._fill()
