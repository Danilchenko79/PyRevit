# -*- coding: utf-8 -*-
"""Account window in every state, off-screen. Nothing is read from or sent to
the service and the real key is not touched: the state is faked."""
from __future__ import print_function
import os
import traceback

execfile(os.path.join(os.path.dirname(__file__), 'stubs.py'))   # noqa: F821

from peer_library import access, keystore, ui_account, version  # noqa: E402

XAML = os.path.join(EXT, 'PEER.tab', 'Account.panel', 'Account.pushbutton', 'AccountWindow.xaml')  # noqa: F821
FAKE_KEY = u'peer_Ab3dE6gH9jK2mN5pQ8rS1tU4vW7xYz'
LONG = u'Alexander-Konstantin Wolfeschlegelstein (structural engineering, remote office)'

STATES = [
    ('account_ok.png', access.Status(access.OK, True, 14, u'Dima D', 'admin', '2026-11-20T09:15:00'), True, 'ok'),
    ('account_offline.png', access.Status(access.OK, True, 9, LONG, 'user', '2026-11-15T18:02:00'), True, 'offline'),
    ('account_stale.png', access.Status(access.STALE, True, 0, u'Dima D', 'user', '2026-10-30T08:00:00'), True, 'offline'),
    ('account_none.png', access.Status(access.NONE, False), False, 'no key'),
    ('account_none_locked.png', access.Status(access.NONE, True), False, 'no key'),
    ('account_requested.png', access.Status(access.REQUESTED, True), False, 'no key'),
    ('account_revoked.png', access.Status(access.NONE, True), False, 'revoked'),
    ('account_off.png', access.Status(access.OFF, False), False, 'off'),
    ('account_loader_signed.png', access.Status(access.OK, True, 14, u'Anna', 'user', '2026-11-20T09:15:00'), True, 'ok'),
]

for name, st, has_key, check in STATES:
    try:
        access.status = lambda cfg=None, _st=st: _st
        keystore.load = lambda _k=has_key: FAKE_KEY if _k else None
        version.is_loader = lambda folder=None, _n=name: 'loader' in _n
        win = ui_account.AccountWindow(XAML, check=False)
        win.check = check
        win.render()
        show(win, 300)      # noqa: F821
        snap(win, OUT, name)   # noqa: F821
        print(name, '|', win.chip_text.Text, '|', win.status_text.Text)
        print('   buttons:', win.signin_btn.Content, win.signin_btn.IsEnabled,
              win.check_btn.IsEnabled, win.signout_btn.IsEnabled)
        win.Close()
        pump(50)            # noqa: F821
    except Exception:
        print('FAILED', name)
        traceback.print_exc()
