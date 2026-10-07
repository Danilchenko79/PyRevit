# PEER for Revit — Installation

**English** | [Русский](README.ru.md)

You need: Revit and [pyRevit](https://github.com/pyrevitlabs/pyRevit/releases). Git is not required.

## Install (once)

**1.** Close Revit.

**2.** Download **[install.bat](https://github.com/Danilchenko79/PyRevit/raw/main/install.bat)**.

![Download install.bat](docs/img/01-download.png)

**3.** Run the file. If Windows shows a warning: **More info → Run anyway**.

![Windows warning](docs/img/02-smartscreen.png)

**4.** Wait for `[OK]`, then press any key.

![Installation complete](docs/img/03-install-ok.png)

**5.** Start Revit — the **PEER** tab appears.

![PEER tab](docs/img/04-peer-tab.png)

## Updates

Updates install automatically every time Revit starts.
To update right now: **pyRevit → Update**.

![Update button](docs/img/05-update.png)

## Something wrong?

- **No PEER tab** — restart Revit.
- **Stopped updating** — close Revit and run `install.bat` again.
- **`Could not download` error** — check that github.com opens in your browser.

Do not edit files in the extension folder — updates will stop working.
