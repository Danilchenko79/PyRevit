# -*- coding: utf-8 -*-
__title__ = "Account"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Your PEER account on this computer: who is signed in, the state of your
personal key, the installed PEER version.

- Sign in: paste the key from a PEER admin (starts with peer_), or send an
  access request - after an admin approves it, press Sign in again.
- Check now: asks the PEER service whether the key is still valid.
- Sign out: removes the key from this computer.

One key opens the PEER buttons and the family library. Without internet
PEER keeps working for 14 days after the last check.
"""

from pyrevit import forms

from peer_library import log, strings

try:
    from peer_library import ui_account
    ui_account.show()
except Exception as ex:
    log.write(u'account', exc=True)
    forms.alert(u'{0}'.format(ex), title=strings.ACC_TITLE)
