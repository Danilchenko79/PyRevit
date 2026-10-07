# PEER — расширение pyRevit

Вкладка **PEER** в Revit: листы, армирование, колонны, стены, сваи, анализ, документация.
Ставится из этого репозитория и **обновляется само** при каждом запуске Revit.

---

## Для пользователей: установка

**Нужно:** Revit + установленный [pyRevit](https://github.com/pyrevitlabs/pyRevit/releases)
(проверено на pyRevit 5.2). Git ставить **не нужно** — у pyRevit свой встроенный.
Нужен доступ к github.com (если сайт не открывается в браузере — к IT, прокси).

### Способ 1 — файлом (рекомендуется)
1. Закрыть Revit.
2. Скачать [`install.bat`](https://github.com/Danilchenko79/PyRevit/raw/main/install.bat)
   (или взять у автора / с общего диска) и запустить двойным щелчком.
3. Дождаться `[OK]`, запустить Revit — появится вкладка **PEER**.

Что делает `install.bat`:
- клонирует репозиторий (ветка `main`) в `%APPDATA%\pyRevit\Extensions\PEER.extension`;
- включает в pyRevit «проверять обновления» и «обновлять автоматически при запуске»;
- если PEER уже стоит — просто обновляет его. Повторный запуск безопасен.

### Способ 2 — через окно pyRevit Extensions
Один раз в командной строке:
```
pyrevit extensions sources add https://raw.githubusercontent.com/Danilchenko79/PyRevit/main/extensions.json
```
Затем в Revit: **pyRevit → Extensions** → в списке **PEER** → **Install** → перезапустить Revit.
Автообновление включить: **pyRevit → Settings → Core Settings** → галочки
*Check for updates at startup* и *Automatically update to latest at startup* → Save Settings.

### Способ 3 — одной командой
```
pyrevit extend ui PEER https://github.com/Danilchenko79/PyRevit.git --branch=main
pyrevit configs autoupdate enable
```

### Обновления
- **Автоматически:** при каждом запуске Revit pyRevit скачивает последнюю версию.
- **Вручную:** кнопка **pyRevit → Update** (или `pyrevit extensions update PEER`).
- Новые кнопки появляются после перезапуска Revit или **pyRevit → Reload**.

### Если что-то не так
| Проблема | Что делать |
|---|---|
| Вкладки PEER нет | Перезапустить Revit; проверить, что есть папка `%APPDATA%\pyRevit\Extensions\PEER.extension` |
| Перестало обновляться | Скорее всего, у вас изменены файлы внутри папки. Закрыть Revit, удалить папку `PEER.extension`, запустить `install.bat` заново |
| `Could not download from GitHub` | Нет доступа к github.com — проверить в браузере, обратиться к IT |
| Удалить расширение | `pyrevit extensions delete PEER` (или удалить папку `PEER.extension`) |

**Файлы в папке `PEER.extension` у себя не править** — иначе обновление не сможет их заменить.

---

## Для автора: как это устроено и как выпускать обновления

### Зачем так
- У пользователя расширение — это **git-клон** ветки `main`. pyRevit при запуске Revit делает
  `git pull` всех таких клонов (настройка `autoupdate`). Поэтому всё, что попало в `main` на GitHub,
  у людей появится при следующем запуске Revit — без рассылки файлов.
- Репозиторий публичный — логин и токен у пользователей не нужны.

### Две ветки
| Ветка | Кто видит | Для чего |
|---|---|---|
| `dev` | только автор | разработка, недоделанное, эксперименты |
| `main` | **все пользователи** | только проверенное |

У автора рабочая копия — `Desktop\Plagin PEER v2.0\PyRevitV2.extension` (в ней ветка `dev`,
она и загружается в его Revit). **Сам `install.bat` у себя не запускать** — будет две вкладки PEER.

### Выпуск новой версии
```
git checkout dev
git add -A
git commit -m "Что сделано"
git push                      # dev на GitHub — резервная копия, пользователи не получают

# проверил в Revit — выпускаем:
git checkout main
git pull
git merge dev
git push                      # с этого момента у всех обновится при запуске Revit
git tag v2.1 && git push --tags   # необязательно: метка версии для отката
git checkout dev
```

### Правила, чтобы у людей не ломалось
- В `main` — только то, что проверено в Revit. Каждый push в `main` сразу уходит всем.
- Новая кнопка или панель → вписать в `layout` в `bundle.yaml` вкладки или панели, иначе не появится.
- Описание кнопки (`__doc__`) — ASCII, иначе pyRevit молча уберёт кнопку.
- Никаких путей к своему компьютеру (`C:\Users\...`, `Desktop`) — только относительно папки
  расширения (`os.path.dirname(__file__)`) или `%TEMP%` / `%APPDATA%`.
- Не класть в репозиторий тяжёлое и личное: `.venv`, бэкапы, рабочие заметки (`.gitignore`).

### Откат, если выпустил сломанное
```
git checkout main
git revert HEAD               # отменяет последний коммит новым коммитом
git push                      # у людей при следующем запуске вернётся прежняя версия
```
(`git reset` + `push --force` не использовать — у пользователей клоны могут перестать обновляться.)

### Файлы установки в этом репозитории
| Файл | Зачем |
|---|---|
| `install.bat` | установка/обновление у пользователя + включение автообновления |
| `extensions.json` | каталог для окна pyRevit → Extensions (способ 2) |
| `README.md` | эта инструкция (видна на странице репозитория) |

pyRevit эти файлы игнорирует — на ленту они не влияют.
