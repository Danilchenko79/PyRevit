# -*- coding: utf-8 -*-
"""Shared helpers for reading structure out of Revit links.

The documentation model often holds nothing but views: the concrete lives in
a linked structural model. Every tool that measures geometry therefore has to
walk a list of SOURCES rather than a single document.

A source is the triple (document, transform, link_instance):

    document        where the elements live
    transform       link space -> host space; Transform.Identity for the host
    link_instance   the RevitLinkInstance, or None for the host

Two rules keep the callers honest:

  * Geometry read from a source is in THAT source's coordinates. Put it into
    host coordinates with the source transform before comparing it with
    anything else (`to_host`, `host_bbox`).
  * A Reference taken from linked geometry cannot be used in the host
    document as it is. Run it through `host_ref` first, which is what lets a
    dimension bind to a linked face.

The host is always the first source, so a model that has no links behaves
exactly as it did before.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, Options, RevitLinkInstance, Transform,
    ViewDetailLevel, XYZ,
)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class Source(object):
    """One document to read geometry from, with the way back to host space."""

    __slots__ = ('doc', 'xform', 'link', 'index')

    def __init__(self, doc, xform, link, index):
        self.doc = doc
        self.xform = xform
        self.link = link
        self.index = index

    @property
    def is_link(self):
        return self.link is not None

    @property
    def name(self):
        if self.link is None:
            return u'host'
        try:
            return self.link.Name
        except Exception:
            return u'link {}'.format(self.link.Id.IntegerValue)

    def to_host(self, p):
        """A point of this source, in host coordinates."""
        return p if self.link is None else self.xform.OfPoint(p)

    def to_source(self, p):
        """A host point, in this source's coordinates."""
        return p if self.link is None else self.xform.Inverse.OfPoint(p)

    def vec_to_host(self, v):
        return v if self.link is None else self.xform.OfVector(v)

    def vec_to_source(self, v):
        return v if self.link is None else self.xform.Inverse.OfVector(v)

    def ref(self, reference):
        """`reference` as the host document can use it (dimensions, tags)."""
        return host_ref(reference, self.link)

    def key(self, el):
        """An element key unique across documents (ids repeat per document)."""
        try:
            return (self.index, el.Id.IntegerValue)
        except Exception:
            return (self.index, id(el))


def link_instances(doc, view=None):
    """Loaded link instances, restricted to `view` when one is given."""
    out = []
    try:
        col = (FilteredElementCollector(doc, view.Id) if view is not None
               else FilteredElementCollector(doc))
        for li in col.OfClass(RevitLinkInstance):
            try:
                if li.GetLinkDocument() is not None:
                    out.append(li)
            except Exception:
                continue
    except Exception:
        pass
    return out


def sources(doc, view=None, include_links=True, include_host=True):
    """The host first, then every loaded link visible on the view.

    Pass view=None to reach links the view happens to hide (the section
    tools probe geometry, they do not care what the plan shows).
    """
    out = []
    if include_host:
        out.append(Source(doc, Transform.Identity, None, 0))
    if include_links:
        for li in link_instances(doc, view):
            try:
                out.append(Source(li.GetLinkDocument(), li.GetTotalTransform(),
                                  li, len(out)))
            except Exception:
                continue
    return out


# Дисциплина связи — по токенам имени файла (KRM-ST-MAIN, KRM_AR_FL_TYP_X).
# По содержимому не определить: в АР-моделях тоже бывают балки и плиты.
STRUCT_TOKENS = (u'ST', u'STR', u'STRU', u'STRUCT', u'STRUCTURAL', u'KZ', u'KJ',
                 u'KR', u'CON', u'CONST', u'SE')
# одиночных букв (A, B) нет: так называют части здания (BLD_A, BLD_B)
OTHER_TOKENS = (u'AR', u'ARC', u'ARCH', u'ARX', u'MEP', u'ME', u'MEC',
                u'EL', u'ELE', u'ELEC', u'PL', u'PLB', u'PLUMB', u'HVAC', u'FP',
                u'INT', u'LAND', u'LS', u'SITE', u'FUR')


def _tokens(text):
    out, cur = [], []
    for ch in (text or u'').upper():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append(u''.join(cur))
            cur = []
    if cur:
        out.append(u''.join(cur))
    return out


def _discipline_of(text):
    toks = _tokens(text)
    if any(t in STRUCT_TOKENS for t in toks):
        return u'ST'
    if any(t in OTHER_TOKENS for t in toks):
        return u'OTHER'
    return None


def link_discipline(src):
    """'ST' (конструктив), 'OTHER' (АР/ОВ/ВК/...) или '?' для связи.

    Решает имя файла самой модели; если по нему не понятно — вся цепочка
    вложения (АР-модель внутри АР-связи остаётся архитектурой)."""
    if not src.is_link:
        return u'ST'
    try:
        title = src.doc.Title
    except Exception:
        title = u''
    d = _discipline_of(title)
    if d is None:
        d = _discipline_of(src.name)
    return d or u'?'


def unique_sources(srcs, tol=1e-3):
    """Без повторов: одна и та же модель, вставленная в то же место дважды
    (вложенная связь + прямая) — один источник, иначе плиты считаются дважды."""
    out, seen = [], []
    for s in srcs:
        if not s.is_link:
            out.append(s)
            continue
        try:
            sig = (s.doc.PathName or s.doc.Title, s.xform.Origin,
                   s.xform.BasisX)
        except Exception:
            out.append(s)
            continue
        dup = False
        for p, o, bx in seen:
            if (p == sig[0] and o.IsAlmostEqualTo(sig[1], tol)
                    and bx.IsAlmostEqualTo(sig[2], tol)):
                dup = True
                break
        if not dup:
            seen.append(sig)
            out.append(s)
    return out


def structural_sources(doc, view, categories, min_count=1):
    """Only the sources that actually carry any of `categories`.

    A documentation model links in furniture, MEP and the architectural
    model as well; walking all of them costs time and can drag foreign
    geometry into a chain. Keep the ones that hold structure.
    """
    out = []
    for src in sources(doc, view):
        n = 0
        for bic in categories:
            try:
                n += (FilteredElementCollector(src.doc).OfCategory(bic)
                      .WhereElementIsNotElementType().GetElementCount())
            except Exception:
                continue
            if n >= min_count:
                break
        if n >= min_count:
            out.append(src)
    return out


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

def host_ref(reference, link):
    """A reference the host document accepts, or None when it cannot be made.

    Geometry of a linked element yields a reference that lives in the link's
    document. CreateLinkReference prefixes it with the link instance, which
    is the only form a host dimension can bind to.
    """
    if reference is None:
        return None
    if link is None:
        return reference
    try:
        return reference.CreateLinkReference(link)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def geometry_options(view=None, references=True,
                     detail=ViewDetailLevel.Fine):
    """Options for get_Geometry.

    A host view cannot be used to read a linked element, so pass view=None
    for links and let the detail level decide what comes back.
    """
    opts = Options()
    opts.ComputeReferences = bool(references)
    opts.IncludeNonVisibleObjects = False
    if view is not None:
        opts.View = view
    else:
        opts.DetailLevel = detail
    return opts


def source_options(src, view=None, references=True):
    """`geometry_options` bound to a source: the view only applies to the host."""
    return geometry_options(None if src.is_link else view, references)


def host_bbox(el, xform, view=None):
    """(xmin, xmax, ymin, ymax, zmin, zmax) of an element, in host space.

    All eight corners go through the transform, so a rotated or mirrored
    link gives a correct box rather than a skewed one.
    """
    try:
        bb = el.get_BoundingBox(view)
    except Exception:
        bb = None
    if bb is None:
        return None
    lo, hi = bb.Min, bb.Max
    if bb.Transform is not None:
        try:
            xform = xform.Multiply(bb.Transform)
        except Exception:
            pass
    xs, ys, zs = [], [], []
    for x in (lo.X, hi.X):
        for y in (lo.Y, hi.Y):
            for z in (lo.Z, hi.Z):
                q = xform.OfPoint(XYZ(x, y, z))
                xs.append(q.X)
                ys.append(q.Y)
                zs.append(q.Z)
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def is_axis_aligned(xform, tol=1e-6):
    """True when the transform keeps X along X and Y along Y (up to sign).

    Chains and section boxes are built on world axes. A link rotated off the
    axes still works, but its faces stop being axis-aligned, so a caller may
    want to warn instead of silently dimensioning nothing.
    """
    try:
        bx, by, bz = xform.BasisX, xform.BasisY, xform.BasisZ
    except Exception:
        return True
    if abs(bz.Z) < 1.0 - 1e-6:
        return False
    ok_x = abs(abs(bx.X) - 1.0) < tol or abs(abs(bx.Y) - 1.0) < tol
    ok_y = abs(abs(by.X) - 1.0) < tol or abs(abs(by.Y) - 1.0) < tol
    return ok_x and ok_y


def describe(srcs):
    """One short line naming the sources, for the run report."""
    names = []
    for s in srcs:
        names.append(u'host' if not s.is_link else s.name)
    return u', '.join(names) if names else u'-'
