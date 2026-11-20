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
| What goes with it | **Also load** lists the families that belong with this one (a pile → its tag). Ticked ones are loaded with it; a family the project already has is only named and never replaced |
| A whole kit | pick a collection (▦) on the left, **Load collection** |

Each tile shows the family's status in the open project: **Not in project**, **Up to date (vN)**,
**Project vN → library vM** (an update is available), **In project, no version**.
Updating keeps the parameter values changed in the project (catalog types too), unless you tick
**Overwrite parameter values in the project** - then the library values come back, also for a
family that is already up to date.

### Before a family in the project is replaced

A family with the same name may already be in the project - an older library version, or somebody's
own family that only has the same name. Before **Update** replaces it, the library checks what the
update would do **in this project** (a trial load that is undone at once):

- parameters of the project family that the library family does not have, or has as another shared
  parameter (other GUID), another unit, type ↔ instance - with how many elements lose their values;
- dimensions and tags Revit would delete, shared parameters whose name the project already uses with
  another GUID, nested shared families that would be replaced in the whole project.

Nothing breaks → it updates at once. Otherwise a window shows the two pictures and the list:
**Update** / **Update anyway** (replaces and loses what is marked *Breaks*; Ctrl+Z undoes it),
**Load next to it** (the project family keeps its elements and values under the name
`<name> (project)`, the library one is added beside it) or **Cancel**. A family that did not come
from the library always gets this window. Right click on a tile → **Check against this project…**
shows it without loading. **Update all**, **Load collection** and **Update selected** leave such
families alone and list them at the end.

## Keep a project up to date

- **Need update** group → **Update all outdated**.
- **This project** tab: every family of the project with its library status. Select rows →
  **Update selected from library**. A family that is not in the library → **Propose selected to library**.
- When you open a project with outdated library families, Windows shows a notification.
- At Revit start you get a notification about new and updated families (every 6 hours at most).

## Buttons that need families

PEER buttons that use library families take them from the library themselves: a family the
project does not have yet is downloaded and loaded when the button runs (your library sign-in is
used; offline - the copy downloaded before). A family already in the project is used as it is -
a button never replaces it, even when the library has a newer version; it only tells you, and you
update it in **Library → This project**.

## Ask for something

- **Request a family…** (bottom right): describe what you need.
- **Report a problem…** (in the family card): what is wrong with it.
- **Propose family**: send a family file (from disk, the selected element, or the family editor).
  Automatic checks are shown but do not block sending.
- Answers come in **Library → My proposals**.

## Check a family (making or fixing one)

**Check family** changes nothing and works on the open family (family editor), on the family of the
selected element or type in a project, or - with nothing selected - on a whole folder of `.rfa`
(list saved as CSV in `%LOCALAPPDATA%\PEER\checks`). It reports:

- shared parameters against the company shared parameter file (`PR_FOPv4.txt` - the file set in
  Revit, or `shared_params` in the library settings): the same name with another GUID breaks
  schedules, tags and filters in projects; family parameters that should be the company's shared ones;
- types that do not regenerate; names that differ only in case or spaces; parameters nothing uses;
  nested shared families named like library families.

**Publish** runs the same checks: another GUID blocks publishing, the rest are warnings.

### Put a family in order

In the family editor the check window has two more buttons (Save the family afterwards; Ctrl+Z
undoes the changes):

- **Fix automatically (N)** - shared parameters with old names (`ADSK_…`) get the company name
  (same GUID, so projects keep their values); family parameters that the company file has as shared
  ones become those shared parameters. Formulas, dimension labels and visibility links stay.
- **Change a parameter…** - pick one: replace it with any company shared parameter of the same kind,
  make a shared parameter a family one, rename or delete it.

A folder: after the folder check press **Fix copies…** and choose another folder - fixed copies are
saved there with the same sub-folders and a list of changes (`_family_fix.csv`); the checked files
stay as they are. A family selected in a project is only checked - open it (Edit Family) to fix it.

## Your account (one key for PEER)

**PEER → Account** shows who is signed in on this computer, the state of your key and the installed
PEER version. The same personal key opens the family library, brings PEER updates and - when the
office turns the lock on - the PEER buttons themselves.

- **Sign in / request access…**: paste the key from a PEER admin, or send a request and press
  Sign in again after an admin approves it.
- **Check now**: asks the service whether the key is still valid. **Sign out** removes the key from
  this computer.
- Without internet PEER keeps working for 14 days after the last check.
- Install on a new computer: run `install.bat` from the PEER site - it asks for the key (or sends the
  access request) and downloads PEER. After that PEER updates itself when Revit starts.

## New project from the company template

**PEER → New project** creates a project from **PR_Template Concrete** - always the released
version: PEER keeps the template file on your computer up to date by itself (a notification says
what changed). You only choose where to save the project. Revit's own **New…** can use the same
file: `%LOCALAPPDATA%\PEER\Templates\PR_Template Concrete.rte`.

A new template version changes new projects only; projects that are already started stay as they are.

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
| What is loaded together | card → **Edit info…** → *Load together with this family* (IDs, comma separated) |
| Collections (kits) | card → **Add to collection…**; in a collection → **Remove from this collection** |
| Retire a family | card → **Deprecate…** (projects keep it, the window hides it) |
| Proposals, requests, problems | **Inbox**: open in the editor, publish, mark done, reject with a comment |
| People | **Keys**: approve access requests, create a key, revoke a key (works at once); the list shows which PEER version each person runs |
| Release the template | save it as `.rte`, then `release.ps1 -Do template -File … -Note "what changed"` → **beta** → **stable** |
| Release PEER | `release.ps1` (developer README): package → **beta** → **stable**; roll back by pointing a channel at an older version |

Rules: the ID = file name = family name in Revit and never changes; the library format is
Revit 2024; publish only from Revit 2024.

Service setup, costs and backups: `service/README.md`. Developer notes: `lib/peer_library/README.md`.
