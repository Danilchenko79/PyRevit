# -*- coding: utf-8 -*-
__title__ = "Inbox"
__author__ = "Dima D"
__doc__ = """LIBRARY ADMINS ONLY
Families proposed by colleagues: author, date, reason, automatic checks,
screenshot. Open in the editor (work folder %LOCALAPPDATA%/PEER/Work),
improve and save there, then Publish - or Reject with a comment.
The author sees the result in Library -> My proposals.
"""

import os

from pyrevit import HOST_APP, forms

from peer_library import config, log, session, strings

HERE = os.path.dirname(__file__)
XAML = os.path.join(HERE, 'InboxWindow.xaml')
from peer_library import version as _version
PUBLISH_XAML = os.path.join(_version.bundle_dir('Publish.smartbutton'), 'PublishWindow.xaml')


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    """Hidden for users; shows the number of waiting proposals for admins."""
    try:
        cfg = config.load()
        if cfg['role'] != 'admin':
            ui_button_cmp.visible = False
            return True
        if cfg['backend'] == 'local' and config.is_configured(cfg):   # no network at Revit start
            n = sum(1 for p in config.make_backend(cfg).list_proposals()
                    if p.get('status') == 'pending')
            if n:
                ui_button_cmp.set_title(u'Inbox\n({0})'.format(n))
    except Exception:
        pass
    return True


def main():
    cfg = config.load()
    if cfg['role'] != 'admin':
        forms.alert(strings.NOT_ADMIN, title=strings.APP)
        return
    if not config.is_configured(cfg):
        forms.alert(strings.NOT_CONFIGURED, title=strings.APP)
        return
    from peer_library.ui_inbox import InboxWindow
    backend = session.connect(cfg)
    if backend is None:
        return
    if backend.role != 'admin':
        forms.alert(strings.NOT_ADMIN, title=strings.APP)
        return
    win = InboxWindow(XAML, backend, PUBLISH_XAML, HOST_APP.app)
    win.ShowDialog()
    if win.open_path:
        HOST_APP.uiapp.OpenAndActivateDocument(win.open_path)


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        log.write(u'Inbox button', exc=True)
        forms.alert(u'{0}\n\nDetails: {1}'.format(ex, log.log_file()), title=strings.APP)
