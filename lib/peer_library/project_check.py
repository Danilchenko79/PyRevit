# -*- coding: utf-8 -*-
"""On project open: which library families in it are older than the library.

Uses only the index saved in the local cache (no network, no waiting) and
the PEER_Version of the families in the project. Shows a Windows
notification when something is outdated; silent otherwise.
"""

import os

from peer_library import config, jsonio, log


def outdated(doc, idx):
    """[(id, project version, library version)] for families from the library."""
    from peer_library import loader
    lib = dict((c['id'].lower(), c) for c in (idx or {}).get('families', [])
               if c.get('status') != 'deprecated')
    out = []
    for name, cat, pv in loader.project_family_list(doc):
        card = lib.get(name.lower())
        if card is not None and pv is not None and pv < card.get('version', 0):
            out.append((card['id'], pv, card['version']))
    return out


def on_doc_opened(doc):
    if doc is None or doc.IsFamilyDocument or getattr(doc, 'IsLinked', False):
        return None
    cfg = config.load()
    if not config.panel_visible(cfg):
        return None
    idx = jsonio.read(os.path.join(cfg['cache'], 'index.json'))
    if not idx:
        return None
    try:
        old = outdated(doc, idx)
    except Exception:
        log.write(u'project check', exc=True)
        return None
    if not old:
        return None
    names = u', '.join(o[0] for o in old[:3]) + (u'…' if len(old) > 3 else u'')
    text = (u'{0}: {1} library famil{2} outdated ({3}). PEER → Library → This project.'
            .format(doc.Title, len(old), u'y is' if len(old) == 1 else u'ies are', names))
    try:
        from pyrevit.forms import toaster
        toaster.send_toast(text, title=u'PEER Library')
    except Exception:
        log.write(u'project check toast', exc=True)
    return text
