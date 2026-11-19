# -*- coding: utf-8 -*-
__title__ = "Propose\nfamily"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Sends a family to the library admins for review: a file from disk, the
family of the selected element (exported without changing the project) or
the saved family open in the editor. Automatic checks are shown and sent
along but do not block sending.

The answer (accepted / rejected with a comment) is in
Library -> My proposals.
"""

import os

from pyrevit import forms, revit

from peer_library import config, log, strings

XAML = os.path.join(os.path.dirname(__file__), 'ProposeWindow.xaml')


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(strings.NO_DOC, title=strings.APP)
        return
    cfg = config.load()
    if not config.is_configured(cfg):
        forms.alert(strings.NOT_CONFIGURED + u'\n\n(Shift+Click on Library)', title=strings.APP)
        return
    from peer_library.ui_propose import ProposeWindow
    ProposeWindow(XAML, doc, revit.uidoc, config.make_backend(cfg)).ShowDialog()


try:
    main()
except Exception as ex:
    log.write(u'Propose button', exc=True)
    forms.alert(u'{0}\n\nDetails: {1}'.format(ex, log.log_file()), title=strings.APP)
