# -*- coding: utf-8 -*-
"""Keep an installed PEER extension up to date.

Called from startup.py on every Revit start and every pyRevit Reload.
"""
# Два способа доставки, выбор автоматический:
#
# 1. ПАКЕТ с сервиса PEER (новый способ, GitHub не нужен). Есть ключ PEER на компьютере и на
#    сервисе опубликован пакет - папка доводится до пакета (lib/peer_library/ext_update.py):
#    скачать zip один раз, сверить SHA-1, заменить изменённые файлы, убрать удалённые.
#    Установка из git при этом сама превращается в пакетную: появляется version.json,
#    папка .git удаляется (если занята - после закрытия Revit).
# 2. GIT (старый способ, пока репозиторий открыт). pyRevit сам делает git pull при старте и
#    Reload, но молча пропускает обновление, если у сотрудника изменён файл из репозитория.
#    Здесь после pull папка доводится до origin/main (reset --hard). Работает, только пока
#    установка ещё не пакетная: нет ключа, или пакет на сервисе ещё не опубликован.
#
# Оба способа работают ТОЛЬКО на установке сотрудника: папка в %APPDATA%\pyRevit\Extensions
# (так ставит установщик). Рабочая копия автора (Desktop, ветка dev) не трогается никогда.
#
# Правки скриптов и lib действуют сразу (pyRevit читает script.py при нажатии); новые /
# удалённые кнопки появятся после следующего Reload - ленту pyRevit собрал до startup.py.

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


# ---- package from the PEER service ----------------------------------------------------
def _work_dir():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'PEER', 'Update')


def _git_tracked(ext_dir):
    """Files git tracks in a clone: the list of what PEER owns there, so files deleted
    from PEER later are removed when the clone becomes a package installation."""
    try:
        from pyrevit.coreutils import git
        info = git.get_repo(ext_dir)
        try:
            return dict((e.Path.replace(u'\\', u'/'), u'') for e in info.repo.Index)
        finally:
            info.repo.Dispose()
    except Exception:
        return {}


def _drop_git(ext_dir):
    """Remove .git of a converted installation. pyRevit may still hold its pack
    files open in this Revit: then only HEAD is removed - without it the folder
    is not a git repository any more, pyRevit stops opening (and pulling) it,
    and the next Revit start removes the rest. No helper process is started."""
    git_dir = os.path.join(ext_dir, '.git')
    if not os.path.isdir(git_dir):
        return u''
    try:
        from peer_library import ext_update
        if ext_update._rmtree(git_dir):
            return u'.git removed'
    except Exception:
        pass
    head = os.path.join(git_dir, 'HEAD')
    try:
        if os.path.isfile(head):
            os.chmod(head, 0o666)
            os.remove(head)
        return u'.git is in use - switched off, the rest is removed at the next Revit start'
    except (IOError, OSError) as ex:
        return u'.git not removed: {0}'.format(ex)


def git_branch(ext_dir):
    """Branch of a clone from .git/HEAD ('' = not a clone or detached)."""
    try:
        with io.open(os.path.join(ext_dir, '.git', 'HEAD'), 'r', encoding='utf-8') as f:
            head = f.read().strip()
    except (IOError, OSError):
        return u''
    return head[len('ref: refs/heads/'):] if head.startswith('ref: refs/heads/') else u''


def sync_package(ext_dir, any_path=False):
    """-> (status, details). status: skip / nokey / none / offline / clean /
    updated / partial / error (see peer_library/ext_update.py)."""
    if not any_path and not _installed_by_installer(ext_dir):
        return 'skip', u'not an installed copy (author working folder): ' + ext_dir
    from peer_library import config, ext_update
    cfg = config.load()
    if cfg['backend'] != 'http' or not config.is_configured(cfg):
        return 'skip', u'the PEER service is not set up on this computer'
    backend = config.make_backend(cfg)
    was_git = os.path.isdir(os.path.join(ext_dir, '.git'))
    if was_git and os.path.isfile(os.path.join(ext_dir, '.git', 'HEAD')) and git_branch(ext_dir) != BRANCH:
        return 'skip', u'git clone on branch "{0}" - left as it is'.format(git_branch(ext_dir) or u'?')
    old = _git_tracked(ext_dir) if was_git and not ext_update.installed_files(ext_dir) else None
    status, det = ext_update.sync(ext_dir, backend, cfg.get('channel') or 'stable', _work_dir(), old)
    if was_git and status in ('updated', 'clean'):
        note = _drop_git(ext_dir)
        if note:
            det += u'; ' + note
    return status, det


def run(ext_dir=None):
    # папка расширения = родитель lib/, где лежит этот модуль
    if ext_dir is None:
        ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    lines = []
    try:
        status, det = sync_package(ext_dir)
    except Exception as ex:
        status, det = 'error', u'{0}'.format(ex)
    lines += [u'PEER update (package): ' + status, det]
    # пакет не сработал и установка ещё из git - старый способ (пока репозиторий открыт)
    if status in ('skip', 'nokey', 'none', 'offline', 'error') and \
            os.path.isdir(os.path.join(ext_dir, '.git')) and \
            not os.path.isfile(os.path.join(ext_dir, 'version.json')):
        try:
            status, det = sync(ext_dir)
        except Exception as ex:
            status, det = 'error', u'{0}'.format(ex)
        lines += [u'PEER update (git): ' + status, det]
    _log(lines)
    return status, det
