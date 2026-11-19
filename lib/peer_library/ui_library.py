# -*- coding: utf-8 -*-
"""Library window: groups, search, tiles with previews and statuses, details,
load / update / place, type catalogs, What's new, My proposals."""

from pyrevit import forms

from System import TimeSpan  # noqa: E402
from System.Diagnostics import Process  # noqa: E402
from System.Windows import FontWeights, HorizontalAlignment, TextTrimming, TextWrapping, Thickness, \
    VerticalAlignment, Visibility  # noqa: E402
from System.Windows.Controls import Border, CheckBox, Grid, Image, ListBoxItem, \
    Orientation, StackPanel, TextBlock  # noqa: E402
from System.Windows.Documents import Hyperlink, Run  # noqa: E402
from System.Windows.Input import Cursors, Key, Keyboard, ModifierKeys  # noqa: E402
from System.Windows.Media import Stretch  # noqa: E402
from System.Windows.Threading import DispatcherTimer  # noqa: E402

from peer_library import catalog, groups, index, loader, log, strings, userprefs  # noqa: E402
from peer_library import ui_common as U  # noqa: E402
from peer_library.cache import Cache  # noqa: E402

PREVIEWS_PER_TICK = 12
SPECIAL_GROUPS = ('all', 'favorites', 'recent', 'new', 'project', 'outdated', 'popular')


class Item(object):
    def __init__(self, card):
        self.card = card
        self.code = loader.MISSING
        self.pv = None
        self.label = u''
        self.lbi = None
        self.image = None
        self.chip_host = None
        self.preview_done = False
        self.is_new = index.is_new(card)
        self.text = u' '.join([card.get('id', u''), card.get('name', u''),
                               u' '.join(card.get('tags') or []),
                               card.get('revit_category', u''), card.get('description', u''),
                               u' '.join(card.get('types') or [])]).lower()
        self.downloads = 0
        self.users = 0


class LibraryWindow(forms.WPFWindow):

    def __init__(self, xaml_path, doc, uidoc, backend, cfg):
        forms.WPFWindow.__init__(self, xaml_path)
        self.doc, self.uidoc, self.backend, self.cfg = doc, uidoc, backend, cfg
        self.cache = Cache(cfg['cache'], backend)
        self.items = []
        self.current = None
        self.group_key = 'all'
        self.group_keys = []
        self.place_symbol = None
        self.type_boxes = []
        self.online = False
        self.prefs = userprefs.load()
        self.collections = []
        self.is_admin = getattr(backend, 'role', 'user') == 'admin'
        self.proj_rows = []
        self._busy = False
        self._texts()
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(40)
        self.timer.Tick += self._preview_tick
        self.Loaded += self._on_loaded
        self.Closing += lambda s, a: self.timer.Stop()

    # ---- setup ---------------------------------------------------------
    def _texts(self):
        self.Title = strings.TITLE_LIBRARY
        self.search_hint.Text = strings.SEARCH_HINT
        self.tab_library.Header = strings.TAB_LIBRARY
        self.tab_news.Header = strings.TAB_NEWS
        self.tab_mine.Header = strings.TAB_MINE
        self.overwrite_box.Content = strings.OVERWRITE
        self.history_header.Text = strings.HISTORY
        self.types_hint.Text = strings.TYPES_HINT
        self.load_btn.Content = strings.BTN_LOAD
        self.place_btn.Content = strings.BTN_LOAD_PLACE
        self.d_noimage.Text = strings.NO_PREVIEW
        self.user_text.Text = u'{0} · {1}'.format(self.cfg['user'], self.cfg['role'])
        self.tab_project.Header = strings.TAB_PROJECT
        self.catalog_only.Content = strings.FILTER_CATALOG
        self._busy = True
        for s in strings.SORTS:
            self.sort_box.Items.Add(s)
        self.sort_box.SelectedIndex = 0
        self._busy = False
        self.issue_btn.Content = strings.BTN_ISSUE
        self.request_btn.Content = strings.BTN_REQUEST
        self.admin_header.Text = strings.ADMIN_HEADER
        self.edit_btn.Content = strings.BTN_EDIT_INFO
        self.coll_add_btn.Content = strings.BTN_COLL_ADD
        self.coll_remove_btn.Content = strings.BTN_COLL_REMOVE
        self.deprecate_btn.Content = strings.BTN_DEPRECATE
        self.admin_panel.Visibility = Visibility.Visible if self.is_admin else Visibility.Collapsed
        self.proj_update_btn.Content = strings.BTN_PROJ_UPDATE
        self.proj_propose_btn.Content = strings.BTN_PROJ_PROPOSE
        self.proj_refresh_btn.Content = strings.BTN_REFRESH
        self._show_details(None)

    def _on_loaded(self, sender, args):
        self.status_text.Text = strings.LOADING
        self.Cursor = Cursors.Wait
        try:
            self._load()
        except Exception as ex:
            log.write(u'library open', exc=True)
            self.status_text.Text = u'{0}'.format(ex)
        finally:
            self.Cursor = None
        self.search_box.Focus()

    def _load(self):
        idx, self.online = self.cache.index()
        cards = [c for c in idx.get('families', []) if c.get('status') != 'deprecated']
        in_project = loader.project_families(self.doc)
        self.items = [Item(c) for c in cards]
        try:
            stats = self.cache.stats()
        except Exception:
            stats = {}
        try:
            self.collections = self.cache.collections()
        except Exception:
            self.collections = []
        self.tile_list.Items.Clear()
        for it in self.items:
            self._set_status(it, in_project)
            s = stats.get(it.card['id']) or {}
            it.downloads, it.users = s.get('downloads', 0), s.get('users', 0)
            it.lbi = ListBoxItem()
            it.lbi.Content = self._tile(it)
            it.lbi.Tag = it
        self._fill_categories()
        self._sort_items()
        self._fill_groups()
        if self.online:
            self.status_text.Text = strings.ONLINE.format(len(self.items),
                                                          self.cfg.get('root') or self.cfg.get('url'))
        else:
            self.status_text.Text = strings.OFFLINE.format(idx.get('built', u''))
        self.timer.Start()
        if self.online:
            try:                     # startup notifications count news from here on
                from peer_library import notify
                notify.mark_seen(self.cache.changelog())
            except Exception:
                log.write(u'mark seen', exc=True)

    def _set_status(self, it, in_project):
        it.code, it.pv, it.label = loader.status(it.card, in_project)

    # ---- tiles ---------------------------------------------------------
    def _tile(self, it):
        b = Border()
        b.Width, b.Height = 156, 198
        b.Padding = Thickness(6)
        b.Background = U.brush(U.CARD_BG)
        sp = StackPanel()
        g = Grid()
        g.Height = 120
        it.image = Image()
        it.image.Stretch = Stretch.Uniform
        g.Children.Add(it.image)
        if it.is_new:
            badge = U.new_badge()
            badge.HorizontalAlignment = HorizontalAlignment.Left
            badge.VerticalAlignment = VerticalAlignment.Top
            g.Children.Add(badge)
        sp.Children.Add(g)
        t = TextBlock()
        it.name_block = t
        t.Text = self._tile_name(it)
        t.TextWrapping = TextWrapping.Wrap
        t.TextTrimming = TextTrimming.CharacterEllipsis
        t.MaxHeight = 36
        t.FontSize = 12
        t.Margin = Thickness(0, 4, 0, 3)
        sp.Children.Add(t)
        it.chip_host = Border()
        it.chip_host.HorizontalAlignment = HorizontalAlignment.Left
        it.chip_host.Child = U.chip(it.label, it.code)
        sp.Children.Add(it.chip_host)
        b.Child = sp
        b.ToolTip = u'{0}\n{1}'.format(it.card['id'], groups.title(it.card.get('group')))
        return b

    def _tile_name(self, it):
        star = u'★ ' if it.card['id'] in self.prefs['favorites'] else u''
        return star + (it.card.get('name') or it.card['id'])

    def _preview_tick(self, sender, args):
        todo = [it for it in self.items if not it.preview_done
                and it.lbi.Visibility == Visibility.Visible][:PREVIEWS_PER_TICK]
        if not todo:
            todo = [it for it in self.items if not it.preview_done][:PREVIEWS_PER_TICK]
        if not todo:
            self.timer.Stop()
            return
        for it in todo:
            it.preview_done = True
            try:
                path = self.cache.get(it.card, '.png')
            except Exception:
                path = None
            if path:
                it.image.Source = U.bitmap(path, 150)

    # ---- groups & search -----------------------------------------------
    def _fill_groups(self):
        counts = {}
        for it in self.items:
            counts[it.card.get('group')] = counts.get(it.card.get('group'), 0) + 1
        ids = set(i.card['id'] for i in self.items)
        rows = [('all', strings.GROUP_ALL, len(self.items)),
                ('favorites', strings.GROUP_FAVORITES,
                 sum(1 for x in self.prefs['favorites'] if x in ids)),
                ('recent', strings.GROUP_RECENT, sum(1 for x in self.prefs['recent'] if x in ids)),
                ('new', strings.GROUP_NEW, sum(1 for i in self.items if i.is_new)),
                ('project', strings.GROUP_IN_PROJECT,
                 sum(1 for i in self.items if i.code != loader.MISSING)),
                ('outdated', strings.GROUP_OUTDATED,
                 sum(1 for i in self.items if i.code == loader.OUTDATED)),
                ('popular', strings.GROUP_POPULAR, sum(1 for i in self.items if i.downloads))]
        n_special = len(rows)
        for g in groups.GROUPS:
            rows.append((g[0], g[1], counts.get(g[0], 0)))
        n_groups = len(rows)
        for c in self.collections:
            rows.append(('coll:' + c['id'], u'▦ ' + c['name'],
                         sum(1 for x in c.get('families') or [] if x in ids)))
        self.group_list.Items.Clear()
        self.group_keys = []
        for i, (key, title, n) in enumerate(rows):
            t = TextBlock()
            t.Text = u'{0}  ({1})'.format(title, n)
            t.Padding = Thickness(6, 4, 6, 4)
            if key == 'outdated' and n:
                t.FontWeight = FontWeights.SemiBold
            if i == n_special - 1 or (i == n_groups - 1 and self.collections):
                t.Margin = Thickness(0, 0, 0, 8)
            self.group_list.Items.Add(t)
            self.group_keys.append(key)
        self.group_list.SelectedIndex = self.group_keys.index(self.group_key) \
            if self.group_key in self.group_keys else 0

    def _matches(self, it, words):
        k = self.group_key
        if k == 'new' and not it.is_new:
            return False
        if k == 'project' and it.code == loader.MISSING:
            return False
        if k == 'outdated' and it.code != loader.OUTDATED:
            return False
        if k == 'favorites' and it.card['id'] not in self.prefs['favorites']:
            return False
        if k == 'recent' and it.card['id'] not in self.prefs['recent']:
            return False
        if k == 'popular' and not it.downloads:
            return False
        if k.startswith('coll:'):
            coll = self._collection(k[5:])
            if coll is None or it.card['id'] not in (coll.get('families') or []):
                return False
        elif k not in SPECIAL_GROUPS and it.card.get('group') != k:
            return False
        cat = self.category_box.SelectedItem
        if self.category_box.SelectedIndex > 0 and it.card.get('revit_category') != cat:
            return False
        if self.catalog_only.IsChecked and not it.card.get('type_catalog'):
            return False
        return all(w in it.text for w in words)

    def _collection(self, coll_id):
        for c in self.collections:
            if c['id'] == coll_id:
                return c
        return None

    def _fill_categories(self):
        self._busy = True
        cats = sorted(set(i.card.get('revit_category') or u'' for i in self.items) - set([u'']))
        self.category_box.Items.Clear()
        self.category_box.Items.Add(strings.ALL_CATEGORIES)
        for c in cats:
            self.category_box.Items.Add(c)
        self.category_box.SelectedIndex = 0
        self._busy = False

    def _sort_items(self):
        mode = self.sort_box.SelectedIndex
        if mode == 1:        # newest
            key = lambda i: (i.card.get('updated') or u'', i.card['id'].lower())  # noqa: E731
            self.items.sort(key=key, reverse=True)
        elif mode == 2:      # popular
            self.items.sort(key=lambda i: (-i.downloads, (i.card.get('name') or u'').lower()))
        else:                # name
            self.items.sort(key=lambda i: (i.card.get('name') or i.card['id']).lower())
        self.tile_list.Items.Clear()
        for it in self.items:
            self.tile_list.Items.Add(it.lbi)

    def on_sort(self, sender, args):
        if self._busy or not self.items:
            return
        self._sort_items()
        self._apply_filter()

    def on_filter(self, sender, args):
        if self._busy:
            return
        self._apply_filter()

    def _apply_filter(self):
        words = [w for w in (self.search_box.Text or u'').lower().split() if w]
        shown = 0
        for it in self.items:
            ok = self._matches(it, words)
            it.lbi.Visibility = Visibility.Visible if ok else Visibility.Collapsed
            shown += 1 if ok else 0
        self.search_hint.Visibility = Visibility.Collapsed if self.search_box.Text \
            else Visibility.Visible
        if self.online is not None and self.items:
            self.status_text.Text = u'{0} / {1}'.format(shown, len(self.items))
        n_out = sum(1 for i in self.items if i.code == loader.OUTDATED)
        show_all = self.group_key == 'outdated' and n_out > 0
        self.update_all_btn.Visibility = Visibility.Visible if show_all else Visibility.Collapsed
        self.update_all_btn.Content = strings.BTN_UPDATE_ALL.format(n_out)
        in_coll = self.group_key.startswith('coll:')
        self.coll_load_btn.Visibility = Visibility.Visible if in_coll and shown else Visibility.Collapsed
        self.coll_load_btn.Content = strings.BTN_COLL_LOAD.format(shown)
        self.coll_remove_btn.Visibility = Visibility.Visible if in_coll else Visibility.Collapsed
        if self.timer is not None and not self.timer.IsEnabled:
            self.timer.Start()

    def on_search(self, sender, args):
        self._apply_filter()

    def on_group(self, sender, args):
        i = self.group_list.SelectedIndex
        if 0 <= i < len(self.group_keys):
            self.group_key = self.group_keys[i]
            self._apply_filter()

    def on_key(self, sender, args):
        if args.Key == Key.Escape:
            self.Close()
        elif args.Key == Key.F and Keyboard.Modifiers == ModifierKeys.Control:
            self.search_box.Focus()
            self.search_box.SelectAll()
        elif args.Key == Key.Enter and self.current is not None \
                and self.tile_list.IsKeyboardFocusWithin:
            args.Handled = True
            self._do_load(place=Keyboard.Modifiers == ModifierKeys.Shift)
        elif args.Key == Key.Down and self.search_box.IsKeyboardFocusWithin:
            for idx, it in enumerate(self.items):          # first shown tile
                if it.lbi.Visibility == Visibility.Visible:
                    self.tile_list.SelectedIndex = idx
                    it.lbi.Focus()
                    args.Handled = True
                    break

    def on_tab(self, sender, args):
        if args.OriginalSource is not self.tabs:
            return
        if self.tabs.SelectedItem is self.tab_news:
            self._fill_news()
        elif self.tabs.SelectedItem is self.tab_mine:
            self._fill_mine()
        elif self.tabs.SelectedItem is self.tab_project:
            try:
                self._fill_project()
            except Exception as ex:
                log.write(u'project tab', exc=True)
                self.proj_summary.Text = u'{0}'.format(ex)

    # ---- details -------------------------------------------------------
    def on_tile(self, sender, args):
        lbi = self.tile_list.SelectedItem
        self._show_details(lbi.Tag if lbi is not None else None)

    def on_double(self, sender, args):
        if self.current is not None:
            self._do_load(place=True)

    def _show_details(self, it):
        self.current = it
        has = it is not None
        self.details.Visibility = Visibility.Visible if has else Visibility.Hidden
        self.load_btn.IsEnabled = has
        self.place_btn.IsEnabled = has
        self.overwrite_box.IsEnabled = has
        if not has:
            self.status_text.Text = self.status_text.Text or strings.NOTHING_SELECTED
            return
        c = it.card
        try:
            png = self.cache.get(c, '.png')
        except Exception:
            png = None
        self.d_image.Source = U.bitmap(png, 400) if png else None
        self.d_noimage.Visibility = Visibility.Collapsed if png else Visibility.Visible
        self.d_name.Text = c.get('name') or c['id']
        self.d_id.Text = u'{0} · {1} · {2}'.format(c['id'], groups.title(c.get('group')),
                                                           c.get('revit_category') or u'')
        self.d_chips.Children.Clear()
        ch = U.chip(it.label, it.code, small=False)
        ch.Margin = Thickness(0, 0, 6, 0)
        self.d_chips.Children.Add(ch)
        if it.is_new:
            self.d_chips.Children.Add(U.new_badge())
        self.d_version.Text = strings.VERSION_LINE.format(c.get('version'), c.get('updated'))
        self.d_project.Text = strings.PROJECT_LINE.format(it.label)
        self.d_desc.Text = c.get('description') or u''
        self.d_tags.Text = u', '.join(c.get('tags') or [])
        self._help_link(c.get('help_url'))
        self._fill_types(c)
        self.d_history.Children.Clear()
        for h in reversed(c.get('history') or []):
            t = TextBlock()
            t.TextWrapping = TextWrapping.Wrap
            t.Margin = Thickness(0, 0, 0, 3)
            t.Text = u'v{0} · {1} · {2}{3}'.format(
                h.get('v'), h.get('date'), h.get('note') or u'-',
                u' ({0})'.format(h['by']) if h.get('by') else u'')
            self.d_history.Children.Add(t)
        update = it.code in (loader.OUTDATED, loader.UNKNOWN, loader.NEWER, loader.CURRENT)
        self.load_btn.Content = strings.BTN_UPDATE if update else strings.BTN_LOAD
        self.place_btn.Content = strings.BTN_UPDATE_PLACE if update else strings.BTN_LOAD_PLACE
        fav = c['id'] in self.prefs['favorites']
        self.fav_btn.Content = strings.FAV_ON if fav else strings.FAV_OFF
        self.d_stats.Text = strings.STATS_LINE.format(it.downloads, it.users) if it.downloads \
            else u''

    def on_fav(self, sender, args):
        it = self.current
        if it is None:
            return
        userprefs.toggle_favorite(it.card['id'])
        self.prefs = userprefs.load()
        it.name_block.Text = self._tile_name(it)
        self._show_details(it)
        sel = self.group_list.SelectedIndex
        self._fill_groups()
        self.group_list.SelectedIndex = sel
        self._apply_filter()

    def _help_link(self, url):
        self.d_help.Inlines.Clear()
        if not url:
            return
        link = Hyperlink(Run(strings.HELP))
        link.Foreground = U.brush(U.INK)
        link.Click += lambda s, a: Process.Start(url)
        self.d_help.Inlines.Add(link)

    def _fill_types(self, card):
        self.type_boxes = []
        self.types_list.Items.Clear()
        self.types_search.Text = u''
        params, rows = [], []
        if card.get('type_catalog'):
            try:
                path = self.cache.get(card, '.txt')
                if path:
                    params, rows = catalog.read(path)
            except Exception as ex:
                log.write(u'catalog {0}'.format(card['id']), exc=True)
                self.status_text.Text = u'{0}'.format(ex)
        self.types_panel.Visibility = Visibility.Visible if rows else Visibility.Collapsed
        self.types_header.Text = strings.TYPES_HEADER.format(len(rows))
        for name, values in rows:
            cb = CheckBox()
            extra = catalog.short_values(params, values)
            cb.Content = u'{0}    {1}'.format(name, extra) if extra else name
            cb.Tag = name
            cb.Margin = Thickness(2)
            self.type_boxes.append(cb)
            self.types_list.Items.Add(cb)

    def on_types_search(self, sender, args):
        words = (self.types_search.Text or u'').lower().split()
        for cb in self.type_boxes:
            ok = all(w in (u'{0}'.format(cb.Content) or u'').lower() for w in words)
            cb.Visibility = Visibility.Visible if ok else Visibility.Collapsed

    def on_types_all(self, sender, args):
        for cb in self.type_boxes:
            if cb.Visibility == Visibility.Visible:
                cb.IsChecked = True

    def on_types_none(self, sender, args):
        for cb in self.type_boxes:
            cb.IsChecked = False

    # ---- load ----------------------------------------------------------
    def on_load(self, sender, args):
        self._do_load(place=False)

    def on_place(self, sender, args):
        self._do_load(place=True)

    def _do_load(self, place):
        it = self.current
        if it is None:
            return
        if self.doc.IsFamilyDocument:
            U.error(strings.FAMILY_DOC)
            return
        types = [cb.Tag for cb in self.type_boxes if cb.IsChecked]
        if self.type_boxes and not types:
            U.error(strings.TYPES_NONE)
            return
        overwrite = bool(self.overwrite_box.IsChecked)
        if overwrite and not U.ask(strings.OVERWRITE_WARN):
            return
        card = it.card
        self.Cursor = Cursors.Wait
        try:
            self.status_text.Text = strings.DOWNLOADING.format(card['id'])
            path = self.cache.get(card, '.rfa')
            if types:
                # LoadFamilySymbol needs the catalog next to the file
                self.cache.get(card, '.txt')
            fam = loader.load_family(self.doc, path, card['id'], overwrite, types or None)
        except Exception as ex:
            self.Cursor = None
            self.status_text.Text = u'{0}'.format(ex)
            U.error(u'{0}'.format(ex))
            return
        self.Cursor = None
        was = it.code
        in_project = loader.project_families(self.doc)
        for x in self.items:
            if x.card['id'].lower() == card['id'].lower():
                self._set_status(x, in_project)
                x.chip_host.Child = U.chip(x.label, x.code)
        msg = (strings.UPDATED.format(card['id'], card.get('version')) if was != loader.MISSING
               else strings.LOADED.format(card['id']))
        userprefs.add_recent(card['id'])
        self.prefs = userprefs.load()
        self.status_text.Text = msg
        self._show_details(it)
        if place:
            sym = loader.first_symbol(self.doc, fam, prefer=types)
            if sym is not None:
                self.place_symbol = sym
                self.Close()

    def on_update_all(self, sender, args):
        """Update every family that is older in the project than in the library.
        Parameter values in the project are kept. Catalog families: the types
        already in the project are reloaded."""
        todo = [x for x in self.items if x.code == loader.OUTDATED]
        if not todo or self.doc.IsFamilyDocument:
            return
        if not U.ask(strings.UPDATE_ALL_ASK.format(len(todo))):
            return
        done, failed = [], []
        self.Cursor = Cursors.Wait
        try:
            for x in todo:
                card = x.card
                self.status_text.Text = strings.DOWNLOADING.format(card['id'])
                try:
                    path = self.cache.get(card, '.rfa')
                    types = None
                    if card.get('type_catalog'):
                        self.cache.get(card, '.txt')
                        types = loader.family_type_names(
                            self.doc, loader.find_family(self.doc, card['id'])) or None
                    loader.load_family(self.doc, path, card['id'], False, types)
                    done.append(card['id'])
                except Exception as ex:
                    log.write(u'update all {0}'.format(card['id']), exc=True)
                    failed.append(u'{0}: {1}'.format(card['id'], ex))
        finally:
            self.Cursor = None
        in_project = loader.project_families(self.doc)
        for x in self.items:
            self._set_status(x, in_project)
            x.chip_host.Child = U.chip(x.label, x.code)
        self._fill_groups()
        self._apply_filter()
        text = strings.UPDATE_ALL_DONE.format(len(done))
        if failed:
            text += u'\n\n' + u'\n'.join(failed[:10])
        U.info(text)

    # ---- requests & issues ---------------------------------------------
    def on_request(self, sender, args):
        from peer_library.ui_dialogs import TextWindow

        def send(name, reason):
            self.backend.send_proposal({'kind': 'request', 'name': name, 'reason': reason})
        win = TextWindow(strings.TITLE_REQUEST, strings.REQUEST_HEAD, strings.REQUEST_HINT,
                         strings.REQUEST_L1, strings.REQUEST_L2, strings.BTN_SEND, send, owner=self)
        win.ShowDialog()
        if win.done:
            U.info(strings.REQUEST_SENT)

    def on_issue(self, sender, args):
        it = self.current
        if it is None:
            return
        from peer_library.ui_dialogs import TextWindow
        card = it.card

        def send(name, text):
            self.backend.send_proposal({'kind': 'issue', 'name': name, 'reason': text,
                                        'family_id': card['id'], 'group': card.get('group'),
                                        'library_version': card.get('version')})
        win = TextWindow(strings.TITLE_ISSUE, strings.ISSUE_HEAD.format(card['id']),
                         strings.ISSUE_HINT, strings.ISSUE_L1, strings.ISSUE_L2, strings.BTN_SEND,
                         send, text1=card.get('name') or card['id'], owner=self)
        win.ShowDialog()
        if win.done:
            U.info(strings.REQUEST_SENT)

    # ---- admin ------------------------------------------------------------
    def _refresh_item(self, it, card):
        it.card = card
        it.text = Item(card).text
        it.name_block.Text = self._tile_name(it)
        it.lbi.Content.ToolTip = u'{0}\n{1}'.format(card['id'], groups.title(card.get('group')))

    def on_edit_info(self, sender, args):
        it = self.current
        if it is None or not self.is_admin:
            return
        from peer_library.ui_dialogs import EditInfoWindow
        win = EditInfoWindow(it.card, owner=self)
        win.ShowDialog()
        if not win.fields:
            return
        try:
            card = self.backend.update_card(it.card['id'], win.fields)
        except Exception as ex:
            log.write(u'edit info', exc=True)
            U.error(u'{0}'.format(ex))
            return
        self._refresh_item(it, card)
        self._show_details(it)
        self._fill_groups()
        self._apply_filter()
        self.status_text.Text = strings.INFO_SAVED.format(card['id'])

    def _save_collections(self, colls):
        try:
            data = self.backend.put_collections(colls)
        except Exception as ex:
            log.write(u'collections', exc=True)
            U.error(u'{0}'.format(ex))
            return False
        self.collections = data.get('collections') or []
        sel = self.group_key
        self._fill_groups()
        if sel in self.group_keys:
            self.group_list.SelectedIndex = self.group_keys.index(sel)
        self._apply_filter()
        return True

    def on_coll_add(self, sender, args):
        it = self.current
        if it is None or not self.is_admin:
            return
        names = [c['name'] for c in self.collections] + [strings.NEW_COLLECTION]
        pick = forms.SelectFromList.show(names, title=strings.BTN_COLL_ADD, button_name=u'Add',
                                         multiselect=False)
        if not pick:
            return
        colls = [dict(c) for c in self.collections]
        if pick == strings.NEW_COLLECTION:
            name = forms.ask_for_string(prompt=strings.NEW_COLLECTION_PROMPT, title=strings.APP)
            if not name or not name.strip():
                return
            colls.append({'name': name.strip(), 'families': [it.card['id']]})
        else:
            for c in colls:
                if c['name'] == pick and it.card['id'] not in (c.get('families') or []):
                    c['families'] = list(c.get('families') or []) + [it.card['id']]
        if self._save_collections(colls):
            self.status_text.Text = strings.COLL_ADDED.format(it.card['id'], pick)

    def on_coll_remove(self, sender, args):
        it = self.current
        if it is None or not self.is_admin or not self.group_key.startswith('coll:'):
            return
        cid = self.group_key[5:]
        colls = [dict(c) for c in self.collections]
        for c in colls:
            if c['id'] == cid:
                c['families'] = [x for x in c.get('families') or [] if x != it.card['id']]
        self._save_collections(colls)

    def on_deprecate(self, sender, args):
        it = self.current
        if it is None or not self.is_admin:
            return
        note = forms.ask_for_string(prompt=strings.DEPRECATE_ASK.format(it.card['id']),
                                    title=strings.APP)
        if note is None:
            return
        try:
            self.backend.deprecate(it.card['id'], note.strip())
        except Exception as ex:
            log.write(u'deprecate', exc=True)
            U.error(u'{0}'.format(ex))
            return
        self.items = [x for x in self.items if x is not it]
        self.tile_list.Items.Remove(it.lbi)
        self._show_details(None)
        self._fill_groups()
        self._apply_filter()

    def on_coll_load(self, sender, args):
        if self.doc.IsFamilyDocument:
            return
        shown = [x for x in self.items if x.lbi.Visibility == Visibility.Visible]
        todo = [x for x in shown if x.code in (loader.MISSING, loader.OUTDATED, loader.UNKNOWN)
                and not x.card.get('type_catalog')]
        skipped = [x.card['id'] for x in shown if x.card.get('type_catalog')
                   and x.code == loader.MISSING]
        if not todo:
            U.info(strings.COLL_NOTHING + (u'\n\n' + strings.COLL_CATALOGS.format(
                u', '.join(skipped)) if skipped else u''))
            return
        if not U.ask(strings.COLL_LOAD_ASK.format(len(todo))):
            return
        done, failed = self._load_many(todo)
        text = strings.COLL_DONE.format(len(done))
        if skipped:
            text += u'\n\n' + strings.COLL_CATALOGS.format(u', '.join(skipped))
        if failed:
            text += u'\n\n' + u'\n'.join(failed[:10])
        U.info(text)

    def _load_many(self, todo, keep_types=False):
        """Load / update several families; returns (done ids, failure texts)."""
        done, failed = [], []
        self.Cursor = Cursors.Wait
        try:
            for x in todo:
                card = x.card
                self.status_text.Text = strings.DOWNLOADING.format(card['id'])
                try:
                    path = self.cache.get(card, '.rfa')
                    types = None
                    if keep_types and card.get('type_catalog'):
                        self.cache.get(card, '.txt')
                        types = loader.family_type_names(
                            self.doc, loader.find_family(self.doc, card['id'])) or None
                    loader.load_family(self.doc, path, card['id'], False, types)
                    userprefs.add_recent(card['id'])
                    done.append(card['id'])
                except Exception as ex:
                    log.write(u'load many {0}'.format(card['id']), exc=True)
                    failed.append(u'{0}: {1}'.format(card['id'], ex))
        finally:
            self.Cursor = None
        self.prefs = userprefs.load()
        self._refresh_statuses()
        return done, failed

    def _refresh_statuses(self):
        in_project = loader.project_families(self.doc)
        for x in self.items:
            self._set_status(x, in_project)
            x.chip_host.Child = U.chip(x.label, x.code)
        sel = self.group_key
        self._fill_groups()
        if sel in self.group_keys:
            self.group_list.SelectedIndex = self.group_keys.index(sel)
        self._apply_filter()

    # ---- this project ------------------------------------------------------
    def _fill_project(self):
        import clr
        clr.AddReference('System.Data')
        from System.Data import DataTable
        by_id = dict((x.card['id'].lower(), x) for x in self.items)
        rows = []
        for fam, cat, pv in loader.project_family_list(self.doc):
            it = by_id.get(fam.lower())
            if it is None:
                status, code = strings.PS_NOT_IN_LIBRARY, 'notlib'
            elif pv is None:
                status, code = strings.PS_NO_VERSION, 'unknown'
            elif pv < it.card.get('version', 0):
                status, code = strings.PS_OUTDATED.format(it.card.get('version')), 'outdated'
            elif pv > it.card.get('version', 0):
                status, code = strings.PS_NEWER, 'newer'
            else:
                status, code = strings.PS_CURRENT, 'current'
            rows.append({'family': fam, 'category': cat, 'status': status, 'code': code,
                         'pv': u'' if pv is None else u'v{0}'.format(pv),
                         'lv': u'v{0}'.format(it.card.get('version')) if it else u'',
                         'item': it})
        self.proj_all = rows
        n_lib = sum(1 for r in rows if r['item'] is not None)
        n_out = sum(1 for r in rows if r['code'] == 'outdated')
        self.proj_summary.Text = strings.PROJ_SUMMARY.format(len(rows), n_lib, n_out)
        if self.proj_filter.Items.Count == 0:
            self._busy = True
            for f in strings.PROJ_FILTERS:
                self.proj_filter.Items.Add(f)
            self.proj_filter.SelectedIndex = 1 if n_out else 0
            self._busy = False
        f = self.proj_filter.SelectedIndex
        keep = {0: None, 1: ('outdated', 'unknown'), 2: ('notlib',),
                3: ('current', 'outdated', 'unknown', 'newer')}.get(f)
        self.proj_rows = [r for r in rows if keep is None or r['code'] in keep]
        table = DataTable()
        for col in ('family', 'category', 'status', 'pv', 'lv'):
            table.Columns.Add(col)
        for r in self.proj_rows:
            table.Rows.Add(r['family'], r['category'], r['status'], r['pv'], r['lv'])
        self.proj_list.ItemsSource = table.DefaultView

    def _proj_selected(self):
        out = []
        for i in range(self.proj_list.Items.Count):
            item = self.proj_list.Items[i]
            if self.proj_list.SelectedItems.Contains(item) and i < len(self.proj_rows):
                out.append(self.proj_rows[i])
        return out

    def on_proj_filter(self, sender, args):
        if not self._busy:
            self._fill_project()

    def on_proj_refresh(self, sender, args):
        self._fill_project()

    def on_proj_update(self, sender, args):
        sel = [r for r in self._proj_selected() if r['item'] is not None]
        if not sel:
            U.info(strings.PROJ_SELECT_LIBRARY)
            return
        if not U.ask(strings.UPDATE_ALL_ASK.format(len(sel))):
            return
        done, failed = self._load_many([r['item'] for r in sel], keep_types=True)
        self._fill_project()
        text = strings.UPDATE_ALL_DONE.format(len(done))
        if failed:
            text += u'\n\n' + u'\n'.join(failed[:10])
        U.info(text)

    def on_proj_propose(self, sender, args):
        sel = [r for r in self._proj_selected() if r['item'] is None]
        if len(sel) != 1:
            U.info(strings.PROJ_SELECT_ONE_NOTLIB)
            return
        fam = loader.find_family(self.doc, sel[0]['family'])
        if fam is None or not fam.IsEditable:
            U.error(strings.PROJ_NOT_EDITABLE)
            return
        import os
        from peer_library.ui_propose import ProposeWindow, export_family
        try:
            path = export_family(self.doc, fam)
        except Exception as ex:
            log.write(u'export family', exc=True)
            U.error(u'{0}'.format(ex))
            return
        xaml = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), 'PEER.tab', 'Library.panel', 'Propose.smartbutton',
            'ProposeWindow.xaml')
        ProposeWindow(xaml, self.doc, self.uidoc, self.backend, preset_file=path).ShowDialog()

    # ---- other tabs ----------------------------------------------------
    def _line(self, text, sub=None, code=None):
        sp = StackPanel()
        sp.Margin = Thickness(6, 4, 6, 4)
        head = StackPanel()
        head.Orientation = Orientation.Horizontal
        if code:
            ch = U.chip(code[0], code[1])
            ch.Margin = Thickness(0, 0, 8, 0)
            head.Children.Add(ch)
        t = TextBlock()
        t.Text = text
        t.FontWeight = FontWeights.SemiBold
        head.Children.Add(t)
        sp.Children.Add(head)
        if sub:
            s = TextBlock()
            s.Text = sub
            s.Foreground = U.brush(U.MUTED)
            s.TextWrapping = TextWrapping.Wrap
            sp.Children.Add(s)
        return sp

    def _fill_news(self):
        self.news_list.Items.Clear()
        entries = list(reversed((self.cache.changelog() or {}).get('entries') or []))[:200]
        words = {'added': (strings.NEWS_ADDED, loader.CURRENT),
                 'updated': (strings.NEWS_UPDATED, loader.OUTDATED),
                 'deprecated': (strings.NEWS_DEPRECATED, loader.NEWER)}
        for e in entries:
            code = words.get(e.get('action'), (e.get('action') or u'', loader.MISSING))
            sub = u'{0} · v{1} · {2}{3}'.format(
                e.get('date') or e.get('time', u'')[:10], e.get('version'),
                groups.title(e.get('group')),
                (u' · ' + e['note']) if e.get('note') else u'')
            self.news_list.Items.Add(self._line(u'{0} ({1})'.format(e.get('name') or e.get('id'),
                                                                    e.get('id')), sub, code))

    def _fill_mine(self):
        self.mine_list.Items.Clear()
        try:
            mine = self.backend.my_proposals()
        except Exception as ex:
            self.mine_list.Items.Add(self._line(u'{0}'.format(ex)))
            return
        labels = {'pending': (strings.P_PENDING, loader.UNKNOWN),
                  'accepted': (strings.P_ACCEPTED, loader.CURRENT),
                  'rejected': (strings.P_REJECTED, loader.NEWER)}
        for p in sorted(mine, key=lambda x: x.get('sent', u''), reverse=True):
            sub = u'{0}{1}'.format((p.get('sent') or u'')[:16].replace(u'T', u' '),
                                   (u' · ' + p['comment']) if p.get('comment') else u'')
            self.mine_list.Items.Add(self._line(p.get('name') or p['id'], sub,
                                                labels.get(p.get('status'), labels['pending'])))
