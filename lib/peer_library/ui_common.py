# -*- coding: utf-8 -*-
"""WPF helpers shared by the library windows (IronPython inside Revit).

Colours: high contrast, no blue (ТЗ). Every status has a text label too.
"""

import clr

clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from System import Uri, UriKind  # noqa: E402
from System.Windows import CornerRadius, FontWeights, MessageBox, MessageBoxButton, MessageBoxImage, \
    MessageBoxResult, Thickness  # noqa: E402
from System.Windows.Controls import Border, TextBlock  # noqa: E402
from System.Windows.Media import BrushConverter  # noqa: E402
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage  # noqa: E402

from peer_library import loader, strings  # noqa: E402

_conv = BrushConverter()


def brush(hex_color):
    return _conv.ConvertFromString(hex_color)


INK = '#111827'
MUTED = '#57534E'
LINE = '#D6D3D1'
CARD_BG = '#FFFFFF'

# status -> (text colour, background)
STATUS_COLORS = {
    loader.MISSING: ('#44403C', '#F5F5F4'),
    loader.CURRENT: ('#14532D', '#DCFCE7'),
    loader.OUTDATED: ('#7C2D12', '#FFEDD5'),
    loader.UNKNOWN: ('#581C87', '#F3E8FF'),
    loader.NEWER: ('#7F1D1D', '#FEE2E2'),
}


def chip(text, code, small=True):
    fg, bg = STATUS_COLORS.get(code, (INK, '#F5F5F4'))
    b = Border()
    b.CornerRadius = CornerRadius(4)
    b.Background = brush(bg)
    b.BorderBrush = brush(fg)
    b.BorderThickness = Thickness(1)
    b.Padding = Thickness(5, 1, 5, 1)
    t = TextBlock()
    t.Text = text
    t.FontSize = 10.5 if small else 12
    t.Foreground = brush(fg)
    t.FontWeight = FontWeights.SemiBold
    b.Child = t
    return b


def new_badge():
    b = Border()
    b.CornerRadius = CornerRadius(3)
    b.Background = brush(INK)
    b.Padding = Thickness(4, 0, 4, 1)
    t = TextBlock()
    t.Text = strings.ST_NEW
    t.FontSize = 10
    t.FontWeight = FontWeights.Bold
    t.Foreground = brush('#FFFFFF')
    b.Child = t
    return b


def bitmap(path, width=None):
    if not path:
        return None
    try:
        img = BitmapImage()
        img.BeginInit()
        img.CacheOption = BitmapCacheOption.OnLoad          # file not locked
        if width:
            img.DecodePixelWidth = width
        img.UriSource = Uri(path, UriKind.Absolute)
        img.EndInit()
        img.Freeze()
        return img
    except Exception:
        return None


def local_time(iso, seconds=False):
    """Service time (UTC, '2026-11-20T04:42:27') -> local 'YYYY-MM-DD HH:MM'."""
    import datetime
    if not iso:
        return u''
    try:
        t = datetime.datetime.strptime(iso[:19], '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return iso.replace(u'T', u' ')
    offset = datetime.datetime.now() - datetime.datetime.utcnow()
    t = t + datetime.timedelta(seconds=round(offset.total_seconds() / 60.0) * 60)
    return t.strftime('%Y-%m-%d %H:%M:%S' if seconds else '%Y-%m-%d %H:%M')


def info(text, title=strings.APP):
    MessageBox.Show(text, title, MessageBoxButton.OK, MessageBoxImage.Information)


def error(text, title=strings.APP):
    MessageBox.Show(text, title, MessageBoxButton.OK, MessageBoxImage.Warning)


def ask(text, title=strings.APP):
    r = MessageBox.Show(text, title, MessageBoxButton.YesNo, MessageBoxImage.Question)
    return r == MessageBoxResult.Yes
