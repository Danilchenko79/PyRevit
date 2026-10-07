# PEER for Revit — Installation

You need: Revit and [pyRevit](https://github.com/pyrevitlabs/pyRevit/releases). Git is not required.

## Install (once)

**1.** Close Revit.

**2.** Download **[PEER_install.zip](https://github.com/Danilchenko79/PyRevit/raw/main/PEER_install.zip)** and open it.

![Download PEER_install.zip](docs/img/01-download.png)

*Figure 1 — Downloading PEER_install.zip in the browser*

**3.** Double-click **install.bat** inside the zip. If Windows shows a warning, click **More info → Run anyway**.

![Windows warning](docs/img/02-smartscreen.png)

*Figure 2 — Windows SmartScreen warning: More info → Run anyway*

**4.** Wait for `[OK]`, then press any key.

![Installation complete](docs/img/03-install-ok.png)

*Figure 3 — Installer window after a successful installation*

**5.** Start Revit — the **PEER** tab appears.

![PEER tab](docs/img/04-peer-tab.png)

*Figure 4 — PEER tab in the Revit ribbon*

## Updates

Updates install automatically every time Revit starts.
To update right now, click **pyRevit → Update**.

![Update button](docs/img/05-update.png)

*Figure 5 — Update button on the pyRevit tab*

## Troubleshooting

- **No PEER tab** — restart Revit.
- **Updates stopped** — close Revit and run `install.bat` again.
- **`Could not download` error** — check that github.com opens in your browser.

Do not edit files in the extension folder, or updates will stop working.

## Uninstall

Close Revit and delete the folder `%APPDATA%\pyRevit\Extensions\PEER.extension`.
