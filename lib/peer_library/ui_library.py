# -*- coding: utf-8 -*-
"""Library window: groups, search, tiles with previews and statuses, details,
load / update / place, type catalogs, What's new, My proposals."""

from pyrevit import forms

from System import TimeSpan  # noqa: E402
from System.Diagnostics import Process  # noqa: E402
from System.Windows import FontWeights, HorizontalAlignment, TextTrimming, TextWrapping, Thickness, \
    VerticalAlignment, Visibility  # noqa: E402
from System.Windows import Clipboard  # noqa: E402
from System.Windows.Controls import Border, CheckBox, ContextMenu, Grid, Image, ListBoxItem, \
    MenuItem, Orientation, Separator, StackPanel, TextBlock  # noqa: E402
from System.Windows.Documents import Hyperlink, Run  # noqa: E402
from System.Windows.Input import Cursors, Key, Keyboard, ModifierKeys  # noqa: E402
from System.Windows.Media import Stretch  # noqa: E402
from System.Windows.Threading import DispatcherTimer  # noqa: E402

import threading  # noqa: E402

from peer_library import catalog, groups, index, load_check, loader, log, search, strings, \
    userprefs  # noqa: E402
from peer_library import ui_common as U  # noqa: E402
from peer_library.cache import Cache  # noqa: E402

PREVIEWS_PER_TICK = 12
SEARCH_DELAY_MS = 180
SPECIAL_GROUPS = ('all', 'favorites', 'recent', 'new', 'project', 'outdated', 'popular',
                  'attention')

# preview states (set by the background downloader, applied by the UI timer)
P_WAIT, P_READY, P_NONE = None, 'ready', 'none'


class Item(object):
    def __init__(self, card):
        self.card = card
        self.code = loader.MISSING
        self.pv = None
        self.label = u''
        self.lbi = None
        self.image = None
        self.chip_host = None
        self.preview_done = False          # image set on the tile (UI thread)
        self.png = P_WAIT                  # preview file state (downloader thread)
        self.shown = True                  # plain flag: readable from the downloader thread
        self.is_new = index.is_new(card)
        self.entry = search.Entry(card)
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
        self._closing = False
        self._png_lock = threading.Lock()   # one download of a preview at a time
        self._downloader = None
        self._texts()
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromMilliseconds(40)
        self.timer.Tick += self._preview_tick
        self.search_timer = DispatcherTimer()
        self.search_timer.Interval = TimeSpan.FromMilliseconds(SEARCH_DELAY_MS)
        self.search_timer.Tick += self._search_tick
        self.Loaded += self._on_loaded
        self.Closing += self._on_closing
        self._build_menu()

    # ---- right click on a tile ---------------------------------------------
    def _build_menu(self):
        m = ContextMenu()
        self.menu = {}

        def add(key, action):
            mi = MenuItem()
            mi.Click += lambda s, a: self._menu_do(action)
            m.Items.Add(mi)
            self.menu[key] = mi
        add('load', lambda: self._do_load(place=False))
        add('place', lambda: self._do_load(place=True))
        add('check', self.on_check)
        m.Items.Add(Separator())
        add('fav', lambda: self.on_fav(None, None))
        add('copy', self._copy_id)
        add('issue', lambda: self.on_issue(None, None))
        if self.is_admin:
            m.Items.Add(Separator())
            add('edit', lambda: self.on_edit_info(None, None))
            add('newver', lambda: self.on_new_version(None, None))
        self.menu['copy'].Header = strings.MENU_COPY_ID
        self.menu['check'].Header = strings.MENU_CHECK
        self.menu['check'].ToolTip = strings.MENU_CHECK_TIP
        self.menu['issue'].Header = strings.BTN_ISSUE
        if self.is_admin:
            self.menu['edit'].Header = strings.BTN_EDIT_INFO
            self.menu['newver'].Header = strings.BTN_NEW_VERSION
        self.tile_list.ContextMenu = m
        self.tile_list.ContextMenuOpening += self._on_menu_opening

    def _on_menu_opening(self, sender, args):
        it = self.current
        if it is None:
            args.Handled = True                      # empty space: no menu
            return
        self.menu['load'].Header = self.load_btn.Content
        self.menu['place'].Header = self.place_btn.Content
        self.menu['fav'].Header = self.fav_btn.Content
        self.menu['check'].Visibility = (Visibility.Visible if it.code != loader.MISSING
                                         else Visibility.Collapsed)

    def _menu_do(self, action):
        if self.current is None:
            return
        try:
            action()
        except Exception as ex:
            log.write(u'tile menu', exc=True)
            U.error(u'{0}'.format(ex))

    def _on_closing(self, sender, args):
        self._closing = True
        self.timer.Stop()
        self.search_timer.Stop()

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
        self.d_empty.Text = strings.DETAILS_HINT
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
        self.newver_btn.Content = strings.BTN_NEW_VERSION
        others = self._other_projects()
        if others:
            self.all_docs_box.Content = strings.ALL_DOCS.format(len(others))
            self.all_docs_box.Visibility = Visibility.Visible
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

    def _old_revit(self):
        """This Revit is older than the library format: Revit cannot open the files."""
        try:
            from peer_library import checks_file
            year = int(self.doc.Application.VersionNumber)
            return 0 < year < checks_file.LIBRARY_REVIT
        except Exception:
            return False

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
        if self._old_revit():
            from peer_library import checks_file
            self.status_text.Text = strings.OLD_REVIT.format(checks_file.LIBRARY_REVIT,
                                                             self.doc.Application.VersionNumber)
        self._start_downloader()
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

    # ---- previews: files checked / downloaded in a background thread, shown by
    # the UI timer (WPF objects are touched only on the UI thread) ------------
    def _start_downloader(self):
        items = list(self.items)             # own copy: the UI thread re-sorts self.items
        online = self.online

        def next_item():
            pending = [x for x in items if x.png is P_WAIT]
            for x in pending:
                if x.shown:                  # what the user sees first
                    return x
            return pending[0] if pending else None

        def run():
            try:
                for x in items:              # quick pass: no preview / already on disk
                    if self._closing:
                        return
                    if x.png is not P_WAIT:
                        continue
                    if not x.card.get('png_sha1'):
                        x.png = P_NONE
                    elif self.cache.has(x.card, '.png'):
                        x.png = P_READY
                while not self._closing:
                    x = next_item()
                    if x is None:
                        return
                    if not online:
                        x.png = P_NONE
                        continue
                    try:
                        with self._png_lock:
                            ok = self.cache.get(x.card, '.png')
                        x.png = P_READY if ok else P_NONE
                    except Exception as ex:
                        x.png = P_NONE
                        log.write(u'preview {0}: {1}'.format(x.card.get('id'), ex))
            except Exception:
                log.write(u'preview downloader', exc=True)

        self._downloader = threading.Thread(target=run, name='peer_library_previews')
        self._downloader.daemon = True
        self._downloader.start()

    def _preview_tick(self, sender, args):
        ready = [it for it in self.items if not it.preview_done and it.png is not P_WAIT]
        ready.sort(key=lambda it: 0 if it.shown else 1)
        for it in ready[:PREVIEWS_PER_TICK]:
            it.preview_done = True
            if it.png == P_READY:
                it.image.Source = U.bitmap(self.cache.local_path(it.card, '.png'), 150)
        if not any(not it.preview_done for it in self.items):
            self.timer.Stop()
        elif not ready and (self._downloader is None or not self._downloader.is_alive()):
            for it in self.items:            # downloader gone: the rest has no preview
                if it.png is P_WAIT:
                    it.png = P_NONE

    def _preview_path(self, card):
        """Preview of the selected family; downloaded only when online (offline
        the UI thread must not wait for network timeouts)."""
        if not card.get('png_sha1'):
            return None
        try:
            if not self.online:
                return self.cache.local_path(card, '.png') if self.cache.has(card, '.png') else None
            with self._png_lock:
                return self.cache.get(card, '.png')
        except Exception:
            return None

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
        if self.is_admin:
            rows.append(('attention', strings.GROUP_ATTENTION,
                         sum(1 for i in self.items if index.attention(i.card))))
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
            t.TextTrimming = TextTrimming.CharacterEllipsis      # long collection names
            t.ToolTip = t.Text
            t.Padding = Thickness(6, 4, 6, 4)
            if key == 'outdated' and n:
                t.FontWeight = FontWeights.SemiBold
            if i == n_special - 1 or (i == n_groups - 1 and self.collections):
                t.Margin = Thickness(0, 0, 0, 8)
            self.group_list.Items.Add(t)
            self.group_keys.append(key)
        self.group_list.SelectedIndex = self.group_keys.index(self.group_key) \
            if self.group_key in self.group_keys else 0

    def _group_ok(self, it):
        """Group / category / catalog filters (the search text is scored apart)."""
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
        if k == 'attention' and not index.attention(it.card):
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
        return True

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
        self._show_order(self.items)

    def _show_order(self, order):
        """Shown tiles in this order; keeps the selection. Only the order of the
        shown tiles matters (hidden ones are collapsed), so only the shown tiles
        from the first misplaced one on are moved - re-adding all tiles costs
        ~1 s per keystroke with 500+ families."""
        items = self.tile_list.Items
        sel = self.current
        self._busy = True
        try:
            if items.Count != len(order):
                items.Clear()
                for it in order:
                    items.Add(it.lbi)
            else:
                want = [x for x in order if x.shown]
                have = [lbi.Tag for lbi in items if lbi.Tag.shown]
                j = 0
                while j < len(want) and j < len(have) and want[j] is have[j]:
                    j += 1
                for it in want[j:]:
                    items.Remove(it.lbi)
                    items.Add(it.lbi)
            if sel is not None and sel.lbi is not None and sel.shown \
                    and self.tile_list.SelectedItem is not sel.lbi:
                self.tile_list.SelectedItem = sel.lbi
        finally:
            self._busy = False

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
        query = self.search_box.Text or u''
        words = search.query_words(query)
        shown = 0
        scored = []
        for n, it in enumerate(self.items):
            s = it.entry.order_key(words, query) if self._group_ok(it) else None
            ok = s is not None
            it.shown = ok
            it.lbi.Visibility = Visibility.Visible if ok else Visibility.Collapsed
            if ok:
                shown += 1
                scored.append((s, n, it))
        if words:                        # best matches first, the rest keeps the sort order
            scored.sort(key=lambda x: (x[0], x[1]))
            first = [x[2] for x in scored]
            self._show_order(first + [it for it in self.items if not it.shown])
        else:
            self._show_order(self.items)
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
        self.search_hint.Visibility = Visibility.Collapsed if self.search_box.Text \
            else Visibility.Visible
        self.search_timer.Stop()             # filter once typing pauses
        self.search_timer.Start()

    def _search_tick(self, sender, args):
        self.search_timer.Stop()
        if not self._closing:
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
        elif args.Key in (Key.Down, Key.Enter) and self.search_box.IsKeyboardFocusWithin:
            if self.search_timer.IsEnabled:                # typed just now: filter first
                self._search_tick(None, None)
            for lbi in self.tile_list.Items:               # first shown tile (best match)
                if lbi.Visibility == Visibility.Visible:
                    self.tile_list.SelectedItem = lbi
                    lbi.Focus()
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
        if self._busy:                       # tiles being re-ordered
            return
        lbi = self.tile_list.SelectedItem
        self._show_details(lbi.Tag if lbi is not None else None)

    def on_double(self, sender, args):
        if self.current is not None:
            self._do_load(place=True)

    def _show_details(self, it):
        self.current = it
        has = it is not None
        self.details.Visibility = Visibility.Visible if has else Visibility.Hidden
        self.d_empty.Visibility = Visibility.Collapsed if has else Visibility.Visible
        self.load_btn.IsEnabled = has and not self._old_revit()
        self.place_btn.IsEnabled = has and not self._old_revit()
        self.overwrite_box.IsEnabled = has
        if not has:
            self.status_text.Text = self.status_text.Text or strings.NOTHING_SELECTED
            return
        c = it.card
        png = self._preview_path(c)
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
        self.d_version.Text = strings.VERSION_LINE.format(c.get('version'), c.get('updated')) + (
            u' · ' + U.file_size(c['size']) if c.get('size') else u'')
        self.d_project.Text = strings.PROJECT_LINE.format(it.label)
        self.d_desc.Text = c.get('description') or u''
        self.d_tags.Text = u', '.join(c.get('tags') or [])
        self._help_link(c.get('help_url'))
        self._fill_types(c)
        self._fill_companions(c)
        self.d_history.Children.Clear()
        for h in reversed(c.get('history') or []):
            t = TextBlock()
            t.TextWrapping = TextWrapping.Wrap
            t.Margin = Thickness(0, 0, 0, 3)
            t.Inlines.Add(Run(u'v{0} · {1} · {2}{3}'.format(
                h.get('v'), h.get('date'), h.get('note') or u'-',
                u' ({0})'.format(h['by']) if h.get('by') else u'')))
            if self.is_admin and h.get('v') != c.get('version') and (h.get('files') or {}).get('.rfa'):
                t.Inlines.Add(Run(u'  '))
                link = Hyperlink(Run(strings.RESTORE))
                link.Foreground = U.brush(U.INK)
                link.ToolTip = strings.RESTORE_TIP.format(h.get('v'))
                link.Click += self._restore_handler(it, h)
                t.Inlines.Add(link)
            self.d_history.Children.Add(t)
        update = it.code in (loader.OUTDATED, loader.UNKNOWN, loader.NEWER, loader.CURRENT)
        self.load_btn.Content = strings.BTN_UPDATE if update else strings.BTN_LOAD
        self.place_btn.Content = strings.BTN_UPDATE_PLACE if update else strings.BTN_LOAD_PLACE
        fav = c['id'] in self.prefs['favorites']
        self.fav_btn.Content = strings.FAV_ON if fav else strings.FAV_OFF
        self.d_stats.Text = strings.STATS_LINE.format(
            strings.times(it.downloads), strings.people(it.users)) if it.downloads else u''
        if self.is_admin:
            need = index.attention(c)
            self.admin_header.Text = strings.ADMIN_HEADER + (
                u' · ' + strings.NEEDS.format(u', '.join(need)) if need else u'')

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
            cb.Content = U.label(u'{0}    {1}'.format(name, extra) if extra else name)
            cb.Tag = name
            cb.Margin = Thickness(2)
            self.type_boxes.append(cb)
            self.types_list.Items.Add(cb)

    def _copy_id(self):
        if self.current is None:
            return
        if U.copy_text(self.current.card['id']):
            self.status_text.Text = strings.COPIED.format(self.current.card['id'])
        else:
            self.status_text.Text = strings.COPY_BUSY

    def _fill_companions(self, card):
        """'Also load' boxes: what the card says goes with this family (a tag
        for a pile). Ticked = loaded with it; what the project already has is
        only named - it is never replaced from here."""
        self.comp_boxes = []
        self.comp_list.Children.Clear()
        cards = dict((x.card['id'].lower(), x.card) for x in self.items)
        try:
            in_project = loader.project_families(self.doc) if not self.doc.IsFamilyDocument else {}
        except Exception:
            in_project = {}
        rows = index.companions(card, cards, in_project)
        if not self.is_admin:
            rows = [r for r in rows if r[1] != 'unknown']
        self.comp_panel.Visibility = Visibility.Visible if rows else Visibility.Collapsed
        self.comp_header.Text = strings.COMP_HEADER
        notes = {'present': strings.COMP_PRESENT, 'catalog': strings.COMP_CATALOG,
                 'retired': strings.COMP_RETIRED, 'unknown': strings.COMP_MISSING}
        for cid, state, c in rows:
            cb = CheckBox()
            name = (c or {}).get('name') or cid
            label = cid if name == cid else u'{0}  ({1})'.format(name, cid)
            cb.Content = U.label(label if state == 'load' else u'{0} - {1}'.format(label, notes[state]))
            cb.IsChecked = state == 'load'
            cb.IsEnabled = state == 'load'
            cb.Tag = c
            cb.Margin = Thickness(2)
            if state == 'load':
                self.comp_boxes.append(cb)
            self.comp_list.Children.Add(cb)

    def _load_companions(self):
        """Loads the ticked companions (never over a family in the project).
        Returns (loaded ids, [error texts])."""
        done, failed = [], []
        for cb in getattr(self, 'comp_boxes', []):
            c = cb.Tag
            if not cb.IsChecked or c is None:
                continue
            try:
                if loader.find_family(self.doc, c['id']) is not None:
                    continue
                loader.load_family(self.doc, self.cache.get(c, '.rfa'), c['id'], False, None)
                done.append(c['id'])
            except Exception as ex:
                log.write(u'companion {0}'.format(c['id']), exc=True)
                failed.append(u'{0}: {1}'.format(c['id'], ex))
        return done, failed

    def on_types_search(self, sender, args):
        words = (self.types_search.Text or u'').lower().split()
        for cb in self.type_boxes:
            ok = all(w in U.label_text(cb).lower() for w in words)
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

    def _refuse_old_revit(self):
        if not self._old_revit():
            return False
        from peer_library import checks_file
        U.error(strings.OLD_REVIT.format(checks_file.LIBRARY_REVIT, self.doc.Application.VersionNumber))
        return True

    def _do_load(self, place, always_show=False):
        it = self.current
        if it is None or self._refuse_old_revit():
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
        aside = None
        try:
            self.status_text.Text = strings.DOWNLOADING.format(card['id'])
            path = self.cache.get(card, '.rfa')
            if types:
                # LoadFamilySymbol needs the catalog next to the file
                self.cache.get(card, '.txt')
            choice = self._check_before(it, path, types, overwrite, always_show)
            if choice is None:
                self.Cursor = None
                self.status_text.Text = strings.CHECK_CANCELLED
                return
            if choice == 'aside':
                aside = load_check.rename_aside(self.doc, card['id'])
            fam = loader.load_family(self.doc, path, card['id'], overwrite, types or None,
                                     delete_broken=(choice == 'anyway'))
        except Exception as ex:
            self.Cursor = None
            self.status_text.Text = u'{0}'.format(ex)
            U.error(u'{0}'.format(ex))
            return
        other_failed = []
        if self.all_docs_box.IsChecked:
            for d in self._other_projects():
                try:
                    problem = self._quiet_check(d, it, path, types, overwrite)
                    if problem:
                        other_failed.append(u'{0}: {1}'.format(d.Title, problem))
                        continue
                    loader.load_family(d, path, card['id'], overwrite, types or None)
                except Exception as ex:
                    other_failed.append(u'{0}: {1}'.format(d.Title, ex))
        self.Cursor = None
        if other_failed:
            U.error(strings.OTHER_DOCS_FAILED + u'\n\n' + u'\n'.join(other_failed))
        also, also_failed = self._load_companions()
        if also_failed:
            U.error(strings.COMP_FAILED + u'\n\n' + u'\n'.join(also_failed))
        was = loader.MISSING if aside else it.code
        in_project = loader.project_families(self.doc)
        for x in self.items:
            if x.card['id'].lower() == card['id'].lower():
                self._set_status(x, in_project)
                x.chip_host.Child = U.chip(x.label, x.code)
        msg = (strings.UPDATED.format(card['id'], card.get('version')) if was != loader.MISSING
               else strings.LOADED.format(card['id']))
        if aside:
            msg = strings.CHECK_ASIDE_DONE.format(aside, card['id'])
        if also:
            msg += u' ' + strings.COMP_LOADED.format(u', '.join(also))
        userprefs.add_recent(card['id'])
        self.prefs = userprefs.load()
        self.status_text.Text = msg
        self._show_details(it)
        if place:
            try:
                sym = loader.first_symbol(self.doc, fam, prefer=types)
            except Exception:
                log.write(u'first symbol {0}'.format(card['id']), exc=True)
                sym = None
            if sym is not None:
                self.place_symbol = sym
                self.Close()
            else:
                self.status_text.Text = strings.NO_PLACE.format(card['id'])

    def on_update_all(self, sender, args):
        """Update every family that is older in the project than in the library.
        Parameter values in the project are kept. Catalog families: the types
        already in the project are reloaded."""
        todo = [x for x in self.items if x.code == loader.OUTDATED]
        if not todo or self.doc.IsFamilyDocument or self._refuse_old_revit():
            return
        if not U.ask(strings.UPDATE_ALL_ASK.format(len(todo))):
            return
        done, failed, skipped = self._load_many(todo, keep_types=True)
        U.info(_batch_text(strings.UPDATE_ALL_DONE.format(len(done)), failed, skipped))

    # ---- check before a family that is in the project is replaced ---------
    def _check_before(self, it, path, types, overwrite, always_show=False):
        """'load' (not in the project / nothing breaks / the person said Update),
        'anyway' (Update anyway: Revit may delete what breaks), 'aside' (keep the
        project family under another name) or None (cancelled)."""
        card = it.card
        if loader.find_family(self.doc, card['id']) is None:
            return 'load'
        self.status_text.Text = strings.CHECKING.format(card['id'])
        U.refresh(self)
        try:
            rep = load_check.check(self.doc, path, card['id'], types or None, overwrite,
                                   not_library=(it.code == loader.UNKNOWN),
                                   previews_to=load_check.preview_folder())
        except Exception as ex:
            log.write(u'load check {0}'.format(card['id']), exc=True)
            self.Cursor = None
            ok = U.ask(strings.CHECK_FAILED_ASK.format(ex))
            self.Cursor = Cursors.Wait
            return 'load' if ok else None
        if rep is None or (not rep.needs_look and not always_show):
            self.status_text.Text = strings.CHECK_OK_STATUS
            return 'load'
        from peer_library.ui_check import LoadCheckWindow
        self.Cursor = None
        w = LoadCheckWindow(rep, self._preview_path(card), owner=self)
        w.ShowDialog()
        self.Cursor = Cursors.Wait
        if w.choice == 'update':
            return 'anyway' if rep.blocking else 'load'
        return w.choice

    def _quiet_check(self, doc, card, path, types, overwrite=False):
        """For loads without a window (collections, Update all, other projects):
        None = go ahead, else the reason to leave this family alone."""
        in_project = loader.project_families(doc)
        if card['id'].lower() not in in_project:
            return None
        if loader.status(card, in_project)[0] == loader.UNKNOWN:
            return strings.CHECK_NOT_FROM_LIBRARY
        rep = load_check.check(doc, path, card['id'], types or None, overwrite)
        if rep is not None and rep.blocking:
            return rep.first_problem()
        return None

    def on_check(self):
        """Right click -> Check against this project: the window always opens."""
        self._do_load(place=False, always_show=True)

    def _other_projects(self):
        """Other open, editable project documents (not families, not links)."""
        out = []
        try:
            for d in self.doc.Application.Documents:
                if d.IsFamilyDocument or d.IsLinked or d.Equals(self.doc):
                    continue
                if getattr(d, 'IsReadOnly', False):
                    continue
                out.append(d)
        except Exception:
            log.write(u'other projects', exc=True)
        return out

    def on_new_version(self, sender, args):
        it = self.current
        if it is None or not self.is_admin:
            return
        self._publish_window(it, {'family_id': it.card['id']})

    def _publish_window(self, it, prefill):
        import os
        from pyrevit import HOST_APP
        from peer_library.ui_publish import PublishWindow
        from peer_library import version as _version
        xaml = os.path.join(_version.bundle_dir('Publish.smartbutton'), 'PublishWindow.xaml')
        win = PublishWindow(xaml, HOST_APP.app, self.backend, prefill)
        win.ShowDialog()
        if win.published:
            self._refresh_item(it, win.published)
            self._refresh_statuses()
            self._show_details(it)
        return win.published

    def _restore_handler(self, it, h):
        return lambda s, a: self._restore(it, h)

    def _restore(self, it, h):
        """Old version -> Publish window as the next version (the file gets the
        new PEER_Version and a fresh preview there). Needs Revit 2024."""
        import os
        import shutil
        from peer_library import publish, rfa_info
        card = it.card
        work = publish.workdir_for(card['id']) + u'.restore'
        target = os.path.join(work, card['id'] + u'.rfa')     # file name = family name
        self.Cursor = Cursors.Wait
        try:
            shutil.rmtree(work, ignore_errors=True)
            self.backend.download(h['files']['.rfa'], target)
            if h.get('sha1') and rfa_info.sha1(target) != h['sha1']:
                raise Exception(strings.RESTORE_BAD.format(h.get('v')))
        except Exception as ex:
            log.write(u'restore {0} v{1}'.format(card['id'], h.get('v')), exc=True)
            U.error(u'{0}'.format(ex))
            return
        finally:
            self.Cursor = None
        try:
            self._publish_window(it, {'family_id': card['id'], 'file': target,
                                      'reason': strings.RESTORE_NOTE.format(h.get('v'))})
        finally:
            shutil.rmtree(work, ignore_errors=True)

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
        new_png = card.get('png_sha1') != it.card.get('png_sha1')
        it.card = card
        it.entry = search.Entry(card)
        it.name_block.Text = self._tile_name(it)
        if new_png:                          # new version with a new preview
            it.image.Source = None
            it.preview_done = False
            it.png = P_WAIT
            if self._downloader is None or not self._downloader.is_alive():
                self._start_downloader()
            self.timer.Start()
        it.lbi.Content.ToolTip = u'{0}\n{1}'.format(card['id'], groups.title(card.get('group')))

    def on_edit_info(self, sender, args):
        it = self.current
        if it is None or not self.is_admin:
            return
        from peer_library.ui_dialogs import EditInfoWindow
        win = EditInfoWindow(it.card, owner=self, known_ids=[x.card['id'] for x in self.items])
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
        if self.doc.IsFamilyDocument or self._refuse_old_revit():
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
        done, failed, not_replaced = self._load_many(todo)
        text = strings.COLL_DONE.format(len(done))
        if skipped:
            text += u'\n\n' + strings.COLL_CATALOGS.format(u', '.join(skipped))
        U.info(_batch_text(text, failed, not_replaced))

    def _load_many(self, todo, keep_types=False):
        """Load / update several families. A family that is in the project is
        checked first and left alone when the update would break something or
        when it is not from the library. Returns (done ids, failure texts,
        texts of the families left alone)."""
        done, failed, skipped = [], [], []
        self.Cursor = Cursors.Wait
        try:
            for x in todo:
                card = x.card
                self.status_text.Text = strings.DOWNLOADING.format(card['id'])
                U.refresh(self)
                try:
                    path = self.cache.get(card, '.rfa')
                    types = None
                    if keep_types and card.get('type_catalog'):
                        self.cache.get(card, '.txt')
                        types = loader.family_type_names(
                            self.doc, loader.find_family(self.doc, card['id'])) or None
                    self.status_text.Text = strings.CHECKING.format(card['id'])
                    U.refresh(self)
                    problem = self._quiet_check(self.doc, card, path, types)
                    if problem:
                        skipped.append(u'{0}: {1}'.format(card['id'], problem))
                        continue
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
        return done, failed, skipped

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
        if sel and self._refuse_old_revit():
            return
        if not sel:
            U.info(strings.PROJ_SELECT_LIBRARY)
            return
        if not U.ask(strings.UPDATE_ALL_ASK.format(len(sel))):
            return
        done, failed, skipped = self._load_many([r['item'] for r in sel], keep_types=True)
        self._fill_project()
        U.info(_batch_text(strings.UPDATE_ALL_DONE.format(len(done)), failed, skipped))

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
        from peer_library import version as _version
        xaml = os.path.join(_version.bundle_dir('Propose.smartbutton'), 'ProposeWindow.xaml')
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
            sub = u'{0}{1}'.format(U.local_time(p.get('sent')),
                                   (u' · ' + p['comment']) if p.get('comment') else u'')
            self.mine_list.Items.Add(self._line(p.get('name') or p['id'], sub,
                                                labels.get(p.get('status'), labels['pending'])))


def _batch_text(text, failed, skipped):
    """Result message of a load of several families."""
    if skipped:
        text += u'\n\n' + strings.CHECK_SKIPPED + u'\n' + u'\n'.join(u'- ' + s for s in skipped[:12])
        if len(skipped) > 12:
            text += u'\n... (+{0})'.format(len(skipped) - 12)
    if failed:
        text += u'\n\n' + u'\n'.join(failed[:10])
    return text
