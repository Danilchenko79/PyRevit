# -*- coding: utf-8 -*-
"""Full error texts go to %APPDATA%/PEER/library.log; the user sees one line."""

import datetime
import io
import os
import traceback

MAX_BYTES = 2 * 1024 * 1024


def log_file():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'PEER', 'library.log')


def write(message, exc=False):
    path = log_file()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
            old = path + '.1'
            if os.path.exists(old):
                os.remove(old)
            os.rename(path, old)
        text = u'{0}  {1}\n'.format(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    message)
        if exc:
            tb = traceback.format_exc()
            if not isinstance(tb, type(u'')):
                tb = tb.decode('utf-8', 'replace')
            text += tb + u'\n'
        with io.open(path, 'a', encoding='utf-8') as f:
            f.write(text)
    except Exception:  # logging must never break the button
        pass
