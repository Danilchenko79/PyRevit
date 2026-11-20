# -*- coding: utf-8 -*-
"""Account window: who is signed in on this computer, the key state, the PEER
version; sign in / request access / check now / sign out.

The same key opens the library and (when the office turns the lock on) every
PEER button. Sign in / out shows or hides the PEER panels at once.
"""

import os

from pyrevit import forms

from peer_library import access, config, keystore, log, session, strings, version
from peer_library import ui_common as U

XAML = os.path.join(version.ext_dir(), 'PEER.tab', 'Account.panel', 'Account.pushbutton',
                    'AccountWindow.xaml')

# status code -> (label, text colour, background) - never colour alone, always the label
CHIPS = {
    access.OK: (strings.ACC_ST_OK, '#14532D', '#DCFCE7'),
    access.STALE: (strings.ACC_ST_STALE, '#7C2D12', '#FFEDD5'),
    access.NONE: (strings.ACC_ST_NONE, '#44403C', '#F5F5F4'),
    access.REQUESTED: (strings.ACC_ST_REQUESTED, '#581C87', '#F3E8FF'),
    access.OFF: (strings.ACC_ST_OFF, '#44403C', '#F5F5F4'),
}


class AccountWindow(forms.WPFWindow):

    def __init__(self, xaml=None, check=True):
        forms.WPFWindow.__init__(self, xaml or XAML)
        self.check = u''
        self.changed = False
        if check:
            self._check()
        self.render()

    # ---- state -------------------------------------------------------------
    def _check(self):
        try:
            _, self.check = access.check_now()
        except Exception as ex:
            log.write(u'account check', exc=True)
            self.check = u'{0}'.format(ex)

    def render(self):
        cfg = config.load()
        st = access.status(cfg)
        label, fg, bg = CHIPS.get(st.code, CHIPS[access.NONE])
        if self.check == 'revoked':
            label, fg, bg = strings.ACC_ST_REVOKED, '#7F1D1D', '#FEE2E2'
        self.chip_text.Text = label
        self.chip_text.Foreground = U.brush(fg)
        self.chip.Background = U.brush(bg)
        self.chip.BorderBrush = U.brush(fg)
        self.status_text.Text = access.describe(st, self.check)
        key = keystore.load()
        self.name_text.Text = st.name if st.signed_in else strings.ACC_DASH
        self.role_text.Text = (strings.ACC_ROLE_ADMIN if st.role == 'admin' else strings.ACC_ROLE_USER) \
            if st.signed_in else strings.ACC_DASH
        self.key_text.Text = keystore.mask(key) if key else strings.ACC_DASH
        self.last_text.Text = st.last_ok.replace(u'T', u' ')[:16] if st.last_ok else strings.ACC_DASH
        self.version_text.Text = version.text()
        self.service_text.Text = (cfg.get('url') or u'').replace(u'https://', u'') or strings.ACC_DASH
        signed = bool(key)
        off = st.code == access.OFF
        self.signin_btn.IsEnabled = not off
        self.signin_btn.Content = strings.ACC_BTN_CHANGE if signed else strings.ACC_BTN_SIGNIN
        self.check_btn.IsEnabled = signed and not off
        self.signout_btn.IsEnabled = signed
        return st

    def _after_change(self):
        self.changed = True
        st = self.render()
        try:
            access.apply_ribbon(st)
        except Exception:
            log.write(u'account: ribbon', exc=True)

    # ---- buttons -------------------------------------------------------------
    def on_key(self, sender, args):
        from System.Windows.Input import Key
        if args.Key == Key.Escape:
            self.Close()

    def on_close(self, sender, args):
        self.Close()

    def on_signin(self, sender, args):
        backend = config.make_backend()
        if not backend.has_key():
            try:
                ok, msg = session.pick_up_request(backend)
            except Exception as ex:
                log.write(u'account: pick up', exc=True)
                ok, msg = False, u'{0}'.format(ex)
            if ok:
                self.check = 'ok'
                self._after_change()
                return
        else:
            msg = u''
        if session.login(backend, msg):
            self.check = 'ok'
        self._after_change()

    def on_check(self, sender, args):
        self._check()
        self._after_change()

    def on_signout(self, sender, args):
        if not U.ask(strings.ACC_SIGNOUT_ASK, strings.ACC_TITLE):
            return
        session.sign_out()
        self.check = u''
        self._after_change()


def show(check=True):
    win = AccountWindow(check=check)
    win.ShowDialog()
    return win.changed
