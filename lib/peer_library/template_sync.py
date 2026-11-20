# -*- coding: utf-8 -*-
"""The company project template on this computer, always the released version.

    %LOCALAPPDATA%/PEER/Templates/PR_Template Concrete.rte     (the path never changes)
    %LOCALAPPDATA%/PEER/Templates/template.json                {"version", "sha1", "note", "time"}

sync(backend, channel, folder): the 'template' product of the service ->
download once (SHA-1 checked) -> replace the file. Revit may have the file
open (a project is being created from it): then the new file waits next to
it as *.new and replaces it on the next start.
Pure Python (Revit and tests). New projects use the file; projects already
started are not touched by a new template.
"""

import os

from peer_library import jsonio, releases, rfa_info
from peer_library.backend_base import AccessError, LibraryError, OfflineError

NAME = u'PR_Template Concrete.rte'
STATE = 'template.json'


def default_folder():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'PEER', 'Templates')


def path(folder=None):
    return os.path.join(folder or default_folder(), NAME)


def installed(folder=None):
    """{'version', 'sha1', 'note', 'time'} of the template on this computer, or {}."""
    folder = folder or default_folder()
    data = jsonio.read(os.path.join(folder, STATE))
    if isinstance(data, dict) and data.get('version') and os.path.isfile(path(folder)):
        return data
    return {}


def _replace(new, target):
    """True when target is now the new file; False = target is in use."""
    try:
        if os.path.exists(target):
            os.chmod(target, 0o666)
            os.remove(target)
        os.rename(new, target)
        return True
    except (IOError, OSError):
        return False


def sync(backend, channel, folder=None):
    """-> (status, details, notes). status: clean / updated / waiting / none /
    nokey / offline / error. notes: [(version, text)] newer than what was here
    (for the "what is new" message), newest first."""
    folder = folder or default_folder()
    if not backend.has_key():
        return 'nokey', u'no PEER key on this computer', []
    try:
        manifest, _ = backend.release_manifest(releases.TEMPLATE, None, True)
    except OfflineError as ex:
        return 'offline', u'{0}'.format(ex), []
    except AccessError as ex:
        return 'nokey', u'{0}'.format(ex), []
    except LibraryError as ex:
        return 'error', u'{0}'.format(ex), []
    goal = releases.target(manifest, channel)
    if goal is None:
        return 'none', u'no template is published yet', []
    want = goal['version']
    target = path(folder)
    have = installed(folder)
    fresh = target + u'.new'
    if have.get('version') == want and have.get('sha1') == goal.get('sha1') and \
            rfa_info.sha1(target) == goal.get('sha1'):
        if os.path.exists(fresh):
            os.remove(fresh)
        return 'clean', want, []
    if not os.path.isdir(folder):
        os.makedirs(folder)
    try:
        if not os.path.isfile(fresh) or rfa_info.sha1(fresh) != goal.get('sha1'):
            backend.release_download(releases.TEMPLATE, want, fresh)
            if rfa_info.sha1(fresh) != goal.get('sha1'):
                os.remove(fresh)
                return 'error', u'the downloaded template {0} is damaged - will try again'.format(want), []
    except OfflineError as ex:
        return 'offline', u'{0}'.format(ex), []
    except (LibraryError, IOError, OSError) as ex:
        return 'error', u'{0}'.format(ex), []
    notes = releases.news(manifest, have.get('version') or u'0', channel)
    if not _replace(fresh, target):
        return 'waiting', u'template {0} is downloaded; the file is in use - it is replaced at the next start'.format(want), []
    jsonio.write(os.path.join(folder, STATE), {'version': want, 'sha1': goal.get('sha1'),
                                               'note': goal.get('note') or u'', 'time': goal.get('time') or u''})
    return 'updated', u'{0} -> {1}'.format(have.get('version') or u'-', want), notes


def run_async(on_done=None):
    """Background sync at Revit start (never blocks the start). on_done(status, details, notes)."""
    import threading

    def work():
        from peer_library import config, log
        try:
            cfg = config.load()
            if cfg['backend'] != 'http' or not config.is_configured(cfg):
                return
            status, det, notes = sync(config.make_backend(cfg), cfg.get('channel') or 'stable')
            if status not in ('clean', 'none', 'nokey', 'offline'):
                log.write(u'template: {0} {1}'.format(status, det))
            if on_done is not None:
                on_done(status, det, notes)
        except Exception:
            log.write(u'template sync', exc=True)

    t = threading.Thread(target=work)
    t.daemon = True
    t.start()
    return t


def toast(status, details, notes):
    """Windows notification 'template vN: what is new' after an update."""
    if status != 'updated':
        return
    try:
        from pyrevit.forms import toaster
        text = notes[0][1] if notes else u''
        toaster.send_toast(u'{0}: {1}{2}'.format(NAME, details, (u'\n' + text[:200]) if text else u''),
                           title=u'PEER template updated')
    except Exception:
        pass
