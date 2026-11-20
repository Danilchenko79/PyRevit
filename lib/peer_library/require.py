# -*- coding: utf-8 -*-
"""Families a script needs: take them from the project, else from the library.

    from peer_library import require
    res = require.families(doc, [u'PR_Wall2D_Edge', u'PEER_Rebar_Shape 21'],
                           folder=BUTTON_FOLDER)           # folder = old fallback, optional
    if not res.ok:
        forms.alert(res.message(), exitscript=True)
    sym = require.symbol(doc, u'PR_Wall2D_Edge')

Rules (the script never breaks what is in the project):
- a family already in the project is used as it is - never reloaded or
  replaced, even when the library has a newer version (res.outdated lists them;
  updating is the person's choice in Library -> This project);
- a missing family comes from the library (downloaded once, then the local
  copy; offline the copy works 14 days), then from folder/<name>.rfa;
- a family with a type catalog loads only the types asked for
  (types={name: [type, ...]}) - never the whole catalog;
- what the library card says goes with a loaded family (a pile -> its tag)
  is loaded with it, if the project does not have it yet;
- each load is its own transaction: call it outside an open Transaction
  (inside a TransactionGroup is fine - one Undo with the script).

plan() is pure Python (tested without Revit); families() does the loading.
"""

import os

PRESENT, LIBRARY, FOLDER, MISSING = 'present', 'library', 'folder', 'missing'

WHY_NOT_IN_LIBRARY = u'not in the library'
WHY_NO_LIBRARY = u'the library is not available'
WHY_NEEDS_TYPES = u'has a type catalog - the script must say which types'


def _key(name):
    return (name or u'').strip().lower()


def plan(names, in_project, cards, folder_files=(), types=None, library_error=None):
    """[(name, action, detail)] in the order of names (duplicates dropped).

    in_project   {name.lower(): project version or None}  (loader.project_families)
    cards        {id.lower(): card} of the library index, or None (no library)
    folder_files {name.lower(): path} of <folder>/<name>.rfa
    action / detail: PRESENT / project version, LIBRARY / card,
                     FOLDER / path, MISSING / reason text."""
    types = dict((_key(k), v) for k, v in (types or {}).items())
    folder_files = dict(folder_files or {})
    out, seen = [], set()
    for name in names:
        k = _key(name)
        if not k or k in seen:
            continue
        seen.add(k)
        if k in in_project:
            out.append((name, PRESENT, in_project[k]))
            continue
        card = (cards or {}).get(k)
        if card is not None and card.get('type_catalog') and not types.get(k):
            if k in folder_files:
                out.append((name, FOLDER, folder_files[k]))
            else:
                out.append((name, MISSING, WHY_NEEDS_TYPES))
            continue
        if card is not None:
            out.append((name, LIBRARY, card))
        elif k in folder_files:
            out.append((name, FOLDER, folder_files[k]))
        elif cards is None:
            out.append((name, MISSING, library_error or WHY_NO_LIBRARY))
        else:
            out.append((name, MISSING, WHY_NOT_IN_LIBRARY))
    return out


def with_companions(names, cards, in_project):
    """names + what the library says goes with them (a pile -> its tag), each
    once. Only companions that can load by themselves are added: not in the
    project, not retired, no type catalog."""
    from peer_library import index
    out, seen = [], set()
    for name in names:
        k = _key(name)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(name)
        card = (cards or {}).get(k)
        if card is None:
            continue
        for cid, state, c in index.companions(card, cards, in_project):
            if state == 'load' and cid.lower() not in seen:
                seen.add(cid.lower())
                out.append(cid)
    return out


def outdated(steps, cards):
    """[(name, project version, library version)] of present families the
    library has newer (shown to the person, never updated by a script)."""
    out = []
    for name, action, detail in steps:
        if action != PRESENT or detail is None:
            continue
        card = (cards or {}).get(_key(name))
        if card is not None and card.get('version', 0) > detail:
            out.append((name, detail, card['version']))
    return out


def folder_files(folder, names):
    out = {}
    if not folder:
        return out
    for name in names:
        p = os.path.join(folder, u'{0}.rfa'.format(name.strip()))
        if os.path.isfile(p):
            out[_key(name)] = p
    return out


class Result(object):

    def __init__(self):
        self.families = {}       # name -> Family (None for a rebar shape)
        self.loaded = []         # [(name, 'library vN' / 'folder')]
        self.missing = []        # [(name, reason)]
        self.outdated = []       # [(name, project version, library version)]
        self.offline = False     # the library answered from the saved copy

    @property
    def ok(self):
        return not self.missing

    def message(self):
        lines = []
        if self.missing:
            lines.append(u'Families the script needs are not in the project:')
            lines.extend(u'  {0} - {1}'.format(n, why) for n, why in self.missing)
        if self.loaded:
            lines.append(u'Loaded: ' + u', '.join(u'{0} ({1})'.format(n, s) for n, s in self.loaded))
        if self.outdated:
            lines.append(u'Older than the library (kept as they are; update them in '
                         u'PEER -> Library -> This project): ' +
                         u', '.join(u'{0} v{1} -> v{2}'.format(*o) for o in self.outdated))
        return u'\n'.join(lines)


def _library(interactive):
    """(cards {id.lower(): card}, cache, offline, error) - cards None without a library."""
    from peer_library import config, log
    from peer_library.cache import Cache
    cfg = config.load()
    if not config.panel_visible(cfg):
        return None, None, False, WHY_NO_LIBRARY + u' (not set up on this computer)'
    try:
        if interactive:
            from peer_library import session
            backend = session.connect(cfg)
        else:
            backend = config.make_backend(cfg)
            if getattr(backend, 'kind', '') == 'http' and not backend.has_key():
                backend = None
        if backend is None:
            return None, None, False, WHY_NO_LIBRARY + u' (not signed in)'
        cache = Cache(cfg['cache'], backend)
        idx, online = cache.index()
    except Exception as ex:
        log.write(u'require: library', exc=True)
        return None, None, False, u'{0}: {1}'.format(WHY_NO_LIBRARY, ex)
    cards = dict((c['id'].lower(), c) for c in idx.get('families', []))
    return cards, cache, not online, None


def families(doc, names, folder=None, types=None, interactive=True):
    """Makes sure every family in names is in doc. Returns Result.
    interactive=False never shows a window (no sign-in) - for hooks/batch."""
    from peer_library import loader, log, userprefs
    res = Result()
    in_project = loader.project_families(doc)
    want = [n for n in names if _key(n) and _key(n) not in in_project]
    cards, cache, offline, err = (None, None, False, None)
    if want:
        cards, cache, offline, err = _library(interactive)
        names = with_companions(names, cards, in_project)
    res.offline = offline
    files = folder_files(folder, want)
    steps = plan(names, in_project, cards, files, types, err)
    res.outdated = outdated(steps, cards)
    tkeys = dict((_key(k), v) for k, v in (types or {}).items())
    for name, action, detail in steps:
        try:
            if action == PRESENT:
                res.families[name] = loader.find_family(doc, name)
            elif action == LIBRARY:
                path = cache.get(detail, '.rfa')
                tn = tkeys.get(_key(name)) or None
                if tn:
                    cache.get(detail, '.txt')       # LoadFamilySymbol wants it next to the file
                res.families[name] = loader.load_family(doc, path, detail['id'], False, tn)
                res.loaded.append((name, u'library v{0}'.format(detail.get('version'))))
                try:
                    userprefs.add_recent(detail['id'])
                except Exception:
                    pass
            elif action == FOLDER:
                tn = tkeys.get(_key(name)) or None
                res.families[name] = loader.load_family(doc, detail, name, False, tn)
                res.loaded.append((name, u'folder'))
            else:
                res.missing.append((name, detail))
        except Exception as ex:
            log.write(u'require {0}'.format(name), exc=True)
            res.missing.append((name, u'{0}'.format(ex)))
    if res.loaded:
        log.write(u'require: loaded ' + u', '.join(n for n, s in res.loaded))
    return res


def symbol(doc, name, type_name=None):
    """FamilySymbol of a family in doc: type_name (None if there is no such
    type), else the first type. Activate it (sym.Activate()) inside the
    script's transaction before placing."""
    from peer_library import loader
    fam = loader.find_family(doc, name)
    if fam is None:
        return None
    if type_name:
        for i in fam.GetFamilySymbolIds():
            s = doc.GetElement(i)
            if s is not None and loader.symbol_name(s) == type_name:
                return s
        return None
    return loader.first_symbol(doc, fam)
