# -*- coding: utf-8 -*-
__title__ = "Wiki"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Opens the company PEER site in the browser: how to work with PEER, the
buttons, the family library, the project template, what is new.
"""
# Not on the ribbon (it is not in the layout of the stack): the Wiki button under its previous
# folder name. A computer that updates with the previous updater builds the ribbon of that
# session from the old layout and looks for this folder. Remove it one release later.

from pyrevit import forms

from peer_library import log, strings

try:
    from peer_library import ui_about
    if not ui_about.open_wiki():
        forms.alert(strings.WIKI_NOT_SET, title=strings.WIKI_TITLE)
except Exception as ex:
    log.write(u'wiki', exc=True)
    forms.alert(u'{0}'.format(ex), title=strings.WIKI_TITLE)
