# -*- coding: utf-8 -*-
"""PEER startup: keep the installed extension identical to GitHub main."""
# Запускается pyRevit при каждом старте Revit и каждом Reload. Логика - lib/peer_update.py.
try:
    import peer_update
    peer_update.run()
except Exception:
    pass

# Запросы «Contact», не ушедшие раньше (не было интернета) - отправка в фоне,
# старт Revit не ждёт. Логика - lib/peer_feedback/client.py.
try:
    from peer_feedback import client as _peer_feedback
    _peer_feedback.flush_async()
except Exception:
    pass
