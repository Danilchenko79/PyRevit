# PEER Contact — setting up the receiver

One-time setup by the head of the group, about 15 minutes. After it, the
**Contact** button on the PEER tab sends requests into a Google Sheet from
any computer with internet — office or home, no network drive.

```
Contact (Revit) ──HTTPS POST──▶ Apps Script web app ──▶ Google Sheet, sheet "Requests"
      │                                                  
      └─ no internet → %APPDATA%\PEER\outbox → sent on the next Revit start
```

## 1. Table and receiver

1. Use a work Google account, not a personal one: the table and the
   receiver belong to it.
2. Create an empty Google Sheet, e.g. **PEER Feedback**.
3. In the sheet: **Extensions → Apps Script**. Delete the sample code and
   paste the whole of [`receiver/Code.gs`](receiver/Code.gs). Save.
4. In the editor pick the function **setup** and click **Run**. Allow the
   access Google asks for (the script edits only this sheet).
   `setup` creates the **Requests** sheet with its columns, the **Status**
   dropdown and a random key. The key is printed in **Execution log**:
   `PEER_KEY = 3f9c…`. It is stored in **Project Settings → Script
   Properties → PEER_KEY**.
5. **Deploy → New deployment → Web app**:
   - Execute as: **Me**
   - Who has access: **Anyone**

   Click **Deploy** and copy the **Web app URL** (ends with `/exec`).

"Anyone" is needed because Revit sends without a Google login. The URL
alone is not enough to write: every request must carry the key. The
receiver never returns the table's contents.

If your Google Workspace admin does not allow "Anyone", ask them to allow it
for this one script, or create the table under a separate Google account.

## 2. Check it from a browser

Open the Web app URL. The page must say `PEER receiver is running.`

## 3. Give PEER the address and the key

Two options — pick one.

**A. On each computer (recommended while the repo is public).**
Shift+Click on **Contact** → **Receiver address and key** → paste the URL,
then the key. The check runs right away and must say
`Receiver answered in … ms`. Stored in `%APPDATA%\PEER\feedback.json`, not
touched by PEER updates.

**B. For everyone at once, through the repo.** Put both values into
`lib/peer_feedback/settings.json` and push to `main`; every computer gets
them with the next update. The repo `Danilchenko79/PyRevit` is **public**:
anyone can read the key there and add junk rows (nothing else). If you go
this way, make the repo private first — then `install.bat` and the
auto-update need GitHub credentials on every computer.

The local file (A) wins over the repo file (B) key by key.

## 4. First check (stage 1 gate)

On **one remote computer** (home, no network drive):

1. Shift+Click **Contact** → **Check connection** → `Receiver answered`.
2. Click **Contact**, send a test request → a new row on **Requests**
   within a minute.
3. Turn Wi‑Fi off, send another request → "saved on this computer".
   Turn Wi‑Fi on, restart Revit (or Shift+Click → **Send queued requests
   now**) → the row appears, once.

Then repeat step 2 on one computer with Revit 2023–2024 and one with
Revit 2025+.

## Update for "My requests" (once, after stage 2)

The receiver deployed in stage 1 does not report statuses yet. Paste the
new [`receiver/Code.gs`](receiver/Code.gs) over the old code, save, then
**Deploy → Manage deployments → Edit (pencil) → Version: New version →
Deploy**. The URL and the key stay the same. Until then **My Requests**
shows "The receiver does not report statuses yet".

## Button usage — sheets "Usage" and "Buttons" (stage 3)

Also needs the new receiver version (same steps as above). After pasting
the new code run **setup** once more: it adds the two sheets and keeps
the key.

- **Usage** — one row per day, person, computer and button: how many runs,
  how many failed, the name of the last error. Sent on the next Revit
  start after the day is over (never the current day), once.
- **Buttons** — every PEER button, added automatically. Fill in
  **Minutes saved per run** by hand: how long the same work takes without
  the button. The weekly summary multiplies it by the runs.

Sent: date, Revit user, computer name, button, counts, error name,
Revit and PEER versions. No project names, no texts, no paths.

## Pictures in requests

People can paste a screenshot into **Contact** (Ctrl+V), drop image files
on the window or add them with a button — up to 5, each shrunk to 1600 px
and saved as JPEG. The receiver puts them in the Drive folder **PEER
Feedback pictures** (made by `setup`, its id is in Script Property
`ATTACH_FOLDER_ID`) and writes their links in the **Pictures** column.
The folder is yours and not shared: only you open the links.

After pasting the new `Code.gs`: run **setup** once (Google asks for the
Drive permission), then deploy a new version. Until then the request still
arrives, with "(pictures not saved: …)" in **Pictures**.

## Weekly summary (stage 4)

Every Monday at 07:00 the receiver writes the **Summary** sheet and
e-mails it to you. Turn it on once:

1. Paste the new `Code.gs`, save, deploy a new version (as above).
2. In the editor pick **setupWeeklySummary** and click **Run**. Google
   asks for two more permissions: triggers and sending e-mail as you.
   A first summary is sent right away.
3. Optional: another address or several — Script Property
   `SUMMARY_EMAIL`, comma separated.
4. Check **Project Settings → Time zone** (Asia/Jerusalem): "07:00" is in it.

What is in it (numbers for the group, no ranking of people):

| Block | How it is counted |
| --- | --- |
| 1. Requests this week | count, people, by topic |
| 2. Top 3 to automate | open Automation / Routine / Improve requests; hours lost a week = how often (day 5, week 1, rarely 0.25 a week) × time (3 / 15 / 45 min); "Improve" requests on the same button are one line |
| 3. Bugs this week | by button; urgent = 2+ people or 3+ reports |
| 4. Usage, 30 days | top 10 buttons by runs; buttons with no runs |
| 5. Errors without a bug report | buttons that failed this week, no bug sent |
| 6. Signals | requests naming an existing button, how-to questions, template and standard gaps |
| 7. Time saved | successful runs × "Minutes saved per run" |
| 8. Status | counts by status; New for more than 7 days |

Similar requests worded differently are not merged: that needs reading
the texts. For that, download **Requests** as CSV (**File → Download →
CSV**) and give it to Claude with the summary.

## Bug reports with the error text

pyRevit catches script errors itself, so PEER reads them from pyRevit's
file telemetry: on every Revit start PEER switches it on and points it to
`%APPDATA%\PEER\telemetry` (a folder already set in pyRevit settings is
kept). pyRevit writes one record per button run there; files older than
90 days are deleted.

Nothing from these files is sent by itself. When a PEER button fails,
**Contact** opens on **Bug** with that error picked (within 15 minutes;
older errors of the last 7 days are in the list) — the full error text
goes with the report only when the person clicks **Send**.

## Working with the table

- **Status** — pick from the dropdown: New, Accepted, In progress, Done,
  Rejected. **Status changed** fills in by itself.
- **Comment for the author** — a short note; the author sees it in
  **My Requests** together with the status.
- Do not reorder or rename the columns: the receiver writes by position.
  Add your own columns to the right of **Status changed**.

## Changing the key

In the Apps Script editor run **rotateKey**, copy the new key from the log
and give it to PEER (option A or B). Requests sent with the old key stay in
each computer's outbox and go out once the new key is set.

## Updating the receiver code

Paste the new `Code.gs`, save, then **Deploy → Manage deployments → Edit
(pencil) → Version: New version → Deploy**. The URL stays the same. A new
deployment (instead of a new version) gets a new URL.

## Where things are on a user's computer

| What | Where |
| --- | --- |
| Address, key | `%APPDATA%\PEER\feedback.json` |
| Unsent requests | `%APPDATA%\PEER\outbox\*.json` |
| Sent requests and last known status | `%APPDATA%\PEER\sent.json` |
| Button runs (pyRevit telemetry) | `%APPDATA%\PEER\telemetry\*.json` |
| Send log | `%TEMP%\peer_revit_logs\peer_feedback.log` |
