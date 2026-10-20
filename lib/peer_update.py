# -*- coding: utf-8 -*-
"""Keep an installed PEER extension identical to GitHub main.

Called from startup.py on every Revit start and every pyRevit Reload.
"""
# pyRevit сам делает git pull при старте и Reload (autoupdate), но молча пропускает
# обновление, если у сотрудника изменён файл из репозитория (открыл .rfa из папки кнопки
# и сохранил и т.п.). Здесь после pull папка доводится до origin/main (reset --hard):
# локальные правки в файлах репозитория стираются, новые файлы (логи, кэш) не трогаются.
#
# Работает ТОЛЬКО на установке сотрудника: папка в %APPDATA%\pyRevit\Extensions (так ставит
# install.bat) и ветка main. Рабочая копия автора (Desktop, ветка dev) не трогается никогда.
#
# Правки скриптов и lib действуют сразу (pyRevit читает script.py при нажатии); новые /
# удалённые кнопки появятся после следующего Reload — ленту pyRevit собрал до startup.py.

import os
import io
import datetime

BRANCH = 'main'
# FileStatus: NewInWorkdir (неотслеживаемый) = 128, Ignored = 16384 - такие файлы не мешают
_HARMLESS = 128 | 16384


def _log(lines):
    try:
        base = os.environ.get('TEMP') or os.path.expanduser('~')
        folder = os.path.join(base, 'peer_revit_logs')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with io.open(os.path.join(folder, 'peer_update.log'), 'w', encoding='utf-8') as f:
            f.write(u'{0}\n'.format(stamp))
            for x in lines:
                f.write(u'{0}\n'.format(x))
    except Exception:
        pass


def _installed_by_installer(ext_dir):
    root = os.path.join(os.environ.get('APPDATA', ''), 'pyRevit', 'Extensions')
    a = os.path.normcase(os.path.abspath(ext_dir))
    b = os.path.normcase(os.path.abspath(root))
    return bool(os.environ.get('APPDATA')) and a.startswith(b + os.sep)


def sync(ext_dir, any_path=False):
    """-> (status, details). status: skip / clean / updated / error."""
    if not any_path and not _installed_by_installer(ext_dir):
        return 'skip', u'not an installed copy (author working folder): ' + ext_dir
    if not os.path.isdir(os.path.join(ext_dir, '.git')):
        return 'skip', u'not a git clone'

    from pyrevit.coreutils import git
    lg = git.libgit
    repo_info = git.get_repo(ext_dir)
    try:
        return _sync_repo(git, lg, repo_info)
    finally:
        # отпустить файлы .git (иначе Revit держит их открытыми до закрытия)
        try:
            repo_info.repo.Dispose()
        except Exception:
            pass


def _sync_repo(git, lg, repo_info):
    repo = repo_info.repo
    if repo.Head.FriendlyName != BRANCH:
        return 'skip', u'branch is ' + repo.Head.FriendlyName
    if repo.Head.TrackedBranch is None:
        return 'skip', u'branch has no remote'

    # fetch всегда свой: на autoupdate pyRevit не полагаемся (бывает выключен, бывает молча
    # не срабатывает). Нет сети — сверяемся с тем, что уже скачано.
    try:
        git.git_fetch(repo_info)
        fetched = u'ok'
    except Exception as ex:
        fetched = u'failed (offline?): {0}'.format(ex)

    target = repo.Head.TrackedBranch.Tip
    head = repo.Head.Tip
    changed = []
    for e in repo.RetrieveStatus(lg.StatusOptions()):
        if int(e.State) & ~_HARMLESS:
            changed.append(e.FilePath)
    if head.Sha == target.Sha and not changed:
        return 'clean', u'{0} (fetch {1})'.format(head.Sha[:7], fetched)

    repo.Reset(lg.ResetMode.Hard, target)
    det = u'{0} -> {1} (fetch {2})'.format(head.Sha[:7], target.Sha[:7], fetched)
    if changed:
        det += u'; local edits discarded: ' + u', '.join(changed[:30])
    return 'updated', det


def run(ext_dir=None):
    # папка расширения = родитель lib/, где лежит этот модуль
    if ext_dir is None:
        ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        status, det = sync(ext_dir)
    except Exception as ex:
        status, det = 'error', u'{0}'.format(ex)
    _log([u'PEER update: ' + status, det])
    return status, det
