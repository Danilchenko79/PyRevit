# -*- coding: utf-8 -*-
"""peer_log — единый структурированный лог прогона для кнопок PeerTest.

Лежит в lib/ корня extension'а, поэтому импортируется из любой кнопки:

    from peer_log import RunLog

    log = RunLog('RebarUnify')                      # имя кнопки
    log.processed(u'Rebar 12345', u'PR_A 100->120')
    log.skipped(u'Rebar 67890', u'нет PR_A')
    try:
        ...
    except Exception as e:
        log.error(u'Rebar 11111', str(e))
    log.finish(summary=u'Унифицировано 14 стержней')

`finish()` пишет ДВА файла в %TEMP%/peer_revit_logs/ и печатает сводку
в pyRevit output:
    last_run.json            — всегда последний прогон (стабильный путь для reviewer)
    <button>_<timestamp>.json — архивная копия

Совместимо с IronPython 2.7 (стандарт pyRevit в этом extension'е).
"""

import os
import json
import codecs
import datetime


def _log_dir():
    base = os.environ.get('TEMP') or os.environ.get('TMP') or os.path.expanduser('~')
    path = os.path.join(base, 'peer_revit_logs')
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError:
            pass
    return path


class RunLog(object):
    def __init__(self, button):
        self.button = button
        self.started = datetime.datetime.now()
        self.finished = None
        self._processed = []
        self._skipped = []
        self._errors = []

    # --- регистрация событий ---
    def processed(self, item, reason=u''):
        self._processed.append({'item': self._u(item), 'reason': self._u(reason)})

    def skipped(self, item, reason=u''):
        self._skipped.append({'item': self._u(item), 'reason': self._u(reason)})

    def error(self, item, reason=u''):
        self._errors.append({'item': self._u(item), 'reason': self._u(reason)})

    # --- завершение ---
    def finish(self, summary=u''):
        self.finished = datetime.datetime.now()
        data = {
            'button': self.button,
            'started': self.started.strftime('%Y-%m-%d %H:%M:%S'),
            'finished': self.finished.strftime('%Y-%m-%d %H:%M:%S'),
            'summary': self._u(summary),
            'counts': {
                'processed': len(self._processed),
                'skipped': len(self._skipped),
                'errors': len(self._errors),
            },
            'processed': self._processed,
            'skipped': self._skipped,
            'errors': self._errors,
        }
        self._write(data)
        self._print(data)
        return data

    # --- внутреннее ---
    def _write(self, data):
        d = _log_dir()
        ts = self.started.strftime('%Y%m%d_%H%M%S')
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        for name in ('last_run.json', '%s_%s.json' % (self.button, ts)):
            try:
                with codecs.open(os.path.join(d, name), 'w', 'utf-8') as f:
                    f.write(text)
            except (IOError, OSError):
                pass

    def _print(self, data):
        try:
            from pyrevit import script
            out = script.get_output()
            c = data['counts']
            out.print_md(u'**{0}** — {1}'.format(self.button, data['summary']))
            out.print_md(
                u'обработано: **{0}** · пропущено: **{1}** · ошибок: **{2}**'.format(
                    c['processed'], c['skipped'], c['errors']))
            if self._errors:
                out.print_md(u'### Ошибки')
                for e in self._errors:
                    out.print_md(u'- {0}: {1}'.format(e['item'], e['reason']))
        except Exception:
            # вне pyRevit (например, локальный прогон) — молча
            pass

    @staticmethod
    def _u(x):
        if isinstance(x, unicode):
            return x
        try:
            return unicode(x, 'utf-8')
        except (TypeError, UnicodeDecodeError):
            return unicode(x)
