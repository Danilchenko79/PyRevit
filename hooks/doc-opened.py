# -*- coding: utf-8 -*-
# PEER Library: при открытии проекта - уведомление, если в нём есть семейства библиотеки
# старее библиотечной версии. Только сохранённая копия индекса (без сети), ошибки молча.
# Логика - lib/peer_library/project_check.py.
try:
    from peer_library import project_check
    project_check.on_doc_opened(__eventargs__.Document)  # noqa: F821
except Exception:
    pass
