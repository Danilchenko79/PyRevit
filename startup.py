# -*- coding: utf-8 -*-
"""PEER startup: keep the installed extension identical to GitHub main."""
# Запускается pyRevit при каждом старте Revit и каждом Reload. Логика - lib/peer_update.py.
try:
    import peer_update
    peer_update.run()
except Exception:
    pass

# Файловая телеметрия pyRevit (%APPDATA%\PEER\telemetry): из неё Contact берёт текст
# последних ошибок кнопок PEER, а лист Usage - запуски кнопок. Логика - lib/peer_feedback/runs.py.
try:
    from peer_feedback import runs as _peer_runs
    _peer_runs.ensure_telemetry()
except Exception:
    pass

# В фоне, старт Revit не ждёт: итоги запусков за прошедшие дни в очередь, затем отправка
# очереди (и запросов Contact, не ушедших раньше). Логика - lib/peer_feedback/usage.py.
try:
    from peer_feedback import usage as _peer_usage
    _peer_usage.upload_async()
except Exception:
    pass
