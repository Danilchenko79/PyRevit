# -*- coding: utf-8 -*-
__title__ = "Keys"
__author__ = "Dima D"
__doc__ = """LIBRARY ADMINS ONLY (library service)
Personal library keys: give a key to a person (shown once - copy it and
send it privately), see when each key was last used, revoke a key when
someone leaves. A revoked key stops working at once.
"""

import os

import clr
from pyrevit import forms

from peer_library import config, log, session, strings

clr.AddReference('System.Data')
from System.Data import DataTable  # noqa: E402
from System.Windows import Visibility  # noqa: E402

XAML = os.path.join(os.path.dirname(__file__), 'KeysWindow.xaml')
COLUMNS = ('id', 'name', 'role', 'state', 'last_used', 'created')


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    try:
        cfg = config.load()
        if cfg['role'] != 'admin' or cfg['backend'] != 'http':
            ui_button_cmp.visible = False
    except Exception:
        pass
    return True


class KeysWindow(forms.WPFWindow):

    def __init__(self, backend):
        forms.WPFWindow.__init__(self, XAML)
        self.backend = backend
        self.rows = []
        self.requests = []
        self.role_box.Items.Add('user')
        self.role_box.Items.Add('admin')
        self.role_box.SelectedIndex = 0
        self.refresh()

    def on_key(self, sender, args):
        from System.Windows.Input import Key
        if args.Key == Key.Escape:
            self.Close()

    def refresh(self):
        self.refresh_requests()
        try:
            self.rows = self.backend.list_keys()
        except Exception as ex:
            self.status_text.Text = u'{0}'.format(ex)
            return
        table = DataTable()
        for c in COLUMNS:
            table.Columns.Add(c)
        for r in self.rows:
            table.Rows.Add(r['id'], r['name'], r['role'], u'active' if r['active'] else u'revoked',
                           (r.get('last_used') or u'never').replace(u'T', u' '),
                           (r.get('created') or u'').replace(u'T', u' '))
        self.keys_list.ItemsSource = table.DefaultView
        self.status_text.Text = u'{0} active key(s)'.format(sum(1 for r in self.rows if r['active']))

    def on_refresh(self, sender, args):
        self.refresh()

    # ---- access requests ------------------------------------------------------
    def refresh_requests(self):
        try:
            self.requests = self.backend.list_access_requests()
        except Exception as ex:
            log.write(u'access requests: {0}'.format(ex))
            self.requests = []
        self.requests_list.Items.Clear()
        for r in self.requests:
            note = u'  -  {0}'.format(r['note']) if r.get('note') else u''
            self.requests_list.Items.Add(u'{0}{1}   ({2})'.format(
                r['name'], note, (r.get('created') or u'')[:16].replace(u'T', u' ')))
        self.requests_box.Visibility = Visibility.Visible if self.requests else Visibility.Collapsed
        self.requests_title.Text = u'{0} person(s) ask for access'.format(len(self.requests))
        if self.requests:
            self.requests_list.SelectedIndex = 0

    def _resolve(self, approve, role='user'):
        i = self.requests_list.SelectedIndex
        if i < 0 or i >= len(self.requests):
            self.status_text.Text = u'Select a request.'
            return
        r = self.requests[i]
        if role == 'admin' and not forms.alert(u'Give ADMIN rights to {0}?'.format(r['name']),
                                               yes=True, no=True):
            return
        try:
            if approve:
                self.backend.approve_access(r['id'], role)
            else:
                self.backend.reject_access(r['id'])
        except Exception as ex:
            self.status_text.Text = u'{0}'.format(ex)
            return
        self.refresh()
        self.status_text.Text = (u'{0}: approved - signed in the next time they press Library.'
                                 if approve else u'{0}: declined.').format(r['name'])

    def on_approve_user(self, sender, args):
        self._resolve(True, 'user')

    def on_approve_admin(self, sender, args):
        self._resolve(True, 'admin')

    def on_decline(self, sender, args):
        self._resolve(False)

    def on_add(self, sender, args):
        name = (self.name_box.Text or u'').strip()
        if not name:
            self.status_text.Text = u'Write the name of the person.'
            return
        role = self.role_box.SelectedItem or 'user'
        if role == 'admin' and not forms.alert(u'Give ADMIN rights to {0}? Admins publish and '
                                               u'manage keys.'.format(name), yes=True, no=True):
            return
        try:
            k = self.backend.add_key(name, role)
        except Exception as ex:
            log.write(u'add key', exc=True)
            self.status_text.Text = u'{0}'.format(ex)
            return
        self.new_key.Text = k['key']
        self.new_panel.Visibility = Visibility.Visible
        self.name_box.Text = u''
        self.refresh()

    def on_copy(self, sender, args):
        from System.Windows import Clipboard
        if self.new_key.Text:
            Clipboard.SetText(self.new_key.Text)
            self.status_text.Text = u'Copied.'

    def on_revoke(self, sender, args):
        i = self.keys_list.SelectedIndex
        if i < 0 or i >= len(self.rows):
            self.status_text.Text = u'Select a key in the list.'
            return
        r = self.rows[i]
        if not r['active']:
            return
        if not forms.alert(u'Revoke the key of {0}? It stops working at once.'.format(r['name']),
                           yes=True, no=True):
            return
        try:
            self.backend.revoke_key(r['id'])
        except Exception as ex:
            self.status_text.Text = u'{0}'.format(ex)
            return
        self.refresh()


def main():
    cfg = config.load()
    if cfg['backend'] != 'http':
        forms.alert(u'Keys are used with the library service only.', title=strings.APP)
        return
    backend = session.connect(cfg)
    if backend is None:
        return
    if backend.role != 'admin':
        forms.alert(strings.NOT_ADMIN, title=strings.APP)
        return
    KeysWindow(backend).ShowDialog()


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        log.write(u'Keys button', exc=True)
        forms.alert(u'{0}\n\nDetails: {1}'.format(ex, log.log_file()), title=strings.APP)
