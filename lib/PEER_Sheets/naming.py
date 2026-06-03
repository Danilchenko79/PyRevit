# -*- coding: utf-8 -*-
"""Sheet numbers and (Hebrew) sheet names.

Sheet content language follows the existing project convention (Hebrew),
unlike the tool UI which is English.

A logical level = all Revit levels that share the same PR_Level value. Such
levels usually run consecutively (no PR_Level level between them). When a
logical level spans more than one Revit level, the formwork and slab sheets
are named with an elevation RANGE (from low to high) instead of a single
elevation.

Per PR_Level `base`:
    base      -> formwork plan
    base + 2  -> slab reinforcement plan
    base + 5  -> wall reinforcement plan (from previous logical level up)
"""

FT_TO_M = 0.3048

# Single-elevation templates ({} = elevation X).
TPL_FORMWORK = u"תכנית קומה במפלס {}"
TPL_SLAB = u"תכנית זיון תקרה במפלס {}"

# Range templates ({} {} = low elevation, high elevation).
TPL_FORMWORK_RANGE = u"תכנית קומה ממפלס {} עד {}"
TPL_SLAB_RANGE = u"תכנית זיון תקרה ממפלס {} עד {}"

# Walls: first {} = previous logical level (Y), second {} = current (X).
TPL_WALLS = u"תכנית זיון קירות ממפלס {} עד {}"

# Fixed leading text of every template (before the first elevation). Used to
# recognise sheets this tool created when adopting an existing project.
TEMPLATE_PREFIXES = (
    u"תכנית קומה במפלס ",
    u"תכנית קומה ממפלס ",
    u"תכנית זיון תקרה במפלס ",
    u"תכנית זיון תקרה ממפלס ",
    u"תכנית זיון קירות ממפלס ",
)


def looks_like_tool_sheet(name):
    """True if a sheet name matches one of this tool's name templates."""
    if not name:
        return False
    return any(name.startswith(p) for p in TEMPLATE_PREFIXES)


def ft_to_m(value_ft):
    return value_ft * FT_TO_M


def _fmt_abs(elev_m):
    """Absolute value, always at least one decimal (up to two): 5 -> 5.0."""
    m = round(abs(elev_m), 2)
    s = u"{:.2f}".format(m).rstrip("0")
    if s.endswith("."):
        s += u"0"
    return s


def elevation_str(elev_m):
    """Form used IN sheet names: number then sign (5.1+ / 14.0-).

    The sign trails the number so that, inside the right-to-left Hebrew sheet
    name, it renders correctly as +5.1 / -14.0.
    """
    m = round(elev_m, 2)
    return u"{}{}".format(_fmt_abs(m), u"+" if m >= 0 else u"-")


def format_num(elev_m):
    """Natural human form for UI display/editing: +5.1 / -14.0."""
    m = round(elev_m, 2)
    return u"{}{}".format(u"+" if m >= 0 else u"-", _fmt_abs(m))


def parse_elev(text):
    """Parse a user-typed elevation into a float, or None if invalid.

    Accepts -14, 5, 5.1, 5,1 and a trailing-sign form like 14.0-.
    """
    if text is None:
        return None
    s = text.strip().replace(u",", u".")
    if not s:
        return None
    if s[-1] in u"+-" and s[0] not in u"+-":
        s = s[-1] + s[:-1]
    try:
        return float(s)
    except ValueError:
        return None


def sheet_defs(base, low_str, high_str, is_range, prev_str=None):
    """(kind, name, number) tuples for one logical level.

    `kind` is one of "formwork" / "slab" / "walls" - a stable identity for the
    sheet's role, used to match a sheet to its level across PR_Level changes.

    Elevation strings are passed in already formatted (the caller applies any
    manual label override before calling). `low_str`/`high_str` are the low and
    high elevations of the logical level.

    is_range:
        False -> single Revit level; formwork/slab use high_str (== low_str).
        True  -> several Revit levels share this PR_Level; formwork/slab use
                 the range 'from low_str to high_str'.

    The wall sheet (base+5) is produced only when `prev_str` is given (there is
    a lower logical level). The foundation (100) has none.
    """
    if is_range:
        formwork = TPL_FORMWORK_RANGE.format(low_str, high_str)
        slab = TPL_SLAB_RANGE.format(low_str, high_str)
    else:
        formwork = TPL_FORMWORK.format(high_str)
        slab = TPL_SLAB.format(high_str)

    defs = [
        ("formwork", formwork, str(base)),
        ("slab", slab, str(base + 2)),
    ]
    if prev_str is not None:
        defs.append(("walls", TPL_WALLS.format(prev_str, high_str), str(base + 5)))
    return defs


# --- view names -----------------------------------------------------------
# Each sheet (kind) carries two structural plans: Reaching (RE) and Growing
# (GR). View names are keyed by the PR_Level number (not the sheet number) so
# all of a level's views share the same number, e.g. 120RE / RF.Floor 120RE.
#
# Unlike sheet names (Hebrew), view names use the office's short ASCII codes.
# The kind prefix is the only per-kind part, kept in one dict so a future
# Shift-mode "name constructor" can override it per project / user.

# Sheet number offset per kind (mirrors sheet_defs: base, base+2, base+5).
KIND_OFFSET = {"formwork": 0, "slab": 2, "walls": 5}

# View name prefix per kind. Formwork is bare ("120RE"); reinforcement plans
# carry a discipline prefix.
VIEW_KIND_PREFIX = {
    "formwork": u"",
    "slab": u"RF.Floor ",
    "walls": u"RF.Walls ",
}

# Plan flavours and their long labels (for UI / reports).
FLAVORS = ("RE", "GR")
FLAVOR_LABEL = {"RE": u"Reaching", "GR": u"Growing"}


def sheet_number(base, kind):
    """Sheet number string for a level `base` and sheet role `kind`."""
    return str(base + KIND_OFFSET[kind])


def view_name(base, kind, flavor, prefixes=None):
    """View name for (level base, sheet kind, flavor).

    `flavor` is "RE" or "GR". `prefixes` overrides VIEW_KIND_PREFIX (the future
    user-editable name constructor); when None the built-in prefixes are used.
    """
    pref = (prefixes or VIEW_KIND_PREFIX).get(kind, u"")
    return u"{}{}{}".format(pref, base, flavor)


def view_defs(base, has_walls, prefixes=None):
    """(kind, flavor, view_name) tuples for one logical level.

    Two views (RE + GR) per sheet role: formwork and slab always, walls only
    when `has_walls` (there is a lower logical level - matches sheet_defs).
    """
    kinds = ["formwork", "slab"]
    if has_walls:
        kinds.append("walls")
    out = []
    for kind in kinds:
        for flavor in FLAVORS:
            out.append((kind, flavor, view_name(base, kind, flavor, prefixes)))
    return out
