# -*- coding: utf-8 -*-
"""Revit side of publishing (IronPython, inside Revit only).

prepare_family(app, source, family_id, version, workdir):
    copy -> open in background -> checks -> PEER_Version into every type ->
    PNG preview 256x256 -> save compact -> close. The user's source file is
    never touched.
"""

import os
import shutil

import clr
from Autodesk.Revit import DB
from System.Collections.Generic import List

from peer_library import checks_file, log

VERSION_PARAM = 'PEER_Version'
PREVIEW_PX = 256


class Guard(DB.IFailuresPreprocessor):
    """Warnings are dropped, errors roll the transaction back silently."""

    last_errors = []

    def PreprocessFailures(self, fa):
        err = False
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(f)
            else:
                err = True
                try:
                    Guard.last_errors.append(f.GetDescriptionText())
                except Exception:
                    pass
        if err:
            return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


def _transaction(doc, name):
    tx = DB.Transaction(doc, name)
    o = tx.GetFailureHandlingOptions()
    o.SetFailuresPreprocessor(Guard())
    o.SetClearAfterRollback(True)
    tx.SetFailureHandlingOptions(o)
    return tx


def revit_version(app):
    try:
        return int(app.VersionNumber)
    except (TypeError, ValueError):
        return 0


# ---- checks on the open family ---------------------------------------------
def family_checks(fd):
    res = []
    fam = fd.OwnerFamily
    cat = fam.FamilyCategory if fam else None
    if cat is None:
        res.append(('error', 'category', u'Family category is not set'))
    n_imports = DB.FilteredElementCollector(fd).OfClass(DB.ImportInstance).GetElementCount()
    if n_imports:
        res.append(('warning', 'cad', u'{0} imported / linked CAD file(s) inside the family'
                                      .format(n_imports)))
    if fd.FamilyManager.Types.Size == 0:
        res.append(('warning', 'types', u'Family has no named types - one will be created'))
    n_param = 0
    for p in fd.FamilyManager.GetParameters():
        if not p.IsShared and p.Definition.Name != VERSION_PARAM and p.Id.IntegerValue > 0:
            n_param += 1
    if n_param:
        res.append(('info', 'params', u'{0} family parameter(s) are not shared parameters'
                                      .format(n_param)))
    return res, (cat.Name if cat else u'')


def _version_param(fd):
    fm = fd.FamilyManager
    p = fm.get_Parameter(VERSION_PARAM)
    if p is None:
        p = fm.AddParameter(VERSION_PARAM, DB.GroupTypeId.IdentityData,
                            DB.SpecTypeId.Int.Integer, False)
    return p


def stamp_version(fd, version, family_id):
    """PEER_Version = version for every type, as a formula ("3").

    A formula is one value for all types, so the types are not switched one
    by one: some families have types that do not regenerate ("Constraints
    are not satisfied") and switching to them rolls everything back.
    Returns problem text or None."""
    fm = fd.FamilyManager
    Guard.last_errors = []
    tx = _transaction(fd, 'PEER: library version')
    tx.Start()
    try:
        if fm.Types.Size == 0:
            fm.NewType(family_id)
        p = _version_param(fd)
        if p.IsInstance:
            fm.MakeType(p)
        if p.StorageType != DB.StorageType.Integer:
            raise Exception(u'{0} exists but is not an integer'.format(VERSION_PARAM))
        fm.SetFormula(p, str(int(version)))
        tx.Commit()
    finally:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
    if tx.GetStatus() != DB.TransactionStatus.Committed:
        return u'Revit rejected the change: ' + u'; '.join(Guard.last_errors or [u'?'])
    p = fm.get_Parameter(VERSION_PARAM)
    if p is None or (p.Formula or u'').strip() != str(int(version)):
        return u'the formula was not kept'
    return None


# ---- preview ---------------------------------------------------------------
def _is_model(fd):
    cat = fd.OwnerFamily.FamilyCategory if fd.OwnerFamily else None
    return cat is not None and cat.CategoryType == DB.CategoryType.Model


def _printable_views(fd):
    out = []
    for v in DB.FilteredElementCollector(fd).OfClass(DB.View):
        try:
            if not v.IsTemplate and v.CanBePrinted:
                out.append(v)
        except Exception:
            pass
    return out


def pick_view(fd):
    """3D view for model families (created if missing), else the first plan."""
    views = _printable_views(fd)
    if _is_model(fd):
        v3 = [v for v in views if isinstance(v, DB.View3D) and not v.IsPerspective]
        if v3:
            return v3[0], False
        vft = [t for t in DB.FilteredElementCollector(fd).OfClass(DB.ViewFamilyType)
               if t.ViewFamily == DB.ViewFamily.ThreeDimensional]
        if vft:
            return vft[0], True
    plans = [v for v in views if isinstance(v, DB.ViewPlan)]
    if plans:
        return plans[0], False
    return (views[0] if views else None), False


# Hidden in the preview only: they stretch the view far beyond the family.
PREVIEW_HIDE = ('OST_CLines', 'OST_ReferenceLines', 'OST_Dimensions', 'OST_SketchLines')


def _setup_view(fd, family_id):
    """(view, restore) for the preview. Changes the view (3D style, hidden
    reference planes / dimensions) and returns a function that undoes them,
    so the published family keeps its views as the author left them."""
    view, create = pick_view(fd)
    if view is None:
        return None, None
    undo = {'created': None, 'hidden': [], 'style': None}
    tx = _transaction(fd, 'PEER: preview view')
    tx.Start()
    try:
        if create:
            try:
                view = DB.View3D.CreateIsometric(fd, view.Id)
                undo['created'] = view.Id
            except Exception:            # detail / rebar shape families: no 3D
                plans = [v for v in _printable_views(fd) if isinstance(v, DB.ViewPlan)]
                others = _printable_views(fd)
                view = plans[0] if plans else (others[0] if others else None)
        if view is not None:
            if isinstance(view, DB.View3D) and undo['created'] is None:
                undo['style'] = (view.DisplayStyle, view.DetailLevel)
            if isinstance(view, DB.View3D):
                try:
                    view.DisplayStyle = DB.DisplayStyle.ShadingWithEdges
                    view.DetailLevel = DB.ViewDetailLevel.Fine
                except Exception:
                    pass
            for name in PREVIEW_HIDE:
                bic = getattr(DB.BuiltInCategory, name, None)
                cat = DB.Category.GetCategory(fd, bic) if bic is not None else None
                try:
                    if cat is not None and view.CanCategoryBeHidden(cat.Id) \
                            and not view.GetCategoryHidden(cat.Id):
                        view.SetCategoryHidden(cat.Id, True)
                        undo['hidden'].append(cat.Id)
                except Exception:
                    pass
        tx.Commit()
    finally:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()

    def restore():
        t2 = _transaction(fd, 'PEER: restore preview view')
        t2.Start()
        try:
            if undo['created'] is not None:
                fd.Delete(undo['created'])
            else:
                for cid in undo['hidden']:
                    view.SetCategoryHidden(cid, False)
                if undo['style']:
                    view.DisplayStyle, view.DetailLevel = undo['style']
            t2.Commit()
        finally:
            if t2.HasStarted() and not t2.HasEnded():
                t2.RollBack()
    return view, restore


def _content_box(img):
    """Bounding box of non-white pixels, found on a small copy (fast)."""
    from System.Drawing import Bitmap
    side = 160
    k = float(side) / max(img.Width, img.Height)
    sw, sh = max(1, int(img.Width * k)), max(1, int(img.Height * k))
    small = Bitmap(img, sw, sh)
    try:
        xs, ys = [], []
        for y in range(sh):
            for x in range(sw):
                c = small.GetPixel(x, y)
                if c.A > 20 and (c.R < 235 or c.G < 235 or c.B < 235):
                    xs.append(x)
                    ys.append(y)
    finally:
        small.Dispose()
    if not xs:
        return None
    pad = 2
    x0, x1 = max(0, min(xs) - pad), min(sw, max(xs) + 1 + pad)
    y0, y1 = max(0, min(ys) - pad), min(sh, max(ys) + 1 + pad)
    return int(x0 / k), int(y0 / k), int((x1 - x0) / k), int((y1 - y0) / k)


def _square_png(src, dst, size):
    clr.AddReference('System.Drawing')
    from System.Drawing import Bitmap, Color, Graphics, GraphicsUnit, Rectangle
    from System.Drawing.Drawing2D import InterpolationMode
    from System.Drawing.Imaging import ImageFormat
    img = Bitmap(src)
    try:
        box = _content_box(img) or (0, 0, img.Width, img.Height)
        bw, bh = max(1, min(box[2], img.Width - box[0])), max(1, min(box[3], img.Height - box[1]))
        canvas = Bitmap(size, size)
        g = Graphics.FromImage(canvas)
        try:
            g.Clear(Color.White)
            g.InterpolationMode = InterpolationMode.HighQualityBicubic
            pad = 10
            k = min(float(size - 2 * pad) / bw, float(size - 2 * pad) / bh, 3.0)
            w, h = max(1, int(bw * k)), max(1, int(bh * k))
            g.DrawImage(img, Rectangle((size - w) // 2, (size - h) // 2, w, h),
                        Rectangle(box[0], box[1], bw, bh), GraphicsUnit.Pixel)
        finally:
            g.Dispose()
        canvas.Save(dst, ImageFormat.Png)
        canvas.Dispose()
    finally:
        img.Dispose()


def image_type_preview(fd, png_path):
    """Rebar shape families have no geometry - use the shape sketch stored in
    the family (ImageType). Returns the path or None."""
    clr.AddReference('System.Drawing')
    from System.Drawing.Imaging import ImageFormat
    for it in DB.FilteredElementCollector(fd).OfClass(DB.ImageType):
        try:
            img = it.GetImage()
        except Exception:
            continue
        if img is None:
            continue
        tmp = png_path + '.src.png'
        img.Save(tmp, ImageFormat.Png)
        img.Dispose()
        _square_png(tmp, png_path, PREVIEW_PX)
        os.remove(tmp)
        return png_path
    return None


def export_preview(fd, view, png_path):
    tmp = os.path.join(os.path.dirname(png_path), '_img')
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    opts = DB.ImageExportOptions()
    opts.ExportRange = DB.ExportRange.SetOfViews
    opts.SetViewsAndSheets(List[DB.ElementId]([view.Id]))
    opts.ZoomType = DB.ZoomFitType.FitToPage
    opts.PixelSize = PREVIEW_PX * 3
    opts.ImageResolution = DB.ImageResolution.DPI_150
    opts.HLRandWFViewsFileType = DB.ImageFileType.PNG
    opts.ShadowViewsFileType = DB.ImageFileType.PNG
    opts.FilePath = os.path.join(tmp, 'preview')
    fd.ExportImage(opts)
    pngs = [os.path.join(tmp, f) for f in os.listdir(tmp) if f.lower().endswith('.png')]
    if not pngs:
        raise Exception(u'Revit exported no image')
    _square_png(pngs[0], png_path, PREVIEW_PX)
    shutil.rmtree(tmp, ignore_errors=True)
    return png_path


# ---- whole preparation -----------------------------------------------------
def prepare_family(app, source, family_id, version, workdir):
    """-> dict(results, rfa, png, catalog, category, revit).

    results: list of (level, code, text); any 'error' = do not publish.
    """
    out = {'results': [], 'rfa': None, 'png': None, 'catalog': None,
           'category': u'', 'revit': None, 'types': []}
    res = out['results']
    file_res, year = checks_file.check_file(source, family_id)
    res.extend(file_res)
    out['revit'] = year
    ver = revit_version(app)
    if ver != checks_file.LIBRARY_REVIT:
        res.append(('error', 'revit_app', u'Publish from Revit {0} only (this is Revit {1}) - '
                                          u'otherwise the file is saved in a newer format'
                                          .format(checks_file.LIBRARY_REVIT, ver)))
    if checks_file.errors(res):
        return out

    src_dir = os.path.join(workdir, 'src')
    out_dir = os.path.join(workdir, 'out')
    for d in (src_dir, out_dir):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    copy = os.path.join(src_dir, family_id + '.rfa')
    shutil.copyfile(source, copy)
    target = os.path.join(out_dir, family_id + '.rfa')

    fd = None
    try:
        try:
            fd = app.OpenDocumentFile(copy)
        except Exception as ex:
            log.write(u'open {0}: {1}'.format(source, ex), exc=True)
            res.append(('error', 'open', u'Revit could not open the family: {0}'.format(ex)))
            return out
        if not fd.IsFamilyDocument:
            res.append(('error', 'not_family', u'Not a family document'))
            return out
        doc_res, out['category'] = family_checks(fd)
        res.extend(doc_res)
        try:
            out['types'] = [t.Name for t in fd.FamilyManager.Types if t.Name and t.Name.strip()]
        except Exception:
            out['types'] = []
        if checks_file.errors(res):
            return out
        try:
            problem = stamp_version(fd, version, family_id)
        except Exception as ex:
            log.write(u'stamp {0}'.format(family_id), exc=True)
            problem = u'{0}'.format(ex)
        if problem:
            res.append(('warning', 'version', u'{0} not written: {1} - the version in projects '
                                              u'will show as unknown'.format(VERSION_PARAM, problem)))
        restore = None
        png_path = os.path.join(out_dir, family_id + '.png')
        if out['category'] == u'Rebar Shape':
            try:
                out['png'] = image_type_preview(fd, png_path)
            except Exception:
                log.write(u'rebar shape image {0}'.format(family_id), exc=True)
        try:
            if out['png']:
                view = None
            else:
                view, restore = _setup_view(fd, family_id)
            if view is not None:
                out['png'] = export_preview(fd, view, png_path)
            elif not out['png']:
                res.append(('warning', 'preview', u'No view for a preview'))
        except Exception as ex:
            log.write(u'preview {0}'.format(family_id), exc=True)
            res.append(('warning', 'preview', u'Preview not made: {0}'.format(ex)))
        finally:
            if restore is not None:
                try:
                    restore()
                except Exception:
                    log.write(u'restore view {0}'.format(family_id), exc=True)
        so = DB.SaveAsOptions()
        so.OverwriteExistingFile = True
        so.Compact = True
        so.MaximumBackups = 1
        fd.SaveAs(target, so)
        out['rfa'] = target
    finally:
        if fd is not None:
            try:
                fd.Close(False)
            except Exception:
                log.write(u'close {0}'.format(family_id), exc=True)
    for f in os.listdir(out_dir):
        if f.lower().endswith('.rfa') and f != family_id + '.rfa':
            try:
                os.remove(os.path.join(out_dir, f))   # Revit backups *.0001.rfa
            except OSError:
                pass
    cat = os.path.splitext(source)[0] + '.txt'
    if os.path.isfile(cat):
        dst = os.path.join(out_dir, family_id + '.txt')
        shutil.copyfile(cat, dst)
        out['catalog'] = dst
    return out
