# PEER Family Library

Company Revit families in one place: search, previews, versions, one-click load and update.
The **Library** panel on the **PEER** tab appears once the library is set up for the office.

## First start

1. Press **Library**.
2. Have a key from an admin? Paste it (starts with `peer_`) and press **Sign in**.
   No key yet? Fill in **Request access** (your name, a note) and press it. When an admin
   approves, press **Library** again - you are signed in automatically.
3. The key is stored encrypted for your Windows user on this computer only. Without internet the
   families you downloaded before keep working for 14 days.

## Find and load a family

| Do | How |
|---|---|
| Search | type in the top box: name, ID, tag, Revit category, description or a type name. Spaces and dashes do not matter (`he 200 a` = `HE200A`); Russian and Hebrew words work too (`колонна`, `כלונס`). Best matches (in the name) come first; **Enter** / **↓** jumps to the first tile |
| Narrow down | groups on the left, Revit category, **With type catalog**, sort by name / newest / popular |
| Keep at hand | **☆ Add to favorites**; **Recently loaded** fills itself |
| Load | select a tile, **Load** (or **Enter**); **Load and place** (or double click, **Shift+Enter**) starts placing in the view |
| Types from a catalog | tick the types you need (the list shows key sizes), then Load |
| Several projects open | tick **Also load into the other open projects** |
| A whole kit | pick a collection (▦) on the left, **Load collection** |

Each tile shows the family's status in the open project: **Not in project**, **Up to date (vN)**,
**Project vN → library vM** (an update is available), **In project, no version**.
Updating keeps the parameter values changed in the project (catalog types too), unless you tick
**Overwrite parameter values in the project** - then the library values come back, also for a
family that is already up to date.

## Keep a project up to date

- **Need update** group → **Update all outdated**.
- **This project** tab: every family of the project with its library status. Select rows →
  **Update selected from library**. A family that is not in the library → **Propose selected to library**.
- When you open a project with outdated library families, Windows shows a notification.
- At Revit start you get a notification about new and updated families (every 6 hours at most).

## Ask for something

- **Request a family…** (bottom right): describe what you need.
- **Report a problem…** (in the family card): what is wrong with it.
- **Propose family**: send a family file (from disk, the selected element, or the family editor).
  Automatic checks are shown but do not block sending.
- Answers come in **Library → My proposals**.

## Admins (2–3 people)

Admin buttons are visible only with an admin key: **Publish**, **Inbox**, **Keys**.

| Task | Where |
|---|---|
| Put a family into the library | **Publish** (Revit 2024 only): checks, `PEER_Version` in every type, preview, compact save |
| New version | Publish → *New version of an existing family* (or **New version…** in the card); a note is required |
| Undo a bad version | card → History → **restore** next to an older version: Publish opens with that file and publishes it as the next version (the last 5 versions are kept) |
| Import a sorted folder | Publish → **Publish a sorted folder…** (`<group>/<ID>.rfa`) |
| Names, tags, descriptions of many families | Publish → **Info to Excel…**, edit, **Info from Excel…** (no new versions) |
| One family's info | card → **Edit info…** |
| Collections (kits) | card → **Add to collection…**; in a collection → **Remove from this collection** |
| Retire a family | card → **Deprecate…** (projects keep it, the window hides it) |
| Proposals, requests, problems | **Inbox**: open in the editor, publish, mark done, reject with a comment |
| People | **Keys**: approve access requests, create a key, revoke a key (works at once) |

Rules: the ID = file name = family name in Revit and never changes; the library format is
Revit 2024; publish only from Revit 2024.

Service setup, costs and backups: `service/README.md`. Developer notes: `lib/peer_library/README.md`.
