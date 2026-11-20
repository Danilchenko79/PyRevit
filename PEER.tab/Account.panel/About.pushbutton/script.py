# -*- coding: utf-8 -*-
__title__ = "About"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
About PEER: the installed version and what came with it, who is signed
in, where PEER is installed. Check for updates installs a new version at
once (PEER also updates by itself when Revit starts). Wiki opens the
company PEER site.
"""

from pyrevit import forms

from peer_library import log, strings

try:
    from peer_library import ui_about
    ui_about.show()
except Exception as ex:
    log.write(u'about', exc=True)
    forms.alert(u'{0}'.format(ex), title=strings.ABOUT_TITLE)
