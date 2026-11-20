# -*- coding: utf-8 -*-
__title__ = "New\nproject"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Creates a new project from the company template PR_Template Concrete -
always the released version (PEER keeps the template file up to date by
itself, nothing to search for or download).

You choose where to save the project; the project opens right away.

Projects that are already started are not changed by a new template.
"""

import peer_access; peer_access.require_key()  # one PEER key (lib/peer_library/access.py)
import os

from pyrevit import forms, HOST_APP

from peer_library import config, log, strings, template_sync


def template_file():
    """Path of the template, downloading it now if this computer has none yet."""
    have = template_sync.installed()
    if have:
        return template_sync.path(), have
    cfg = config.load()
    if cfg['backend'] != 'http' or not config.is_configured(cfg):
        forms.alert(strings.TPL_NO_SERVICE, title=strings.TPL_TITLE)
        return None, None
    status, det, _ = template_sync.sync(config.make_backend(cfg), cfg.get('channel') or 'stable')
    have = template_sync.installed()
    if not have:
        forms.alert(strings.TPL_NOT_READY.format(det), title=strings.TPL_TITLE)
        return None, None
    return template_sync.path(), have


def main():
    path, have = template_file()
    if not path:
        return
    target = forms.save_file(file_ext='rvt', title=strings.TPL_SAVE_AS.format(have.get('version')))
    if not target:
        return
    if os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(path)):
        forms.alert(strings.TPL_NOT_OVER, title=strings.TPL_TITLE)
        return
    uiapp = HOST_APP.uiapp
    doc = uiapp.Application.NewProjectDocument(path)
    try:
        from Autodesk.Revit import DB
        opts = DB.SaveAsOptions()
        opts.OverwriteExistingFile = True
        doc.SaveAs(target, opts)
    finally:
        doc.Close(False)
    uiapp.OpenAndActivateDocument(target)


try:
    main()
except Exception as ex:
    log.write(u'new project', exc=True)
    forms.alert(u'{0}'.format(ex), title=strings.TPL_TITLE)
