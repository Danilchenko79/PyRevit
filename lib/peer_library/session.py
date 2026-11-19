# -*- coding: utf-8 -*-
"""Opening the library from a button: storage + (for the service) sign-in.

connect(cfg) -> backend or None
    local folder : the folder backend.
    service      : no key -> a sent access request is checked first (approved =
                   signed in automatically), otherwise the sign-in window
                   (paste a key, or request access). With a key: checked once
                   per button press (name / role / last check refreshed);
                   a revoked key asks again; no connection = work offline.
"""

import os

from pyrevit import forms

from peer_library import config, keystore, log, strings
from peer_library.backend_base import AccessError, LibraryError, OfflineError

LOGIN_XAML = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          'PEER.tab', 'Library.panel', 'Library.smartbutton', 'LoginWindow.xaml')


class LoginWindow(forms.WPFWindow):

    def __init__(self, backend, message=u''):
        forms.WPFWindow.__init__(self, LOGIN_XAML)
        self.backend = backend
        self.ok = False
        self.status_text.Text = message
        req = keystore.load_request()
        if req:
            self.name_box.Text = req[2]
        if not self.name_box.Text:
            self.name_box.Text = config.load().get('user') or u''
        self.key_box.Focus()

    def on_key(self, sender, args):
        from System.Windows.Input import Key
        if args.Key == Key.Escape:
            self.Close()
        elif args.Key == Key.Enter and self.key_box.IsKeyboardFocusWithin:
            self.on_ok(None, None)

    def on_cancel(self, sender, args):
        self.Close()

    def on_ok(self, sender, args):
        key = (self.key_box.Password or u'').strip()
        if not key.startswith('peer_'):
            self.status_text.Text = u'The key starts with peer_ - paste it as you got it.'
            return
        try:
            info = self.backend.sign_in(key)
        except AccessError:
            self.status_text.Text = u'This key is not valid. Ask a library admin for a new one.'
            return
        except OfflineError:
            self.status_text.Text = u'No connection to the library service. Check the internet.'
            return
        except Exception as ex:
            log.write(u'sign in', exc=True)
            self.status_text.Text = u'{0}'.format(ex)
            return
        keystore.forget_request()
        self.ok = True
        forms.alert(u'Hello, {0}!'.format(info.get('name')), title=strings.APP)
        self.Close()

    def on_request(self, sender, args):
        name = (self.name_box.Text or u'').strip()
        if len(name) < 2:
            self.status_text.Text = u'Write your name.'
            return
        try:
            r = self.backend.request_access(name, (self.note_box.Text or u'').strip())
        except OfflineError:
            self.status_text.Text = u'No connection to the library service. Check the internet.'
            return
        except LibraryError as ex:
            self.status_text.Text = u'{0}'.format(ex)
            return
        keystore.save_request(r['id'], r['token'], name)
        self.status_text.Text = (u'Request sent. When an admin approves it, press Library again - '
                                 u'you will be signed in automatically.')
        self.request_btn.IsEnabled = False


def login(backend, message=u''):
    win = LoginWindow(backend, message)
    win.ShowDialog()
    return win.ok


def pick_up_request(backend):
    """(signed_in, message) for a request sent earlier from this computer."""
    req = keystore.load_request()
    if not req:
        return False, u''
    try:
        st = backend.access_status(req[0], req[1])
    except OfflineError:
        return False, u'No connection - your access request is still waiting.'
    except (AccessError, LibraryError):
        keystore.forget_request()
        return False, u'Your access request expired - send a new one.'
    if st.get('status') == 'delivered' and st.get('key'):
        try:
            backend.sign_in(st['key'])
        except Exception:
            log.write(u'pick up key', exc=True)
            return False, u'The key could not be saved - ask an admin.'
        keystore.forget_request()
        forms.alert(u'Access approved. Welcome, {0}!'.format(st.get('name')), title=strings.APP)
        return True, u''
    if st.get('status') == 'rejected':
        keystore.forget_request()
        return False, u'Your access request was declined. Ask a library admin.'
    return False, u'Your access request ({0}) is waiting for an admin.'.format(req[2] or u'sent')


def connect(cfg=None):
    cfg = cfg or config.load()
    backend = config.make_backend(cfg)
    if backend.kind != 'http':
        return backend
    if not backend.has_key():
        ok, msg = pick_up_request(backend)
        if ok:
            return backend
        return backend if login(backend, msg) else None
    try:
        backend.auth()
    except OfflineError:
        pass                         # cache + 14-day grace decide later
    except AccessError:
        keystore.forget()
        backend.key = None
        msg = u'Your library key is not valid any more. Paste a new one or request access.'
        return backend if login(backend, msg) else None
    return backend


def sign_out():
    keystore.forget()
    keystore.forget_request()
    config.save_local(last_ok=u'', role=u'user')
