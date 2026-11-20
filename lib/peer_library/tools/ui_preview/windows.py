# -*- coding: utf-8 -*-
"""The other library windows, off-screen: open and render only, nothing is sent."""
from __future__ import print_function
import os
import traceback

execfile(os.path.join(os.path.dirname(__file__), 'stubs.py'))   # noqa: F821
be, cfg = backend(OUT)   # noqa: F821


def run(name, make):
    try:
        win = make()
        show(win)
        snap(win, OUT, name)   # noqa: F821
        st = getattr(win, 'status_text', None)
        print(name, '-', st.Text if st is not None else u'')
        win.Close()
        pump(100)
    except Exception:
        print('FAILED', name)
        traceback.print_exc()


def keys():
    ns = {'__name__': 'keys_preview', '__file__': os.path.join(PANEL, 'Keys.smartbutton', 'script.py')}
    execfile(ns['__file__'], ns)   # noqa: F821
    return ns['KeysWindow'](be)


run('keys.png', keys)
from peer_library.ui_inbox import InboxWindow  # noqa: E402
run('inbox.png', lambda: InboxWindow(os.path.join(PANEL, 'Inbox.smartbutton', 'InboxWindow.xaml'), be,
                                     os.path.join(PANEL, 'Publish.smartbutton', 'PublishWindow.xaml'),
                                     FakeApp()))
from peer_library.ui_publish import PublishWindow  # noqa: E402
first_id = be.get_index()['families'][0]['id']
run('publish.png', lambda: PublishWindow(os.path.join(PANEL, 'Publish.smartbutton', 'PublishWindow.xaml'),
                                         FakeApp(), be, {'family_id': first_id}))
from peer_library.ui_propose import ProposeWindow  # noqa: E402
run('propose.png', lambda: ProposeWindow(os.path.join(PANEL, 'Propose.smartbutton', 'ProposeWindow.xaml'),
                                         FakeDoc(), None, be, preset_file=r'C:\Temp\My_Family.rfa'))
from peer_library import session, strings  # noqa: E402
run('login.png', lambda: session.LoginWindow(be))
from peer_library.ui_dialogs import EditInfoWindow, TextWindow  # noqa: E402
run('request.png', lambda: TextWindow(strings.TITLE_REQUEST, strings.REQUEST_HEAD, strings.REQUEST_HINT,
                                      strings.REQUEST_L1, strings.REQUEST_L2, strings.BTN_SEND,
                                      lambda a, b: None))
run('edit_info.png', lambda: EditInfoWindow(be.get_index()['families'][0]))
print('message boxes:', MSGS or 'none')
