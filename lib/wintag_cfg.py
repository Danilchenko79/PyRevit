# -*- coding: utf-8 -*-
"""wintag_cfg - settings shared by WinTag and WinTag Place.

Windows whose family or type name contains one of the EXCLUDE keywords
(mamad windows by default) are not tagged: WinTag does not fill their
strings and WinTag Place does not place tags on them. They still count as
windows above / below when the pier heights are calculated.

The keyword list lives in the pyRevit config (section WinTag), so it
follows the user from project to project. Shift+Click on WinTag or
WinTag Place edits it.
"""

from pyrevit import script, forms

SECTION = 'WinTag'
# mamad, and the Hebrew spellings with and without the gershayim
EXCLUDE_DEFAULT = [u'mamad', u'ממ"ד', u'ממד']


def _split(raw):
    return [k.strip() for k in (raw or u'').replace(u';', u',').split(u',')
            if k.strip()]


def get_exclude_keywords():
    try:
        cfg = script.get_config(SECTION)
        raw = cfg.get_option('exclude_keywords', None)
        if raw is not None:
            return _split(raw)
    except Exception:
        pass
    return list(EXCLUDE_DEFAULT)


def edit_exclude_keywords():
    """Shift+Click: ask for the list and store it. -> new list or None."""
    cur = u', '.join(get_exclude_keywords())
    raw = forms.ask_for_string(
        default=cur,
        prompt=u'Windows whose family or type name contains any of these '
               u'words (comma separated, case ignored) are NOT tagged.\n'
               u'Empty = tag every window.',
        title=u'WinTag - excluded window families')
    if raw is None:
        return None
    cfg = script.get_config(SECTION)
    cfg.exclude_keywords = raw
    script.save_config()
    return _split(raw)


def _type_name(sym):
    try:
        from Autodesk.Revit.DB import BuiltInParameter
        p = sym.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        return p.AsString() or u''
    except Exception:
        return u''


def excluded_reason(win, keywords):
    """The matching keyword when the window must not be tagged, else None."""
    sym = getattr(win, 'Symbol', None)
    if sym is None or not keywords:
        return None
    try:
        fam = sym.Family.Name or u''
    except Exception:
        fam = u''
    text = (fam + u' ' + _type_name(sym)).lower()
    for k in keywords:
        if k.lower() in text:
            return k
    return None
