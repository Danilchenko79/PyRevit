# -*- coding: utf-8 -*-
"""Opening the library from a button: storage + (for the service) sign-in.

connect(cfg, login_xaml) -> backend or None
    local folder : the folder backend.
    service      : asks for the key if there is none; checks it once per
                   button press (also refreshes name / role / last check);
                   a revoked key asks again; no connection = work offline.
"""

import os

from pyrevit import forms

from peer_library import config, keystore, log, strings
from peer_library.backend_base import AccessError, OfflineError

LOGIN_XAML = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          'PEER.tab', 'Library.panel', 'Library.pushbutton', 'LoginWindow.xaml')


class LoginWindow(forms.WPFWindow):

    def __init__(self, backend, message=u''):
        forms.WPFWindow.__init__(self, LOGIN_XAML)
        self.backend = backend
        self.ok = False
        self.status_text.Text = message
        self.key_box.Focus()

    def on_key(self, sender, args):
        from System.Windows.Input import Key
        if args.Key == Key.Escape:
            self.Close()
        elif args.Key == Key.Enter:
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
        self.ok = True
        forms.alert(u'Hello, {0}! ({1})'.format(info.get('name'), info.get('role')),
                    title=strings.APP)
        self.Close()


def login(backend, message=u''):
    win = LoginWindow(backend, message)
    win.ShowDialog()
    return win.ok


def connect(cfg=None):
    cfg = cfg or config.load()
    backend = config.make_backend(cfg)
    if backend.kind != 'http':
        return backend
    if not backend.has_key():
        return backend if login(backend) else None
    try:
        backend.auth()
    except OfflineError:
        pass                         # cache + 14-day grace decide later
    except AccessError:
        keystore.forget()
        backend.key = None
        msg = u'Your library key is not valid any more. Paste a new one.'
        return backend if login(backend, msg) else None
    return backend


def sign_out():
    keystore.forget()
    config.save_local(last_ok=u'', role=u'user')
