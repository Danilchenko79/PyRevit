# -*- coding: utf-8 -*-
"""One key for the whole PEER tab (the library key).

    status(cfg)        what this computer has: key, last check, days left
    require_key()      first line of a button: no access -> offer to sign in, stop
    apply_ribbon()     hide / show the PEER panels (startup, after sign in / out)
    refresh_async()    background key check at Revit start

Nothing is locked until 'access_lock' is true in the settings (the office
turns it on once everybody has a key) and the service address is set.
The key is checked online when Revit starts and in Account; between checks
the last good check is trusted for config.OFFLINE_DAYS days.
"""

import datetime

from peer_library import config, keystore

OFF, OK, STALE, NONE, REQUESTED = 'off', 'ok', 'stale', 'none', 'requested'
KEEP_PANELS = ('Account', 'Feedback')     # always usable: sign in, ask for help
TAB = 'PEER'
_TIME = '%Y-%m-%dT%H:%M:%S'


class Status(object):

    def __init__(self, code, lock, days_left=0, name=u'', role=u'user', last_ok=u''):
        self.code = code
        self.lock = bool(lock)          # the office turned the lock on
        self.days_left = days_left
        self.name = name
        self.role = role
        self.last_ok = last_ok

    @property
    def signed_in(self):
        return self.code in (OK, STALE)

    @property
    def locked(self):
        """True = PEER buttons must not run on this computer now."""
        return self.lock and self.code in (STALE, NONE, REQUESTED)


def evaluate(cfg, has_key, has_request=False, now=None):
    """Pure: the status from the settings and what is stored on this computer."""
    lock = bool(cfg.get('access_lock'))
    if cfg.get('backend') != 'http' or not config.service_url_ok(cfg.get('url')):
        return Status(OFF, False)
    if not has_key:
        return Status(REQUESTED if has_request else NONE, lock)
    now = now or datetime.datetime.now()
    name, role = cfg.get('user') or u'', cfg.get('role') or u'user'
    try:
        last = datetime.datetime.strptime(cfg.get('last_ok') or u'', _TIME)
    except ValueError:
        return Status(STALE, lock, 0, name, role)
    age = now - last
    if age < -datetime.timedelta(days=1):              # a date in the future: the clock or a hand edit
        return Status(STALE, lock, 0, name, role)
    fresh = age < datetime.timedelta(days=config.OFFLINE_DAYS)
    left = max(config.OFFLINE_DAYS - age.days, 0) if fresh else 0
    return Status(OK if fresh else STALE, lock, left, name, role, cfg.get('last_ok') or u'')


def status(cfg=None):
    cfg = cfg or config.load()
    return evaluate(cfg, bool(keystore.load()), keystore.load_request() is not None)


def describe(st, check=u''):
    """Pure: the sentence shown under the status (check = result of check_now)."""
    from peer_library import strings
    if check == 'revoked':
        return strings.ACC_REVOKED
    if st.code == OFF:
        return strings.ACC_OFF
    if st.code == NONE:
        return strings.ACC_NONE_LOCKED if st.lock else strings.ACC_NONE
    if st.code == REQUESTED:
        return strings.ACC_REQUESTED
    if st.code == STALE:
        return strings.ACC_STALE_LOCKED if st.lock else strings.ACC_STALE
    if check == 'offline':
        return strings.ACC_OFFLINE.format(st.days_left)
    return strings.ACC_OK


# ---- buttons -----------------------------------------------------------------------
def require_key():
    """First line of every PEER button. Returns True, or stops the script."""
    try:
        st = status()
    except Exception:
        return True                     # settings unreadable: never block work on our own bug
    if not st.locked:
        return True
    from pyrevit import forms, script
    from peer_library import strings
    if forms.alert(strings.ACC_NEED_KEY, title=strings.ACC_TITLE, yes=True, no=True):
        try:
            from peer_library import ui_account
            ui_account.show()
            if not status().locked:
                return True
        except Exception:
            from peer_library import log
            log.write(u'account from a button', exc=True)
    script.exit()


# ---- ribbon ------------------------------------------------------------------------
def panel_plan(names, locked, library, library_ready=True):
    """Pure: {panel name: visible} for the panels this module decides about.
    library = the service is set up; library_ready = it has families to show
    (or the person is an admin who fills it)."""
    out = {}
    for name in names:
        if name == 'Account':
            out[name] = bool(library)
        elif name in KEEP_PANELS:
            continue
        elif name == 'Library':
            out[name] = bool(library) and bool(library_ready) and not locked
        else:
            out[name] = not locked
    return out


def library_ready(cfg=None):
    """Admins always; everybody else once the library has at least one family
    (the copy of the index saved on this computer says so)."""
    import os
    from peer_library import jsonio
    cfg = cfg or config.load()
    if cfg.get('role') == 'admin' or cfg.get('backend') != 'http':
        return True
    idx = jsonio.read(os.path.join(cfg['cache'], 'index.json'))
    return bool(isinstance(idx, dict) and idx.get('families'))


def apply_ribbon(st=None):
    """Hide the PEER panels while locked, show them when access is back.
    Must run on Revit's main thread (startup.py or a button)."""
    from pyrevit.coreutils import ribbon
    st = st or status()
    library = config.panel_visible()
    try:
        ready = library_ready()
    except Exception:
        ready = True
    for tab in ribbon.get_current_ui().get_pyrevit_tabs():
        if tab.name != TAB:
            continue
        panels = dict((p.name, p) for p in list(tab))
        for name, visible in panel_plan(panels.keys(), st.locked, library, ready).items():
            panels[name].visible = visible
    return st


# ---- key check -----------------------------------------------------------------------
def pick_up(backend):
    """The access request sent from this computer, no window: when an admin has
    approved it the key arrives and is saved. Returns 'signed' / 'waiting' /
    'rejected' / 'expired' / 'offline' / 'none' (no request was sent)."""
    from peer_library.backend_base import AccessError, LibraryError, OfflineError
    req = keystore.load_request()
    if not req:
        return 'none'
    try:
        st = backend.access_status(req[0], req[1])
    except OfflineError:
        return 'offline'
    except (AccessError, LibraryError):
        keystore.forget_request()
        return 'expired'
    if st.get('status') == 'delivered' and st.get('key'):
        backend.sign_in(st['key'])
        keystore.forget_request()
        return 'signed'
    if st.get('status') == 'rejected':
        keystore.forget_request()
        return 'rejected'
    return 'waiting'


def check_now(cfg=None, quick=False):
    """Asks the service about the key. Returns (status, 'ok' | 'revoked' |
    'offline' | 'no key' | 'off' | error text). A revoked key is forgotten;
    no connection keeps the last good check. Without a key an approved access
    request is picked up first."""
    from peer_library.backend_base import AccessError, LibraryError, OfflineError
    cfg = cfg or config.load()
    if evaluate(cfg, True).code == OFF:
        return status(cfg), 'off'
    backend = config.make_backend(cfg)
    if not backend.has_key():
        try:
            got = pick_up(backend)
        except Exception:
            got = 'none'
        if got != 'signed':
            return status(cfg), 'no key'
        return status(), 'ok'
    msg = 'ok'
    try:
        backend.auth(quick=quick)
    except AccessError as ex:
        if getattr(ex, 'status', None) == 401:            # the service says the key is not valid
            keystore.forget()
            config.save_local(last_ok=u'', role=u'user')
            msg = 'revoked'
        else:                                              # 403 from a proxy / firewall: keep the key
            msg = u'{0}'.format(ex)
    except OfflineError:
        msg = 'offline'
    except LibraryError as ex:
        msg = u'{0}'.format(ex)
    return status(), msg


def startup():
    """Revit start (main thread): draw the ribbon right. A computer that would be
    locked only because the last check is old asks the service first (one short
    try) - otherwise the panels would stay hidden although the key is fine.
    Then the usual check runs in the background."""
    st = status()
    if st.locked and st.code == STALE:
        try:
            st, _ = check_now(quick=True)
        except Exception:
            pass
        apply_ribbon(st)
        return st
    apply_ribbon(st)
    refresh_async()
    return st


def _toast(title, text):
    try:
        from pyrevit.forms import toaster
        toaster.send_toast(text, title=title)
    except Exception:
        pass


def background_work():
    """Revit start, background thread: key check; an approved access request
    signs the person in and (on a loader) downloads the full PEER; the copy of
    the library index is refreshed; an admin hears about waiting requests."""
    from peer_library import log, strings, version
    had_key = bool(keystore.load())
    st, msg = check_now()
    if not st.signed_in:
        return msg
    cfg = config.load()
    if not had_key:                                    # the request was approved since the last start
        text = strings.ACC_APPROVED.format(st.name)
        if version.is_loader():
            try:
                import peer_update
                peer_update.sync_package(version.ext_dir())
            except Exception:
                log.write(u'access: full PEER after approval', exc=True)
        _toast(strings.ACC_TITLE, text + u' ' + strings.UPD_FULL_TEXT)
    try:
        from peer_library.cache import Cache
        backend = config.make_backend(cfg)
        Cache(cfg['cache'], backend).index()          # keeps the saved copy current (ETag: cheap)
        if cfg.get('role') == 'admin':
            n = len(backend.list_access_requests())
            if n:
                _toast(strings.ACC_TITLE, strings.ACC_REQUESTS_WAIT.format(n))
    except Exception as ex:
        log.write(u'access background: {0}'.format(ex))
    return msg


def refresh_async():
    import threading

    def work():
        try:
            background_work()
        except Exception:
            from peer_library import log
            log.write(u'access check', exc=True)

    t = threading.Thread(target=work)
    t.daemon = True
    t.start()
    return t
