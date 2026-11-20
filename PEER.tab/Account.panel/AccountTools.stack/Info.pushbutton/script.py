# -*- coding: utf-8 -*-
__title__ = "Info"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Opens the company PEER site in the browser: how to work with PEER, the
buttons, the family library, the project template, what is new.
"""

from pyrevit import forms

from peer_library import config, log

TITLE = u'PEER - Info'

try:
    url = (config.load().get('wiki_url') or u'').strip()
    if url.startswith('https://') or url.startswith('http://'):
        from System.Diagnostics import Process
        Process.Start(url)
    else:
        forms.alert(u'The address of the PEER site is not set yet.\n\n'
                    u'An admin sets it once: "wiki_url" in lib/peer_library/settings.json.',
                    title=TITLE)
except Exception as ex:
    log.write(u'info', exc=True)
    forms.alert(u'{0}'.format(ex), title=TITLE)
