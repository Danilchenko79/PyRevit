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

# Панель Library видна только там, где библиотека настроена (адрес сервиса в
# lib/peer_library/settings.json или на этом компьютере): без настройки её кнопки не работают.
try:
    from peer_library import config as _peer_library_config
    if not _peer_library_config.panel_visible():
        from pyrevit.coreutils import ribbon as _peer_ribbon
        for _tab in _peer_ribbon.get_current_ui().get_pyrevit_tabs():
            if _tab.name == 'PEER':
                _panel = _tab.find_child('Library')
                if _panel is not None:
                    _panel.visible = False
except Exception:
    pass

# В фоне: уведомление «что нового в библиотеке семейств» (раз в 6 часов, только с ключом),
# админам - сколько ждут предложений и заявок на доступ. Логика - lib/peer_library/notify.py.
try:
    from peer_library import notify as _peer_library_notify
    _peer_library_notify.check_async()
except Exception:
    pass
