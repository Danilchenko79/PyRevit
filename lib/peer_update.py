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
def _work_dir(ext_dir=None):
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    try:
        from peer_library import version
        if ext_dir and version.edition(ext_dir) == 'dev':
            return os.path.join(base, 'PEER', 'Update_dev')
    except Exception:
        pass
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


def _package_setup(ext_dir, any_path=False):
    """(None, cfg, backend, channel) for an installation the package way applies to,
    else (('skip', reason), None, None, None)."""
    if not any_path and not _installed_by_installer(ext_dir):
        return ('skip', u'not an installed copy (author working folder): ' + ext_dir), None, None, None
    from peer_library import config, version
    cfg = config.load()
    if cfg['backend'] != 'http' or not config.is_configured(cfg):
        return ('skip', u'the PEER service is not set up on this computer'), None, None, None
    if os.path.isfile(os.path.join(ext_dir, '.git', 'HEAD')) and git_branch(ext_dir) != BRANCH:
        return ('skip', u'git clone on branch "{0}" - left as it is'.format(git_branch(ext_dir) or u'?')), None, None, None
    # PEER.extension follows stable, PEER_dev.extension follows beta; a git clone being
    # converted is the everyday PEER
    return None, cfg, config.make_backend(cfg), version.channel_of(ext_dir)


def check_package(ext_dir, any_path=False):
    """Is there a package to install? Touches nothing in the installation.
    -> (status, details); 'needed' = downloaded, ready for sync_package()."""
    stop, cfg, backend, channel = _package_setup(ext_dir, any_path)
    if stop:
        return stop
    from peer_library import ext_update, releases, version
    status, det = ext_update.check(ext_dir, backend, channel, _work_dir(ext_dir))
    if status == 'nokey' and version.is_loader(ext_dir):     # not signed in: the loader itself
        st2, det2 = ext_update.check(ext_dir, backend, channel, _work_dir(ext_dir), releases.BOOT)
        if st2 == 'needed':
            return 'needed', u'loader ' + det2
    return status, det


def sync_package(ext_dir, any_path=False):
    """-> (status, details). status: skip / nokey / none / offline / clean /
    updated / partial / error (see peer_library/ext_update.py)."""
    stop, cfg, backend, channel = _package_setup(ext_dir, any_path)
    if stop:
        return stop
    from peer_library import ext_update, releases, version
    was_git = os.path.isdir(os.path.join(ext_dir, '.git'))
    old = _git_tracked(ext_dir) if was_git and not ext_update.installed_files(ext_dir) else None
    status, det = ext_update.sync(ext_dir, backend, channel, _work_dir(ext_dir), old)
    if status == 'nokey':
        if version.is_loader(ext_dir):           # not signed in yet: keep the loader itself current
            st2, det2 = ext_update.sync(ext_dir, backend, channel, _work_dir(ext_dir), None, releases.BOOT)
            det += u'; loader: {0} {1}'.format(st2, det2)
            if st2 in ('updated', 'partial'):
                status = st2
    if was_git and status in ('updated', 'clean'):
        note = _drop_git(ext_dir)
        if note:
            det += u'; ' + note
    return status, det


def _announce(ext_dir, was_loader):
    """Notification after an update: what came."""
    try:
        from peer_library import jsonio, releases, strings, version as _v
        from pyrevit.forms import toaster
        if _v.is_loader(ext_dir):
            return
        if was_loader:
            toaster.send_toast(strings.UPD_FULL_TEXT_AUTO, title=strings.UPD_FULL_TITLE)
            return
        ver = _v.get(ext_dir)['version']
        entry = releases.entry(jsonio.read(os.path.join(_work_dir(ext_dir), 'ext_manifest.json')), ver) or {}
        note = (entry.get('note') or u'').strip().split(u'\n')[0][:160]
        toaster.send_toast(note or strings.UPD_DONE_PLAIN, title=strings.UPD_DONE_TITLE.format(_v.text(ext_dir, u'')))
    except Exception:
        pass


RELOADS_ENV = 'PEER_UPDATE_RELOADS'      # automatic reloads in this Revit session (a safety limit)
MAX_RELOADS = 3


def apply_and_reload(ext_dir, reload_fn=None):
    """Install the waiting package and reload pyRevit. Runs when Revit is idle,
    AFTER pyRevit has finished drawing the ribbon: pyRevit reads the folders
    first and draws the buttons later, so moving folders in between makes it
    look for buttons that are no longer there (errors in the pyRevit window).
    -> (status, details)."""
    try:
        from peer_library import version as _v
        was_loader = _v.is_loader(ext_dir)
    except Exception:
        was_loader = False
    try:
        status, det = sync_package(ext_dir)
    except Exception as ex:
        status, det = 'error', u'{0}'.format(ex)
    lines = [u'PEER update (package, after the ribbon was built): ' + status, det]
    if status == 'updated':
        n = int(os.environ.get(RELOADS_ENV) or 0)
        if n < MAX_RELOADS:
            os.environ[RELOADS_ENV] = str(n + 1)
            lines.append(u'reloading pyRevit ({0})'.format(n + 1))
            _log(lines)
            _announce(ext_dir, was_loader)
            try:
                if reload_fn is None:
                    from pyrevit.loader import sessionmgr
                    reload_fn = sessionmgr.reload_pyrevit
                reload_fn()
            except Exception as ex:
                _log(lines + [u'reload failed: {0}'.format(ex)])
            return status, det
        lines.append(u'too many automatic reloads in this session - press pyRevit -> Reload')
    _log(lines)
    return status, det


def _when_idle(action):
    """Run action() once, the first time Revit is idle. True = scheduled."""
    try:
        from pyrevit import HOST_APP
        from System import EventHandler
        from Autodesk.Revit.UI.Events import IdlingEventArgs
        uiapp = HOST_APP.uiapp
        box = {}

        def on_idle(sender, args):
            try:
                uiapp.Idling -= box['h']
            except Exception:
                pass
            if box.get('done'):
                return
            box['done'] = True
            try:
                action()
            except Exception as ex:
                _log([u'PEER update when idle: error', u'{0}'.format(ex)])

        box['h'] = EventHandler[IdlingEventArgs](on_idle)
        uiapp.Idling += box['h']
        return True
    except Exception:
        return False


def run(ext_dir=None):
    # папка расширения = родитель lib/, где лежит этот модуль
    if ext_dir is None:
        ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    lines = []
    # 1. Пакет с сервиса: при старте только смотрим и скачиваем. Ставим позже, когда pyRevit
    #    дорисует ленту (иначе он ищет кнопки по старым путям и сыплет ошибками), и сразу
    #    перезагружаем pyRevit - новая версия видна в тот же запуск, без ручного Reload.
    try:
        status, det = check_package(ext_dir)
    except Exception as ex:
        status, det = 'error', u'{0}'.format(ex)
    lines += [u'PEER update (package): ' + status, det]
    if status == 'needed':
        if _when_idle(lambda: apply_and_reload(ext_dir)):
            lines.append(u'will be installed when the ribbon is ready')
            _log(lines)
            return status, det
        try:                                   # no way to wait: the old immediate way
            status, det = sync_package(ext_dir)
        except Exception as ex:
            status, det = 'error', u'{0}'.format(ex)
        lines += [u'PEER update (package, at once): ' + status, det]
    # 2. Пакет не применим и установка ещё из git - старый способ (пока репозиторий открыт)
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
