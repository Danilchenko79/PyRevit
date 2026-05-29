# -*- coding: utf-8 -*-
"""Level helpers built around the shared parameter PR_Level.

PR_Level holds the level *number* the user assigns by hand: 100, 110, 120 ...
(each step of 10 = a new unique level; 100 = foundation). Only levels that
carry a PR_Level value take part in sheet creation. From that number the sheet
numbers are derived elsewhere as base, base+2, base+5.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, Level, StorageType,
)

PR_LEVEL_PARAM = "PR_Level"


def collect_levels(doc):
    """All levels in the project, sorted by elevation (low -> high)."""
    levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
    return sorted(levels, key=lambda l: l.Elevation)


def get_pr_level_raw(level):
    """PR_Level as a display string ('' when unset). Storage-type aware."""
    p = level.LookupParameter(PR_LEVEL_PARAM)
    if not p or not p.HasValue:
        return ""
    st = p.StorageType
    if st == StorageType.Integer:
        return str(p.AsInteger())
    if st == StorageType.Double:
        d = p.AsDouble()
        if abs(d - round(d)) < 1e-6:
            return str(int(round(d)))
        return str(d)
    if st == StorageType.String:
        return p.AsString() or ""
    return ""


def get_pr_level_int(level):
    """PR_Level as a positive int, or None when unset / not a usable number."""
    raw = get_pr_level_raw(level)
    if not raw:
        return None
    try:
        value = int(round(float(str(raw).replace(",", "."))))
    except (ValueError, TypeError):
        return None
    return value if value > 0 else None


def set_pr_level(level, value_str):
    """Write PR_Level from a UI string. Caller must own the transaction.

    Empty string clears the value (numeric params are set to 0, which
    get_pr_level_int() then treats as 'unset').
    Returns True if a write happened.
    """
    p = level.LookupParameter(PR_LEVEL_PARAM)
    if not p or p.IsReadOnly:
        return False

    value_str = (value_str or "").strip().replace(",", ".")
    st = p.StorageType

    try:
        if value_str == "":
            if st == StorageType.String:
                p.Set("")
            else:
                p.Set(0)
            return True

        if st == StorageType.Integer:
            p.Set(int(round(float(value_str))))
        elif st == StorageType.Double:
            p.Set(float(value_str))
        elif st == StorageType.String:
            p.Set(value_str)
        else:
            return False
        return True
    except Exception:
        return False


def levels_with_pr(doc):
    """Levels that carry a PR_Level value, sorted by elevation (low -> high).

    Returns a list of (level, base_number) tuples.
    """
    result = []
    for lvl in collect_levels(doc):
        base = get_pr_level_int(lvl)
        if base is not None:
            result.append((lvl, base))
    return result


def group_by_base(ordered_pr_levels):
    """Group levels that share a PR_Level value into logical levels.

    `ordered_pr_levels` is the list of (level, base) from levels_with_pr().

    Returns a list of (base, [levels]) sorted by base ascending; the levels
    inside each group are sorted by elevation (low -> high). The previous
    logical level is simply the previous entry in this list.
    """
    groups = {}
    for lvl, base in ordered_pr_levels:
        groups.setdefault(base, []).append(lvl)

    result = []
    for base in sorted(groups.keys()):
        lvls = sorted(groups[base], key=lambda l: l.Elevation)
        result.append((base, lvls))
    return result
