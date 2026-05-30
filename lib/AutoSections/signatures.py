# -*- coding: utf-8 -*-
"""Group elements by their node's uniqueness key.

Per-element analysis lives in nodes.analyze; this module only buckets elements
and keeps, for each bucket, the representative's node descriptor so sections.py
can rebuild the exact box.
"""

from collections import OrderedDict

from AutoSections import nodes as N


def build_groups(doc, targets):
    """Bucket targets by node key.

    Returns (groups, errors):
        groups - OrderedDict key -> {"desc": <rep node>, "members": [(kind, elem)]}
                 in first-seen order; the representative is members[0].
        errors - ["<id>: <message>", ...] for elements that failed or had no
                 usable location.
    """
    groups = OrderedDict()
    errors = []
    for kind, elem in targets:
        try:
            res = N.analyze(doc, kind, elem)
        except Exception as e:
            errors.append('{}: {}'.format(elem.Id, str(e)))
            continue
        if res is None:
            errors.append('{}: no usable location'.format(elem.Id))
            continue
        key, desc = res
        g = groups.get(key)
        if g is None:
            groups[key] = {'desc': desc, 'members': [(kind, elem)]}
        else:
            g['members'].append((kind, elem))
    return groups, errors
