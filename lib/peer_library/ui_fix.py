# -*- coding: utf-8 -*-
"""Check family button: change one parameter by hand (pyRevit pickers) and
show what Fix automatically did. The Revit work is in family_fix."""

from pyrevit import forms

from peer_library import family_diff as D
from peer_library import family_fix, strings


def _spec(definition):
    try:
        return D.spec_name(definition.GetDataType().TypeId)
    except Exception:
        return u'?'


def _guid(p):
    try:
        return u'{0}'.format(p.GUID).lower() if p.IsShared else u''
    except Exception:
        return u''


def change_parameter(fd, defs):
    """Asks which parameter and what to do; returns family_fix.apply results
    or None when cancelled."""
    fm = fd.FamilyManager
    labels = {}
    for p in fm.GetParameters():
        if family_fix._eid(p.Id) < 0:
            continue
        labels[u'{0}    [{1}, {2}, {3}]'.format(
            p.Definition.Name, u'shared' if p.IsShared else u'family',
            u'instance' if p.IsInstance else u'type', _spec(p.Definition))] = p
    pick = forms.SelectFromList.show(sorted(labels, key=lambda s: s.lower()),
                                     title=strings.FIX_PICK_PARAM, multiselect=False)
    if not pick:
        return None
    p = labels[pick]
    name = p.Definition.Name
    choices = [strings.FIX_A_SHARED]
    choices += [strings.FIX_A_FAMILY] if p.IsShared else [strings.FIX_A_RENAME]
    choices += [strings.FIX_A_DELETE]
    act = forms.CommandSwitchWindow.show(choices, message=strings.FIX_PICK_ACTION.format(name))
    if not act:
        return None
    a = None
    if act == strings.FIX_A_SHARED:
        if not defs:
            forms.alert(strings.FIX_NO_FILE, title=strings.APP)
            return None
        kind, own = _spec(p.Definition), _guid(p)
        cands = {}
        for g, d in defs.items():
            if g != own and _spec(d) == kind:
                cands[u'{0}    ({1})'.format(d.Name, d.OwnerGroup.Name)] = d
        pick2 = forms.SelectFromList.show(sorted(cands, key=lambda s: s.lower()),
                                          title=strings.FIX_PICK_SHARED.format(kind),
                                          multiselect=False)
        if not pick2:
            return None
        ext = cands[pick2]
        a = {'op': 'rename_shared' if p.IsShared else 'to_shared', 'name': name,
             'guid': u'{0}'.format(ext.GUID).lower(),
             'text': u"'{0}' -> shared '{1}'".format(name, ext.Name)}
    elif act in (strings.FIX_A_RENAME, strings.FIX_A_FAMILY):
        new = forms.ask_for_string(default=name, prompt=strings.FIX_NEW_NAME.format(name),
                                   title=strings.APP)
        if not new or (new == name and act == strings.FIX_A_RENAME):
            return None
        a = {'op': 'rename' if act == strings.FIX_A_RENAME else 'to_family', 'name': name,
             'new': new.strip(), 'text': u"'{0}' -> '{1}'".format(name, new.strip())}
    elif act == strings.FIX_A_DELETE:
        if not forms.alert(strings.FIX_DELETE_ASK.format(name), title=strings.APP, yes=True, no=True):
            return None
        a = {'op': 'remove', 'name': name, 'text': u"remove '{0}'".format(name)}
    if a is None:
        return None
    return family_fix.apply(fd, [a], defs)


def show_results(results):
    done = [a for a, err in results if err is None]
    text = strings.FIX_DONE.format(len(done), len(results))
    bad = [u'- {0}: {1}'.format(a['text'], err) for a, err in results if err is not None]
    if bad:
        text += u'\n\n' + strings.FIX_FAILED + u'\n' + u'\n'.join(bad[:15])
    forms.alert(text, title=strings.APP)
