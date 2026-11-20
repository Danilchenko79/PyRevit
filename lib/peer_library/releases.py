# -*- coding: utf-8 -*-
"""Releases on the service: the PEER package ('ext') and the project template
('template'). Pure helpers - which version a computer should run.

Manifest (GET /release/<product>/manifest):
    {"channels": {"stable": "2026.11.20.1", "beta": "2026.11.21.1"},
     "versions": [{"version", "size", "sha1", "note", "time", "by", "name"}, ...]}
A channel is a pointer: "roll back" on the service = the pointer moves to an
older version, and every computer follows it (so the test is "differs", not
"newer").
"""

EXT, BOOT, TEMPLATE = 'ext', 'boot', 'template'      # boot = the public loader
STABLE, BETA = 'stable', 'beta'


def vkey(version):
    """'2026.11.20.1' -> (2026, 11, 20, 1); junk sorts first."""
    out = []
    for part in (u'{0}'.format(version or u'')).split(u'.'):
        try:
            out.append(int(part))
        except ValueError:
            return ()
    return tuple(out)


def entry(manifest, version):
    for v in (manifest or {}).get('versions') or []:
        if v.get('version') == version:
            return v
    return None


def target(manifest, channel=STABLE):
    """The version entry this computer should run, or None (nothing published).
    A beta computer follows stable whenever stable is newer than beta (or
    there is no beta) - it never stays behind everybody else."""
    channels = (manifest or {}).get('channels') or {}
    stable = channels.get(STABLE) or u''
    want = stable
    if channel == BETA:
        beta = channels.get(BETA) or u''
        if beta and vkey(beta) >= vkey(stable):
            want = beta
    return entry(manifest, want) if want else None


def news(manifest, installed, channel=STABLE, limit=5):
    """Notes of the versions newer than the installed one, newest first, up to
    the version the channel points at: [(version, note)]."""
    goal = target(manifest, channel)
    if goal is None:
        return []
    top, have = vkey(goal['version']), vkey(installed)
    rows = [(v['version'], v.get('note') or u'') for v in (manifest or {}).get('versions') or []
            if have < vkey(v['version']) <= top]
    rows.sort(key=lambda r: vkey(r[0]), reverse=True)
    return rows[:limit]


def next_version(manifest, today):
    """Next package version of a day: '2026.11.20' -> '2026.11.20.N'."""
    n = 0
    for v in (manifest or {}).get('versions') or []:
        k = vkey(v.get('version'))
        if len(k) == 4 and u'.'.join(u'{0:02d}'.format(x) if i else u'{0}'.format(x)
                                     for i, x in enumerate(k[:3])) == today:
            n = max(n, k[3])
    return u'{0}.{1}'.format(today, n + 1)
