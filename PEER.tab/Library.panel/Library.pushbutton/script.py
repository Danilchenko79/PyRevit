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

Shift+Click: library folder, open the cache or the log.
"""

import os

from pyrevit import EXEC_PARAMS, forms, revit

from peer_library import config, loader, log, strings
from peer_library.ui_library import LibraryWindow

XAML = os.path.join(os.path.dirname(__file__), 'LibraryWindow.xaml')


def pick_root(cfg):
    folder = forms.pick_folder(title=strings.PICK_ROOT)
    if not folder:
        return None
    if not os.path.isdir(os.path.join(folder, 'PEER-Library')) and \
            os.path.basename(folder.rstrip('\\/')) == 'PEER-Library':
        folder = os.path.dirname(folder.rstrip('\\/'))
    return config.save_local(root=folder, backend='local')


def settings():
    cfg = config.load()
    opts = [u'Library folder: {0}'.format(cfg['root'] or u'(not set)'),
            u'Open the local cache folder',
            u'Open the log file']
    pick = forms.CommandSwitchWindow.show(opts, message=strings.APP)
    if pick == opts[0]:
        pick_root(cfg)
    elif pick == opts[1]:
        if not os.path.isdir(cfg['cache']):
            os.makedirs(cfg['cache'])
        os.startfile(cfg['cache'])
    elif pick == opts[2]:
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
        cfg = pick_root(cfg)
        if not cfg or not config.is_configured(cfg):
            return
    win = LibraryWindow(XAML, doc, revit.uidoc, config.make_backend(cfg), cfg)
    win.ShowDialog()
    if win.place_symbol is not None:
        try:
            loader.request_placement(revit.uidoc, win.place_symbol)
        except Exception as ex:
            forms.alert(u'{0}'.format(ex), title=strings.APP)


try:
    main()
except Exception as ex:
    log.write(u'Library button', exc=True)
    forms.alert(u'{0}\n\nDetails: {1}'.format(ex, log.log_file()), title=strings.APP)
