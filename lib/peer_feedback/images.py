# -*- coding: utf-8 -*-
"""Screenshots and pictures for a request: clipboard (Ctrl+V), files, drag & drop.

WPF / .NET only (Revit). Every picture is shrunk to MAX_SIDE px on the long
side and saved as JPEG, so a full-screen screenshot is ~150-400 KB. The
receiver stores the files in a Google Drive folder and puts their links on
the request's row.
"""

from peer_feedback import payload

MAX_SIDE = 1600
QUALITY = 85
EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff')


def _wpf():
    import clr
    clr.AddReference('PresentationCore')
    clr.AddReference('WindowsBase')


def is_image_path(path):
    return payload.u(path).lower().endswith(EXTENSIONS)


def from_clipboard():
    """[BitmapSource] from the clipboard: a copied picture or copied image files."""
    _wpf()
    from System.Windows import Clipboard
    out = []
    try:
        if Clipboard.ContainsImage():
            img = Clipboard.GetImage()
            if img is not None:
                out.append(img)
        elif Clipboard.ContainsFileDropList():
            out.extend(from_files([p for p in Clipboard.GetFileDropList()]))
    except Exception:
        pass
    return out


def clipboard_has_image():
    _wpf()
    from System.Windows import Clipboard
    try:
        if Clipboard.ContainsImage():
            return True
        if Clipboard.ContainsFileDropList():
            return any(is_image_path(p) for p in Clipboard.GetFileDropList())
    except Exception:
        pass
    return False


def clipboard_has_text():
    """Text on the clipboard. Excel / Word copy text AND a picture of it."""
    _wpf()
    from System.Windows import Clipboard
    try:
        return bool(Clipboard.ContainsText())
    except Exception:
        return False


def from_files(paths):
    _wpf()
    from System import Uri, UriKind
    from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
    out = []
    for p in paths:
        if not is_image_path(p):
            continue
        try:
            bmp = BitmapImage()
            bmp.BeginInit()
            bmp.CacheOption = BitmapCacheOption.OnLoad   # do not keep the file locked
            bmp.UriSource = Uri(p, UriKind.Absolute)
            bmp.EndInit()
            bmp.Freeze()
            out.append(bmp)
        except Exception:
            continue
    return out


def _scaled(bmp, max_side):
    from System.Windows.Media import ScaleTransform
    from System.Windows.Media.Imaging import TransformedBitmap
    w, h = bmp.PixelWidth, bmp.PixelHeight
    side = max(w, h)
    if side <= max_side:
        return bmp
    k = float(max_side) / side
    return TransformedBitmap(bmp, ScaleTransform(k, k))


def _flatten(bmp):
    """Clipboard screenshots often carry alpha: JPEG needs an opaque image."""
    from System.Windows.Media import PixelFormats
    from System.Windows.Media.Imaging import FormatConvertedBitmap
    try:
        return FormatConvertedBitmap(bmp, PixelFormats.Bgr24, None, 0)
    except Exception:
        return bmp


def encode(bmp, max_side=MAX_SIDE, quality=QUALITY):
    """BitmapSource -> base64 text of a JPEG (unicode)."""
    _wpf()
    from System.IO import MemoryStream
    from System.Windows.Media.Imaging import JpegBitmapEncoder, BitmapFrame
    enc = JpegBitmapEncoder()
    enc.QualityLevel = quality
    enc.Frames.Add(BitmapFrame.Create(_flatten(_scaled(bmp, max_side))))
    ms = MemoryStream()
    try:
        enc.Save(ms)
        data = ms.ToArray()
    finally:
        ms.Close()
    from System import Convert
    return payload.u(Convert.ToBase64String(data))


def encode_fitting(bmp, limit=payload.MAX_IMAGE_B64):
    """encode() smaller until the base64 text fits the limit, or None."""
    for side, q in ((MAX_SIDE, QUALITY), (1280, 80), (1024, 75), (800, 70)):
        b64 = encode(bmp, side, q)
        if len(b64) <= limit:
            return b64
    return None


def b64_size_kb(b64):
    return int(len(b64) * 3 / 4 / 1024)
