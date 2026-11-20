# -*- coding: utf-8 -*-
__title__ = "Wiki"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Opens the company PEER site in the browser: how to work with PEER, the
buttons, the family library, the project template, what is new.
"""

from pyrevit import forms

from peer_library import log, strings

try:
    from peer_library import ui_about
    if not ui_about.open_wiki():
        forms.alert(strings.WIKI_NOT_SET, title=strings.WIKI_TITLE)
except Exception as ex:
    log.write(u'wiki', exc=True)
    forms.alert(u'{0}'.format(ex), title=strings.WIKI_TITLE)
