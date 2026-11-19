# -*- coding: utf-8 -*-
"""Windows notification at Revit start: what is new in the library since the
user last opened it; for admins also waiting proposals and access requests.

Runs in a background thread (Revit start never waits), at most every
CHECK_HOURS, only with the library service and a saved key. The first run on
a computer only remembers "now" - no flood of old news.
"""

import datetime
import threading

from peer_library import config, keystore, log

CHECK_HOURS = 6


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def _due(cfg):
    try:
        last = datetime.datetime.strptime(cfg.get('notify_checked') or u'', '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return True
    return datetime.datetime.now() - last > datetime.timedelta(hours=CHECK_HOURS)


def latest_time(changelog):
    times = [e.get('time') or u'' for e in (changelog or {}).get('entries') or []]
    return max(times) if times else u''


def news_text(changelog, seen_until, me=u'', used=None):
    """'3 new, 1 updated families (incl. 1 you use: X)' since seen_until (server
    times), others' changes only. used: IDs this user loaded recently."""
    added = updated = 0
    mine = []
    used = set(used or [])
    for e in (changelog or {}).get('entries') or []:
        if (e.get('time') or u'') <= seen_until or (me and e.get('by') == me):
            continue
        if e.get('action') == 'added':
            added += 1
        elif e.get('action') == 'updated':
            updated += 1
            if e.get('id') in used and e.get('id') not in mine:
                mine.append(e.get('id'))
    parts = []
    if added:
        parts.append(u'{0} new'.format(added))
    if updated:
        parts.append(u'{0} updated'.format(updated))
    if not parts:
        return u''
    text = u', '.join(parts) + u' famil' + (u'y' if added + updated == 1 else u'ies')
    if mine:
        text += u' - updated that you use: ' + u', '.join(mine[:3]) + (u'…' if len(mine) > 3 else u'')
    return text


def check(toast=True):
    cfg = config.load()
    if cfg['backend'] != 'http' or not cfg.get('url') or not _due(cfg):
        return None
    key = keystore.load()
    if not key:
        return None
    from peer_library.backend_http import HttpBackend
    b = HttpBackend(cfg, key=key)
    log_data = b.get_changelog()
    seen = cfg.get('seen_until') or u''
    if not seen:                                   # first run here: start from now
        config.save_local(seen_until=latest_time(log_data), notify_checked=_now())
        return None
    lines = []
    from peer_library import userprefs
    prefs = userprefs.load()
    news = news_text(log_data, seen, cfg.get('user'), prefs['recent'] + prefs['favorites'])
    if news:
        lines.append(u'Library: ' + news + u'. Open PEER → Library → What’s new.')
    if cfg.get('role') == 'admin':
        try:
            n_prop = sum(1 for p in b.list_proposals() if p.get('status') == 'pending')
            n_acc = len(b.list_access_requests())
            if n_prop:
                lines.append(u'{0} proposal(s) wait in Inbox.'.format(n_prop))
            if n_acc:
                lines.append(u'{0} access request(s) wait in Keys.'.format(n_acc))
        except Exception as ex:
            log.write(u'notify admin counts: {0}'.format(ex))
    config.save_local(notify_checked=_now())
    text = u' '.join(lines)
    if text and toast:
        from pyrevit.forms import toaster
        toaster.send_toast(text, title=u'PEER Library')
    return text


def check_async():
    def run():
        try:
            check()
        except Exception as ex:
            log.write(u'startup notify: {0}'.format(ex))
    t = threading.Thread(target=run, name='peer_library_notify')
    t.daemon = True
    t.start()
    return t


def mark_seen(changelog):
    """Called when the library window opens."""
    t = latest_time(changelog)
    if t:
        config.save_local(seen_until=t)
