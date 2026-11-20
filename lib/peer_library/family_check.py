# -*- coding: utf-8 -*-
"""Check one family - while making or fixing it, before Publish, or a whole
folder before a bulk import (Revit only; the rules are in family_diff).

    - category, CAD imports, no types                (revit_family.family_checks)
    - shared parameters against the company shared parameter file
      (same name with another GUID = two parameters in projects)
    - family parameters that should be the company's shared ones
    - every type regenerates (switched one by one, undone afterwards)
    - names that differ only in case / spaces, parameters nothing uses
    - nested shared families named like library families
Nothing in the family is changed.
"""

import codecs
import os

from Autodesk.Revit import DB

from peer_library import checks_file, config, family_diff as D, family_sig, jsonio, log
from peer_library.revit_family import Guard, QuietOpen, family_checks

_SHARED = {}                 # path -> (mtime, parsed) of the shared parameter file


def shared_file(app, cfg=None):
    """(parsed company shared parameter file or None, its path or u'')."""
    path = ((cfg or {}).get('shared_params') or u'').strip()
    if not path:
        try:
            path = app.SharedParametersFilename or u''
        except Exception:
            path = u''
    path = os.path.expandvars(path)
    if not path or not os.path.isfile(path):
        return None, path
    try:
        mtime = os.path.getmtime(path)
        hit = _SHARED.get(path)
        if hit is None or hit[0] != mtime:
            _SHARED[path] = (mtime, D.read_shared_file(path))
        return _SHARED[path][1], path
    except Exception:
        log.write(u'shared parameter file {0}'.format(path), exc=True)
        return None, path


def library_names(cfg):
    """Family IDs of the library from the saved index (no network)."""
    try:
        idx = jsonio.read(os.path.join(cfg['cache'], 'index.json')) or {}
        return [c['id'] for c in idx.get('families', [])]
    except Exception:
        return []


def broken_types(fd):
    """[(type name, error)] of the types Revit cannot regenerate. Each type is
    made current in its own transaction inside a group that is rolled back."""
    fm = fd.FamilyManager
    types = [t for t in fm.Types if t.Name and t.Name.strip()]
    if len(types) < 2:
        return []
    out = []
    tg = DB.TransactionGroup(fd, u'PEER: check types')
    tg.Start()
    try:
        for t in types:
            Guard.last_errors = []
            tx = DB.Transaction(fd, u'PEER: type {0}'.format(t.Name))
            o = tx.GetFailureHandlingOptions()
            o.SetFailuresPreprocessor(Guard())
            o.SetClearAfterRollback(True)
            tx.SetFailureHandlingOptions(o)
            tx.Start()
            try:
                fm.CurrentType = t
                tx.Commit()
            except Exception as ex:
                Guard.last_errors.append(u'{0}'.format(ex))
            finally:
                if tx.HasStarted() and not tx.HasEnded():
                    tx.RollBack()
            if tx.GetStatus() != DB.TransactionStatus.Committed:
                out.append((t.Name, u'; '.join(Guard.last_errors[:1]) or u'rolled back'))
    finally:
        if tg.HasStarted() and not tg.HasEnded():
            tg.RollBack()            # every transaction above is closed by now
    return out


def check_document(fd, shared=None, shared_name=u'', lib_names=None):
    """(findings, signature) of an open family document."""
    base, cat = family_checks(fd)
    res = [f for f in base if f[1] != 'params']   # 'not shared' count: said better below
    sig = family_sig.signature(fd)
    res.extend(D.shared_file_findings(sig, shared, shared_name or u'the company shared parameter file'))
    res.extend(D.hygiene_findings(sig, lib_names))
    try:
        res.extend(D.types_findings(broken_types(fd)))
    except Exception:
        log.write(u'type check', exc=True)
    return D.ordered(res), sig


def publish_checks(app, fd, cfg):
    """Publish: the checks above without family_checks (Publish runs those
    itself) and without plain notes - errors block, warnings need a tick.
    The family's own name is not a 'library family' for itself."""
    shared, spath = shared_file(app, cfg)
    sig = family_sig.signature(fd)
    own = (sig.get('name') or u'').lower()
    names = [n for n in library_names(cfg) if n.lower() != own]
    res = D.shared_file_findings(sig, shared, os.path.basename(spath) or u'the company shared parameter file')
    res += D.hygiene_findings(sig, names)
    try:
        res += D.types_findings(broken_types(fd))
    except Exception:
        log.write(u'type check', exc=True)
    return [f for f in res if f[0] != D.INFO]


def check_file(app, path, shared=None, shared_name=u'', lib_names=None):
    """Findings of an .rfa (opened in the background and closed again)."""
    res, year = checks_file.check_file(path)
    res = [r for r in res if r[1] not in ('prefix',)]
    if checks_file.errors(res):
        return D.ordered(res)
    fd = None
    try:
        quiet = QuietOpen(app)
        with quiet:
            fd = app.OpenDocumentFile(path)
        found, sig = check_document(fd, shared, shared_name, lib_names)
        return D.ordered(res + found + open_warnings(quiet.dismissed))
    except Exception as ex:
        log.write(u'check {0}'.format(path), exc=True)
        return D.ordered(res + [(D.ERROR, 'open', u'Revit could not open it: {0}'.format(ex))])
    finally:
        if fd is not None:
            try:
                fd.Close(False)
            except Exception:
                log.write(u'close {0}'.format(path), exc=True)


def open_warnings(texts):
    """Warnings Revit gives when the family opens (e.g. nested types it cannot
    make and deletes) - they come back in every project the family goes to."""
    uniq = []
    for t in texts or []:
        if t and t not in uniq:
            uniq.append(t)
    if not uniq:
        return []
    return [(D.WARNING, 'open_warnings', u'Revit warns when it opens the family: {0}'.format(
        u' | '.join(uniq[:3]) + (u' (+{0})'.format(len(uniq) - 3) if len(uniq) > 3 else u'')))]


def family_files(folder):
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(u'_') and not d.startswith(u'.')]
        for f in files:
            if f.lower().endswith(u'.rfa') and not _is_backup(f):
                out.append(os.path.join(root, f))
    return sorted(out)


def _is_backup(name):
    base = os.path.splitext(name)[0]
    tail = base.rsplit(u'.', 1)
    return len(tail) == 2 and len(tail[1]) == 4 and tail[1].isdigit()     # X.0001.rfa


def document_report(fd, cfg, app, name=None):
    """load_check.Report (kind 'family') of an open family document."""
    from peer_library import load_check, strings
    shared, spath = shared_file(app, cfg)
    found, sig = check_document(fd, shared, os.path.basename(spath) if shared else u'',
                                library_names(cfg))
    n_shared = sum(1 for p in sig['params'] if p.get('shared'))
    summary = strings.FCHECK_SUMMARY.format(sig.get('category') or u'?', len(sig['params']),
                                            n_shared, len(sig.get('types') or []))
    note = (strings.FCHECK_SHARED_NOTE.format(spath) if shared
            else strings.FCHECK_NO_SHARED.format(spath or u'-'))
    found = D.ordered(found + D.shared_file_self(shared, os.path.basename(spath)))
    rep = load_check.Report(name or sig.get('name') or fd.Title, found, kind='family',
                            summary=summary, note=note)
    rep.fixes = D.fix_plan(sig, shared)           # what Fix family can do by itself
    rep.sig = sig
    rep.shared_path = spath if shared else u''
    return rep


def report_folder():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    path = os.path.join(base, 'PEER', 'checks')
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def folder_report(app, folder, cfg, progress=None):
    """Every .rfa under folder (not _* folders, not backups). progress(i, n)
    returning False stops. Full list -> CSV in %LOCALAPPDATA%/PEER/checks."""
    import datetime
    from peer_library import load_check, strings
    shared, spath = shared_file(app, cfg)
    sname = os.path.basename(spath) if shared else u''
    names = library_names(cfg)
    files = family_files(folder)
    rows, summary_rows = [], []
    counts = {D.ERROR: 0, D.WARNING: 0, 'ok': 0}
    fixable = 0
    for i, path in enumerate(files):
        if progress is not None and progress(i, len(files)) is False:
            break
        found = check_file(app, path, shared, sname, names)
        rel = os.path.relpath(path, folder)
        if any(f[1] in FIXABLE for f in found):
            fixable += 1
        for lv, code, text in found:
            rows.append((rel, lv, code, text))
        worst = D.worst([f for f in found if f[0] != D.INFO])
        if worst is None:
            rows.append((rel, u'ok', u'', u''))
            counts['ok'] += 1
            continue
        counts[worst] += 1
        bad = [f for f in found if f[0] == worst]
        more = len([f for f in found if f[0] in (D.ERROR, D.WARNING)]) - 1
        summary_rows.append((worst, 'family', u'{0}: {1}{2}'.format(
            rel, bad[0][2], u' (+{0})'.format(more) if more > 0 else u'')))
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M')
    csv = write_csv(os.path.join(report_folder(), u'family_check_{0}_{1}.csv'.format(
        os.path.basename(os.path.normpath(folder)) or u'folder', stamp)), rows)
    note = (strings.FCHECK_SHARED_NOTE.format(spath) if shared
            else strings.FCHECK_NO_SHARED.format(spath or u'-'))
    rep = load_check.Report(
        strings.FCHECK_FOLDER_HEAD.format(len(files), folder),
        D.shared_file_self(shared, sname) + summary_rows, kind='family',
        summary=strings.FCHECK_FOLDER_SUMMARY.format(counts[D.ERROR], counts[D.WARNING],
                                                     counts['ok'], csv),
        note=note)
    rep.folder = folder
    rep.fix_count = fixable if shared else 0
    return rep


# findings Fix family can put right by itself (family_diff.fix_plan)
FIXABLE = ('file_name', 'should_share')


def write_csv(path, rows):
    """rows = [(file, level, code, text)] -> UTF-8 CSV that Excel opens."""
    with codecs.open(path, 'w', 'utf-8-sig') as f:
        f.write(u'file,level,code,text\r\n')
        for r in rows:
            f.write(u','.join(u'"{0}"'.format(u'{0}'.format(x).replace(u'"', u'""')) for x in r) + u'\r\n')
    return path
