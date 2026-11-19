# -*- coding: utf-8 -*-
__title__ = "Publish"
__author__ = "Dima D"
__doc__ = """LIBRARY ADMINS ONLY
The only way to put a family into the library. Checks the file (Revit 2024
format, name, size), opens a copy in the background (no CAD imports, has
types, category), writes PEER_Version into every type, makes a preview,
saves compact and updates the index and What's new.

"Publish a sorted folder" imports a whole <group>/<ID>.rfa folder at once.
Run it from Revit 2024 only.
"""

import os

from pyrevit import HOST_APP, forms

from peer_library import config, log, strings

XAML = os.path.join(os.path.dirname(__file__), 'PublishWindow.xaml')


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    """Hidden for users - the storage checks the role anyway."""
    try:
        if config.load()['role'] != 'admin':
            ui_button_cmp.visible = False
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
    from peer_library.ui_publish import PublishWindow
    PublishWindow(XAML, HOST_APP.app, config.make_backend(cfg)).ShowDialog()


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        log.write(u'Publish button', exc=True)
        forms.alert(u'{0}\n\nDetails: {1}'.format(ex, log.log_file()), title=strings.APP)
