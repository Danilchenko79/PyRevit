# -*- coding: utf-8 -*-
"""PEER startup: keep the installed extension identical to GitHub main."""
# Запускается pyRevit при каждом старте Revit и каждом Reload. Логика - lib/peer_update.py.
try:
    import peer_update
    peer_update.run()
except Exception:
    pass

# Издание PEER_dev рядом с обычным PEER (две вкладки в одном Revit): фоновые дела, общие для
# обоих (телеметрия, шаблон, уведомления библиотеки), делает только обычный PEER.
try:
    from peer_library import version as _peer_version
    _peer_secondary = _peer_version.is_secondary()
except Exception:
    _peer_secondary = False

# Файловая телеметрия pyRevit (%APPDATA%\PEER\telemetry): из неё Contact берёт текст
# последних ошибок кнопок PEER, а лист Usage - запуски кнопок. Логика - lib/peer_feedback/runs.py.
try:
    if _peer_secondary:
        raise RuntimeError('the everyday PEER does this')
    from peer_feedback import runs as _peer_runs
    _peer_runs.ensure_telemetry()
except Exception:
    pass

# В фоне, старт Revit не ждёт: итоги запусков за прошедшие дни в очередь, затем отправка
# очереди (и запросов Contact, не ушедших раньше). Логика - lib/peer_feedback/usage.py.
try:
    if _peer_secondary:
        raise RuntimeError('the everyday PEER does this')
    from peer_feedback import usage as _peer_usage
    _peer_usage.upload_async()
except Exception:
    pass

# Панели Library и Account видны только там, где настроен сервис (адрес в
# lib/peer_library/settings.json или на этом компьютере). Если в настройках включён замок
# (access_lock) и на компьютере нет действующего ключа - остальные панели PEER скрыты, остаются
# Account и Feedback. Затем в фоне ключ сверяется с сервисом (отозванный ключ забывается,
# без сети действует последняя проверка, 14 дней). Логика - lib/peer_library/access.py.
try:
    from peer_library import access as _peer_access
    _peer_access.startup()
except Exception:
    pass

# В фоне: шаблон проекта компании (%LOCALAPPDATA%/PEER/Templates/PR_Template Concrete.rte) доводится
# до версии, выпущенной на сервисе; после обновления - уведомление «что нового».
# Логика - lib/peer_library/template_sync.py.
try:
    if _peer_secondary:
        raise RuntimeError('the everyday PEER does this')
    from peer_library import template_sync as _peer_template
    _peer_template.run_async(_peer_template.toast)
except Exception:
    pass

# В фоне: уведомление «что нового в библиотеке семейств» (раз в 6 часов, только с ключом),
# админам - сколько ждут предложений и заявок на доступ. Логика - lib/peer_library/notify.py.
try:
    if _peer_secondary:
        raise RuntimeError('the everyday PEER does this')
    from peer_library import notify as _peer_library_notify
    _peer_library_notify.check_async()
except Exception:
    pass
