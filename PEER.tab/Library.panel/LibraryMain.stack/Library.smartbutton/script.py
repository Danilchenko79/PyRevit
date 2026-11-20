# -*- coding: utf-8 -*-
__title__ = "Library"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Company family library: groups, search, previews, and the status of every
family against the open project (not in project / up to date / older
version / no version). Load, update or load-and-place a family; for
families with a type catalog only the ticked types are loaded.
Values changed in the project are kept unless you tick the overwrite box.

Tabs: What's new (feed of published families) and My proposals.
First start: paste your personal library key (from an admin).

Shift+Click: change key, sign out, library address / folder, cache, log.
"""

import os

from pyrevit import EXEC_PARAMS, forms, revit

from peer_library import config, keystore, loader, log, session, strings

XAML = os.path.join(os.path.dirname(__file__), 'LibraryWindow.xaml')


def pick_root():
    folder = forms.pick_folder(title=strings.PICK_ROOT)
    if not folder:
        return None
    if os.path.basename(folder.rstrip('\\/')) == 'PEER-Library':
        folder = os.path.dirname(folder.rstrip('\\/'))
    return config.save_local(root=folder, backend='local')


def settings():
    cfg = config.load()
    key = keystore.load()
    if cfg['backend'] == 'http':
        where = u'Service: {0}'.format(cfg['url'] or u'(not set)')
    else:
        where = u'Folder: {0}'.format(cfg['root'] or u'(not set)')
    opts = [u'Change my key ({0})'.format(keystore.mask(key) or u'none'),
            u'Sign out on this computer',
            u'Library service address...',
            u'Use a folder instead (office trial)...',
            u'Open the local cache folder',
            u'Open the log file']
    pick = forms.CommandSwitchWindow.show(opts, message=u'{0}\n{1}'.format(strings.APP, where))
    if pick == opts[0]:
        if cfg['backend'] != 'http':
            forms.alert(u'Keys are used with the library service only.', title=strings.APP)
            return
        session.login(config.make_backend(cfg))
    elif pick == opts[1]:
        session.sign_out()
        forms.alert(u'Signed out. The next start asks for the key.', title=strings.APP)
    elif pick == opts[2]:
        url = forms.ask_for_string(default=cfg['url'] or u'https://',
                                   prompt=u'Address of the library service (https://...)',
                                   title=strings.APP)
        if url and url.strip().startswith('https://'):
            config.save_local(url=url.strip().rstrip('/'), backend='http')
    elif pick == opts[3]:
        pick_root()
    elif pick == opts[4]:
        if not os.path.isdir(cfg['cache']):
            os.makedirs(cfg['cache'])
        os.startfile(cfg['cache'])
    elif pick == opts[5]:
        if os.path.exists(log.log_file()):
            os.startfile(log.log_file())


def main():
    if EXEC_PARAMS.config_mode:
        settings()
        return
    doc = revit.doc
    if doc is None:
        forms.alert(strings.NO_DOC, title=strings.APP)
        return
    if doc.IsFamilyDocument:
        forms.alert(strings.FAMILY_DOC, title=strings.APP)
        return
    cfg = config.load()
    if not config.is_configured(cfg):
        forms.alert(strings.NOT_CONFIGURED, title=strings.APP)
        cfg = pick_root()
        if not cfg or not config.is_configured(cfg):
            return
    backend = session.connect(cfg)
    if backend is None:
        return
    from peer_library.ui_library import LibraryWindow
    win = LibraryWindow(XAML, doc, revit.uidoc, backend, config.load())
    win.ShowDialog()
    if win.place_symbol is not None:
        try:
            loader.request_placement(revit.uidoc, win.place_symbol)
        except Exception as ex:
            forms.alert(u'{0}'.format(ex), title=strings.APP)


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    """Hidden where the library is not set up (no service address / folder)."""
    try:
        if not config.panel_visible():
            ui_button_cmp.visible = False
    except Exception:
        pass
    return True


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        log.write(u'Library button', exc=True)
        forms.alert(u'{0}\n\nDetails: {1}'.format(ex, log.log_file()), title=strings.APP)
