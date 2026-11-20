# -*- coding: utf-8 -*-
"""About PEER: the installed version, what came with it, where it is installed,
who is signed in; check for updates; the wiki."""

import os

from pyrevit import forms

from peer_library import access, config, jsonio, log, releases, strings, version

XAML = os.path.join(version.bundle_dir('About.pushbutton'), 'AboutWindow.xaml')


def facts(folder=None, cfg=None, st=None, manifest=None):
    """Pure: what the window shows. {'name', 'version', 'built', 'kind', 'note', 'folder', 'who', 'wiki'}"""
    folder = folder or version.ext_dir()
    cfg = cfg or {}
    v = version.get(folder)
    kind = {'package': strings.ABOUT_KIND_PACKAGE, 'git': strings.ABOUT_KIND_GIT}.get(v['kind'], strings.ABOUT_KIND_DEV)
    if v['kind'] == 'package' and v['flavor'] == 'boot':
        kind = strings.ABOUT_KIND_LOADER
    note = u''
    entry = releases.entry(manifest, v['version']) if manifest else None
    if entry:
        note = (entry.get('note') or u'').strip()
    who = strings.ACC_ST_NONE
    if st is not None and st.signed_in:
        who = u'{0} ({1})'.format(st.name, strings.ACC_ROLE_ADMIN if st.role == 'admin' else strings.ACC_ROLE_USER)
    return {'name': u'PEER dev' if v['edition'] == 'dev' else u'PEER',
            'version': v['version'], 'built': (v.get('built') or u'').replace(u'T', u' ')[:16],
            'kind': kind, 'note': note, 'folder': folder, 'who': who,
            'wiki': (cfg.get('wiki_url') or u'').strip()}


def open_wiki(cfg=None):
    """Opens the company PEER site. False = the address is not set yet."""
    url = ((cfg or config.load()).get('wiki_url') or u'').strip()
    if not (url.startswith('https://') or url.startswith('http://')):
        return False
    from System.Diagnostics import Process
    Process.Start(url)
    return True


class AboutWindow(forms.WPFWindow):

    def __init__(self, xaml=None):
        forms.WPFWindow.__init__(self, xaml or XAML)
        self.update_now = False
        self.render()

    def render(self):
        import peer_update
        folder = version.ext_dir()
        cfg = config.load()
        try:
            st = access.status(cfg)
        except Exception:
            st = None
        manifest = jsonio.read(os.path.join(peer_update._work_dir(folder), 'ext_manifest.json'))
        f = facts(folder, cfg, st, manifest)
        self.name_text.Text = f['name']
        self.version_text.Text = strings.ABOUT_VERSION.format(f['version'])
        self.kind_text.Text = f['kind'] + (u' · ' + f['built'] if f['built'] else u'')
        self.note_text.Text = f['note'] or strings.ABOUT_NO_NOTE
        self.folder_text.Text = f['folder']
        self.who_text.Text = f['who']
        self.wiki_btn.IsEnabled = bool(f['wiki'])
        self.wiki_btn.ToolTip = f['wiki'] or strings.WIKI_NOT_SET
        installed = version.get(folder)['kind'] == 'package'
        self.update_btn.IsEnabled = installed
        if not installed:
            from System.Windows.Media import Brushes
            self.update_btn.Foreground = Brushes.Gray      # white text is unreadable on a disabled button
            self.status_text.Text = strings.ABOUT_NOT_INSTALLED

    def on_key(self, sender, args):
        from System.Windows.Input import Key
        if args.Key == Key.Escape:
            self.Close()

    def on_close(self, sender, args):
        self.Close()

    def on_wiki(self, sender, args):
        if not open_wiki():
            self.status_text.Text = strings.WIKI_NOT_SET

    def on_update(self, sender, args):
        import peer_update
        self.status_text.Text = strings.ABOUT_CHECKING
        try:
            from peer_library import ui_common as U
            U.refresh(self)
        except Exception:
            pass
        try:
            status, det = peer_update.check_package(version.ext_dir())
        except Exception as ex:
            log.write(u'about: check', exc=True)
            status, det = 'error', u'{0}'.format(ex)
        if status == 'needed':
            self.update_now = True
            self.Close()
            return
        self.status_text.Text = {
            'clean': strings.ABOUT_UP_TO_DATE, 'none': strings.ABOUT_UP_TO_DATE,
            'offline': strings.ABOUT_OFFLINE, 'nokey': strings.ABOUT_NOKEY,
        }.get(status, u'{0}'.format(det))


def show():
    win = AboutWindow()
    win.ShowDialog()
    if win.update_now:
        import peer_update
        forms.alert(strings.ABOUT_UPDATING, title=strings.ABOUT_TITLE)
        peer_update.apply_and_reload(version.ext_dir())
