# -*- coding: utf-8 -*-
"""Diff the planned sheets against the model and apply the confirmed changes.

Pure model side - no UI here.

Sheets are tied to the logical level that produced them, by the set of the
member levels' UniqueIds plus the sheet's `kind` (formwork / slab / walls).
That link is stored in the project JSON (see store.py, key "sheets") and lets
the tool:
    * rename / renumber a sheet when its PR_Level changes (no duplicates);
    * detect orphaned sheets (level deleted or PR_Level cleared);
    * leave foreign sheets (numbers that collide but aren't ours) untouched.

Flow:
    build_diff()    -> classify each planned sheet (new / rename / unchanged /
                       conflict) and list orphaned tool sheets.
    apply_changes() -> create / renumber / rename / delete the confirmed items,
                       then return the rebuilt sheet->level tracking to persist.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewSheet, FamilySymbol, Transaction,
)


def existing_sheets_by_number(doc):
    return dict((s.SheetNumber, s) for s in
                FilteredElementCollector(doc).OfClass(ViewSheet))


def _sheet_by_uid(doc, uid):
    if not uid:
        return None
    el = doc.GetElement(uid)
    return el if isinstance(el, ViewSheet) else None


def build_diff(doc, plan, tracked):
    """Expand the level plan into per-sheet items, compared to the model.

    `plan` rows:
        {"base", "low_str", "high_str", "is_range", "prev_str",
         "level_uids": [level.UniqueId, ...]}.

    `tracked` is the stored sheet link list:
        [{"level_uids": [...], "kind": str, "sheet_uid": str}, ...].

    Returns (items, orphans).

    Each item:
        {"number", "new_name", "kind", "level_uids",
         "current_name" (or None), "current_number" (or None),
         "status": "new"|"rename"|"unchanged"|"conflict", "sheet": ViewSheet|None}

    Each orphan:
        {"sheet": ViewSheet, "number", "name", "kind"} - a tool sheet whose
        logical level no longer exists in the plan.
    """
    from PEER_Sheets.naming import sheet_defs, looks_like_tool_sheet

    by_num = existing_sheets_by_number(doc)

    tracked_index = {}
    for e in tracked:
        tracked_index[(frozenset(e["level_uids"]), e["kind"])] = e["sheet_uid"]

    items = []
    matched_keys = set()
    matched_uids = set()

    for row in plan:
        luid_set = frozenset(row["level_uids"])
        for kind, name, number in sheet_defs(row["base"], row["low_str"],
                                             row["high_str"], row["is_range"],
                                             row["prev_str"]):
            key = (luid_set, kind)

            sheet = _sheet_by_uid(doc, tracked_index.get(key))
            if sheet is not None:
                matched_keys.add(key)
            else:
                # adopt an existing sheet with this number only if it looks
                # like one of ours (migration / sheets made before tracking)
                candidate = by_num.get(number)
                if candidate is not None and looks_like_tool_sheet(candidate.Name):
                    sheet = candidate

            if sheet is None:
                clash = by_num.get(number)
                if clash is not None:
                    items.append({
                        "number": number, "new_name": name, "kind": kind,
                        "level_uids": list(luid_set),
                        "current_name": clash.Name, "current_number": number,
                        "status": "conflict", "sheet": None,
                    })
                else:
                    items.append({
                        "number": number, "new_name": name, "kind": kind,
                        "level_uids": list(luid_set),
                        "current_name": None, "current_number": None,
                        "status": "new", "sheet": None,
                    })
            else:
                cur_name, cur_num = sheet.Name, sheet.SheetNumber
                status = ("unchanged" if (cur_name == name and cur_num == number)
                          else "rename")
                matched_uids.add(sheet.UniqueId)
                items.append({
                    "number": number, "new_name": name, "kind": kind,
                    "level_uids": list(luid_set),
                    "current_name": cur_name, "current_number": cur_num,
                    "status": status, "sheet": sheet,
                })

    orphans = []
    for e in tracked:
        if (frozenset(e["level_uids"]), e["kind"]) in matched_keys:
            continue
        s = _sheet_by_uid(doc, e["sheet_uid"])
        if s is not None and s.UniqueId not in matched_uids:
            orphans.append({"sheet": s, "number": s.SheetNumber,
                            "name": s.Name, "kind": e["kind"]})
    return items, orphans


def _tracking_from_items(items):
    """Rebuild the sheet->level link list from items that resolved to a sheet.

    Skipped 'new' rows have no sheet and drop out; kept orphans are never in
    `items`, so they are untracked automatically.
    """
    tracking = []
    for it in items:
        s = it.get("sheet")
        if s is not None:
            tracking.append({"level_uids": it["level_uids"],
                             "kind": it["kind"], "sheet_uid": s.UniqueId})
    return tracking


def apply_changes(doc, titleblock_id, items, orphans):
    """Create / renumber / rename / delete the confirmed items.

    An item is applied when item['apply'] is True; an orphan is deleted when
    orphan['apply'] is True. 'unchanged' items are always tracked but never
    touched. 'conflict' items are reported and never touched.

    Returns (created, renamed, skipped, deleted, conflicts, tracking) where the
    first four are lists of (number, name), conflicts is a list of
    (number, foreign_name), and tracking is the rebuilt link list to persist.
    """
    created, renamed, skipped, deleted, conflicts = [], [], [], [], []

    t = Transaction(doc, "PEER - Create / Update level sheets")
    t.Start()
    try:
        sym = doc.GetElement(titleblock_id)
        if isinstance(sym, FamilySymbol) and not sym.IsActive:
            sym.Activate()
            doc.Regenerate()

        taken = set(existing_sheets_by_number(doc).keys())

        for orf in orphans:
            if orf.get("apply"):
                s = orf["sheet"]
                num, nm = s.SheetNumber, s.Name
                doc.Delete(s.Id)
                taken.discard(num)
                deleted.append((num, nm))

        for it in items:
            number, name, status = it["number"], it["new_name"], it["status"]

            if status == "conflict":
                conflicts.append((number, it.get("current_name") or u""))
                continue

            if status == "unchanged":
                continue  # left as-is, but still tracked

            if not it.get("apply"):
                skipped.append((number, name))
                continue

            if status == "new":
                if number in taken:
                    skipped.append((number, name))
                    it["sheet"] = None
                    continue
                sheet = ViewSheet.Create(doc, titleblock_id)
                sheet.SheetNumber = number
                sheet.Name = name
                taken.add(number)
                created.append((number, name))
                it["sheet"] = sheet
            else:  # rename / renumber
                sheet = it["sheet"]
                if sheet is None:
                    skipped.append((number, name))
                    continue
                cur_num = sheet.SheetNumber
                if cur_num != number:
                    if number in taken:
                        skipped.append((number, name))
                        continue
                    sheet.SheetNumber = number
                    taken.discard(cur_num)
                    taken.add(number)
                if sheet.Name != name:
                    sheet.Name = name
                renamed.append((number, name))

        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    return created, renamed, skipped, deleted, conflicts, _tracking_from_items(items)
