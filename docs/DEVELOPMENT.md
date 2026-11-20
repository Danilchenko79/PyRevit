# PEER: как идёт разработка и выпуск

Коротко: **правите в своей копии → пушите в `dev` → проверяете → сливаете в `main` → получают все.**
GitHub — мастерская (закрытая, только для разработчиков). Коллеги получают PEER с сервиса PEER, не с GitHub.

## Кто что делает

| Кто | Что у него стоит | Откуда приходят обновления |
|---|---|---|
| Разработчик | клон репозитория, ветка `dev` | `git pull` |
| Коллега | PEER, установленный по ссылке | сам, при запуске Revit |
| Кто пробует новое | PEER и PEER_dev по ссылкам (две вкладки) | сам, при запуске Revit |
| Админ | то же + окно **Keys** | — |

## Две ветки — две вкладки

| Ветка | Вкладка в Revit | Кто видит | Ссылка на установку |
|---|---|---|---|
| `dev` | **PEER_dev** | кто поставил для проб | `<сервис>/install?channel=beta` |
| `main` | **PEER** | все коллеги | `<сервис>/install` |

## Настройка разработчика (один раз)

1. Попросить у владельца доступ к репозиторию на GitHub (Settings → Collaborators).
2. Склонировать ветку `dev` в свою папку — **не** в `%APPDATA%\pyRevit\Extensions`:
   ```
   git clone -b dev https://github.com/Danilchenko79/PyRevit.git C:\PEER-work\PEER.extension
   ```
3. В Revit: pyRevit → Settings → Custom Extension Directories → добавить `C:\PEER-work` → Save and Reload.
4. Вкладка PEER → **Account** → войти своим ключом (нужен для библиотеки семейств).

На этом компьютере PEER по ссылке не ставить: будет две копии в одной вкладке, кнопки задвоятся.
Автообновление рабочую копию не трогает никогда.

## Обычный день

1. `git pull` — забрать чужие правки.
2. Править скрипты в своей папке. Изменение в скрипте видно сразу — просто нажать кнопку ещё раз.
   Новая кнопка или новая иконка появляются после pyRevit → Reload.
3. Проверить в Revit на тестовом проекте.
4. Коммит и пуш в `dev`.
   → вкладка **PEER_dev** обновится у тех, кто её поставил, при следующем запуске Revit.
5. Когда проверено — слить `dev` в `main` и запушить.
   → вкладка **PEER** обновится у всех коллег при следующем запуске Revit, с уведомлением «что изменилось».

Текст коммита видят коллеги в уведомлении: писать по-английски, одной понятной строкой
(`New button: Slab Tools`, `Rebar Tag: fixed the leader`).

## Как пуш превращается в обновление

GitHub сам запускает выпуск при пуше (`.github/workflows/release.yml`): собирает пакет из коммита и
кладёт на сервис. Пуш в `dev` → PEER_dev, пуш в `main` → PEER. Пуш, который не менял файлы PEER
(только документы, тесты), ничего не выпускает.

Автомату нужны два секрета репозитория: `PEER_URL` и `PEER_RELEASE_KEY`. **Пока они не заданы, автомат
ничего не делает** — выпуск делает админ командой:

```powershell
$rel = "lib\peer_library\tools\release\release.ps1"
powershell -ExecutionPolicy Bypass -File $rel -Target production -Do ext -Ref dev -Channel beta -Note "what changed"
powershell -ExecutionPolicy Bypass -File $rel -Target production -Do ext -Ref main -Channel stable -Note "what changed"
```

В пакет попадают только закоммиченные файлы.

## Если версия оказалась плохой

Быстро — откат: сервис хранит пять последних версий, админ возвращает вкладку PEER на предыдущую:

```powershell
powershell -ExecutionPolicy Bypass -File $rel -Target production                 # список версий
powershell -ExecutionPolicy Bypass -File $rel -Target production -Do promote -Version <версия> -Channel stable
```

Потом спокойно исправить в `dev` и выпустить заново.

## Новая кнопка — что обязательно

- Папка `PEER.tab\<Панель>.panel\<Имя>.pushbutton\` с `script.py` и `icon.png`.
- Вписать кнопку в `layout` файла `bundle.yaml` панели — иначе она не появится.
- `__doc__` только латиницей: на русских буквах pyRevit молча убирает кнопку с ленты.
- Первая строка кода после описания:
  ```python
  import peer_access; peer_access.require_key()
  ```
- Код — IronPython 2.7: без f-строк, `u'...'` для текста, изменения модели только в транзакции.
- Нужны семейства — брать через библиотеку, не из папки:
  ```python
  from peer_library import require
  res = require.families(doc, [u'PR_Family Name'])
  ```
- Путь к папке вкладки не писать руками (`PEER.tab`): в PEER_dev она называется иначе.
  Брать `version.tab_dir()` из `peer_library`.

## Чего не делать

- Не пушить в `main` непроверенное: это сразу уходит всем.
- Не править файлы в установленной копии (`%APPDATA%\pyRevit\Extensions\PEER.extension`):
  при следующем запуске Revit они вернутся к выпущенной версии.
- Не коммитить ключи, адреса сервиса и личные настройки. Они живут в `%APPDATA%\PEER\`.

## Люди и доступ (админ)

- Новый человек: дать ссылку на установку → он нажимает Account → Request access → в **Keys** нажать Approve.
- Ушёл: **Keys** → Revoke. Обновления прекращаются, панели скрываются.
- В **Keys** видно, у кого какая версия PEER.

## Где что лежит

| Что | Где |
|---|---|
| Кнопки | `PEER.tab\` |
| Общий код | `lib\` |
| Библиотека семейств, вход, обновление | `lib\peer_library\` (подробности — `lib\peer_library\README.md`) |
| Установщик | `installer\install.ps1` |
| Сервис (Cloudflare) | `service\` |
| Инструкция для коллег | `docs\LIBRARY.md` |
| Журнал обновления на компьютере | `%TEMP%\peer_revit_logs\peer_update.log` |
