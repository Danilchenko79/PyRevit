# -*- coding: utf-8 -*-
"""Publishing: one family from the form, or a whole sorted folder.

Only path into the library. Order: next version from the storage ->
prepare the family (checks, PEER_Version, preview, compact save on a copy)
-> storage.publish (card, index, changelog). Any error before the last step
leaves the library untouched; the storage itself is all-or-nothing.
"""

import io
import os
import shutil

from peer_library import checks_file, config, groups, index, log
from peer_library.backend_base import LibraryError


def workdir_for(family_id):
    base = os.environ.get('TEMP') or os.path.expanduser('~')
    return os.path.join(base, 'PEER', 'publish', family_id)


def publish_one(app, backend, source, draft, note=u'', accept_warnings=False,
                proposal_id=None):
    """-> (card or None, results). draft: id, name, group, tags, description,
    help_url. Nothing is published while results have errors, or warnings
    that were not accepted."""
    from peer_library import revit_family
    fid = draft['id']
    version = backend.next_version(fid)
    work = workdir_for(fid)
    try:
        prep = revit_family.prepare_family(app, source, fid, version, work)
        results = prep['results']
        if checks_file.errors(results):
            return None, results
        if checks_file.warnings(results) and not accept_warnings:
            return None, results
        if not prep['rfa']:
            results.append(('error', 'save', u'The family was not saved'))
            return None, results
        card = dict(draft)
        card['version'] = version
        card['revit'] = checks_file.LIBRARY_REVIT
        card['revit_category'] = prep['category'] or draft.get('revit_category', u'')
        card['types'] = all_type_names(prep)
        stored = backend.publish(card, prep['rfa'], prep['png'], prep['catalog'], note,
                                 proposal_id=proposal_id)
        return stored, results
    except LibraryError as ex:
        log.write(u'publish {0}: {1}'.format(fid, ex))
        return None, [('error', 'storage', u'{0}'.format(ex))]
    finally:
        shutil.rmtree(work, ignore_errors=True)


MAX_TYPES = 2000


def all_type_names(prep):
    """Types of the family + of its catalog, unique, for search."""
    names = list(prep.get('types') or [])
    if prep.get('catalog'):
        try:
            from peer_library import catalog
            names += catalog.type_names(prep['catalog'])
        except Exception:
            log.write(u'catalog names', exc=True)
    out, seen = [], set()
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out[:MAX_TYPES]


def folder_items(folder):
    """Sorted folder <group>/<ID>.rfa -> [(group, id, path)]."""
    items = []
    for g in groups.GROUP_IDS:
        d = os.path.join(folder, g)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith('.rfa'):
                items.append((g, os.path.splitext(f)[0], os.path.join(d, f)))
    return items


def publish_folder(app, backend, folder, progress=None, cancelled=None, note=u'Initial import'):
    """Initial import: every <group>/<ID>.rfa not yet in the library.
    Warnings are accepted, errors are skipped. Writes a CSV report into
    the folder and returns (counts, report_path)."""
    from peer_library import importmeta
    existing = set(c['id'].lower() for c in backend.get_index().get('families', []))
    items = folder_items(folder)
    sources = importmeta.read_sort_log(folder)
    rows, counts = [], {'published': 0, 'skipped': 0, 'failed': 0}
    for i, (g, fid, path) in enumerate(items):
        if cancelled and cancelled():
            break
        if progress:
            progress(i, len(items), fid)
        if fid.lower() in existing:
            counts['skipped'] += 1
            rows.append((fid, g, 'skipped', u'already in the library'))
            continue
        info = importmeta.info_for(fid, sources.get(fid, u''))
        draft = index.new_card(id=fid, name=info['name'], group=g, tags=info['tags'])
        try:
            card, results = publish_one(app, backend, path, draft, note, accept_warnings=True)
        except Exception as ex:
            log.write(u'batch {0}'.format(fid), exc=True)
            card, results = None, [('error', 'crash', u'{0}'.format(ex))]
        text = u' | '.join(r[2] for r in results if r[0] in ('error', 'warning'))
        if card:
            counts['published'] += 1
            existing.add(fid.lower())
            rows.append((fid, g, 'published', text))
        else:
            counts['failed'] += 1
            rows.append((fid, g, 'failed', text))
    report = os.path.join(folder, u'_publish_report.csv')
    with io.open(report, 'w', encoding='utf-8-sig') as f:
        f.write(u'id,group,result,notes\n')
        for r in rows:
            f.write(u','.join(u'"{0}"'.format(x.replace(u'"', u'""')) for x in r) + u'\n')
    return counts, report


def current_backend():
    cfg = config.load()
    return config.make_backend(cfg), cfg
