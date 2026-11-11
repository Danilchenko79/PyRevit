# -*- coding: utf-8 -*-
"""wintag_cfg - settings shared by WinTag and WinTag Place.

Windows whose family or type name contains one of the EXCLUDE keywords
(mamad windows by default) are not tagged: WinTag does not fill their
strings and WinTag Place does not place tags on them. They still count as
windows above / below when the pier heights are calculated.

The keyword list lives in the pyRevit config (section WinTag), so it
follows the user from project to project. Shift+Click on WinTag or
WinTag Place edits it.

Tag units: the pier strings are written in cm (default) or mm. The choice
is the user's, stored in the same config section, independent of the
project units. Shift+Click on WinTag -> "Tag units".
"""

from pyrevit import script, forms

SECTION = 'WinTag'
# mamad, and the Hebrew spellings with and without the gershayim
EXCLUDE_DEFAULT = [u'mamad', u'ממ"ד', u'ממד']
UNITS = ('cm', 'mm')
UNITS_DEFAULT = 'cm'


def get_units():
    """'cm' or 'mm' - the units the tag strings are written in."""
    try:
        cfg = script.get_config(SECTION)
        u = (cfg.get_option('tag_units', None) or u'').strip().lower()
        if u in UNITS:
            return u
    except Exception:
        pass
    return UNITS_DEFAULT


def set_units(units):
    cfg = script.get_config(SECTION)
    cfg.tag_units = units
    script.save_config()
    return units


def edit_units():
    """Shift+Click: pick cm / mm. -> chosen units or None (cancelled)."""
    cur = get_units()
    opts = [u'cm  (25/225+25/15)', u'mm  (250/2250+250/150)']
    pick = forms.CommandSwitchWindow.show(
        opts, message=u'Units of the pier tag strings (now: {}). Run WinTag '
                      u'afterwards to rewrite the strings.'.format(cur),
        title=u'WinTag - tag units')
    if not pick:
        return None
    return set_units(pick.split()[0])


def shift_menu():
    """Shift+Click menu of WinTag: what to edit. -> text to show or None."""
    pick = forms.CommandSwitchWindow.show(
        [u'Tag units (cm / mm)', u'Excluded window families'],
        message=u'Tag units: {}   Excluded: {}'.format(
            get_units(), u', '.join(get_exclude_keywords()) or u'(none)'),
        title=u'WinTag - settings')
    if not pick:
        return None
    if pick.startswith(u'Tag units'):
        u = edit_units()
        return None if u is None else u'Tag units: {}'.format(u)
    kw = edit_exclude_keywords()
    return None if kw is None else u'Excluded: {}'.format(u', '.join(kw) or u'(none)')


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
