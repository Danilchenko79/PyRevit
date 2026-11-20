# PEER Library — библиотека семейств (для разработчика)

План и ТЗ: документ «Библиотека семейств PEER — план разработки» (claude.ai artifact KMy4TRiUTRSWCxoKmN3dAu).
Инструкция для пользователей и админов: `docs/LIBRARY.md`. Сервис: `service/README.md`.

## Кнопки (PEER.tab → Library, все — smartbutton)
| Кнопка | Кто | Видна |
|---|---|---|
| Library | все | где настроена библиотека (`config.panel_visible`) |
| Propose family | все | там же |
| Check family | все | где настроена библиотека |
| Publish, Inbox | админ | роль `admin` |
| Keys | админ | роль `admin` и сервис (`backend: http`) |

Без настройки `startup.py` прячет и саму панель — ветку можно вливать до раздачи адреса.

## Модули
| Без Revit (тесты на CPython) | В Revit (IronPython) |
|---|---|
| `config` настройки, `jsonio`, `log`, `strings` (все тексты UI) | `revit_family` открыть копию, проверки, `PEER_Version` формулой, превью, compact |
| `index` карточка, индекс, changelog | `publish` одно семейство / папка (имена+теги из `importmeta`) |
| `checks_file` маска, размер, версия Revit (2024) | `loader` статусы, LoadFamily / LoadFamilySymbol, размещение, список семейств проекта |
| `rfa_info` версия без Revit, sha1 | `session` вход: ключ / заявка на доступ |
| `cache` локальная копия `<group>/<ID>.rfa`, офлайн 14 дней | `ui_library` окно (группы, избранное, недавние, популярное, коллекции, фильтры, сортировка, каталоги, «Этот проект», админ-действия) |
| `backend_base` интерфейс; `backend_local` папка; `backend_http` сервис | `ui_publish` (+ Excel), `ui_inbox`, `ui_propose`, `ui_dialogs` |
| `catalog` каталог типов; `cards_csv` карточки ↔ Excel; `importmeta` имена/теги | `notify` уведомление при старте; `project_check` + `hooks/doc-opened.py` |
| `keystore` ключ и заявка (DPAPI); `userprefs` избранное/недавние; `search` поиск (слитно, RU/HE-синонимы, порядок) | `ui_common` цвета/чипы (без синего, статус всегда с подписью) |
| `family_diff` что сломает замена семейства, проверки по ФОП, имена, типы (правила и тексты) | `family_sig` состав семейства данными; `load_check` проверка перед заменой (сравнение + пробная загрузка с откатом), `rename_aside`; `family_check` кнопка Check family / папка / Publish; `ui_check` окно отчёта |

## Настройки
`%APPDATA%\PEER\library.json` поверх `lib/peer_library/settings.json` (для офиса положить сюда адрес сервиса):
```json
{"backend": "http", "url": "https://peer-library.<имя>.workers.dev"}
```
Ключ — `%APPDATA%\PEER\library_key.bin` (DPAPI), избранное — `library_user.json`, кэш — `%LOCALAPPDATA%\PEER\Library`,
лог — `%APPDATA%\PEER\library.log`. Вариант «папка» (`backend: local`, `root`) — для пробы без сервиса, роль из настроек.

## Формат
Revit **2024**, публиковать только из 2024. ID = имя файла = имя семейства в Revit, не меняется.
Карточка — `index.CARD_DEFAULTS` (+ `types` для поиска по типам, `files` — адреса версий в сервисе).
`/index` и `/changelog` отдаются с ETag: клиент хранит `index.json.etag` в кэше и при «304» берёт копию;
превью окно качает в фоновом потоке (сначала видимые), WPF трогает только поток окна.
`PEER_Version` — параметр типа формулой `"N"` (одно значение на все типы).

## Проверки
```
py -3 -m unittest discover -s lib/peer_library/tests     # 58 тестов, в т.ч. клиент ↔ сервис (node)
node --test service/test                                  # 17 тестов сервиса
```
Синтаксис IronPython и XAML — `ipy`-компиляция и `XamlReader` (см. историю сессии 20.11.2026).

Окна без Revit — настоящий код окон под IronPython pyRevit, Revit и `pyrevit.forms` заглушены, данные с живого
сервиса (ваш ключ, только чтение), окна вне экрана, картинки в папку:
```
powershell -STA -ExecutionPolicy Bypass -File lib\peer_library\tools\ui_preview\run.ps1 [-Script library|windows] [-Out папка]
```
`library.py` — библиотека (поиск, детали, каталог, «Need update», «This project», «What's new»), `windows.py` —
Keys, Inbox, Publish, Propose, вход, запрос, правка карточки. Загрузку в проект так не проверить — только в Revit.

Загрузка в проект — проверено в Revit 2024 через коннектор (временный проект, 20.11.2026), `loader.load_family`:
- выходной параметр `IFamilyLoadOptions` — `.Value` (`LAST_OPTIONS.used == 'value'`);
- файл, совпадающий с семейством в проекте, Revit пропускает (`OnFamilyFound` не зовётся, `SaveAs` без правки не
  помогает) → «Overwrite» при той же версии загружает копию с пустой правкой (параметр добавлен и удалён) из
  `%LOCALAPPDATA%\Temp\peer_lib_touch\<ID>.rfa`;
- типы каталога (`LoadFamilySymbol`) всегда получают значения каталога → без «Overwrite» значения типов читаются
  до загрузки и пишутся обратно в той же транзакции; целиком (`LoadFamily`) каталог грузит ВСЕ типы — окно так не делает;
- обновление v1 → v2: значения проекта сохраняются, `PEER_Version` (формула) становится 2; `project_check` /
  `on_doc_opened` находит устаревшее (уведомление в проверке заглушено).

Замена «чужого» семейства с тем же именем (проверено там же):
- постороннее семейство (своё, старая версия, исходник из «Families Dima») Revit заменяет молча: значения
  параметров, которых нет в библиотечном, пропадают, общий параметр с другим GUID — тоже;
- размер к опорной плоскости, которой нет в новом семействе = ошибка «dimension references … invalid» →
  `Guard` откатывает всю загрузку; `delete_broken=True` («Update anyway») разрешает Revit удалить такие размеры;
  размеры к центральным плоскостям шаблона переживают замену;
- особый случай: семейство-копия другого библиотечного (одна «родословная» файла) Revit не заменил вообще —
  `LoadFamily` вернул False без `OnFamilyFound`, `fd.LoadFamily` бросил «Family loading failed»;
- поэтому перед заменой `load_check.check`: сравнение составов (`EditFamily` проекта ↔ файл) + пробная загрузка в
  `TransactionGroup` с откатом (удалённое — через `DocumentChanged`, считаются размеры/марки/экземпляры и видимые
  зависимые элементы; сотни скрытых внутренних элементов семейства Revit пересоздаёт всегда — не в счёт);
  ~1,5–2 с на семейство. После отката старые Python-ссылки на элементы недействительны — брать по id;
- семейство с предупреждениями, открытое в фоне, показывает модальное окно «Warnings» и вешает скрипт —
  `revit_family.open_quiet` / `QuietOpen` (обработчик `FailuresProcessing` снимает предупреждения).

## Инструменты (`tools/`)
- `sort_source.py <сырые> <папка>` — раскладка по группам, журнал `_sort_log.csv`.
- `backfill_plan.py` + `apply_plan.ps1` — имена/теги/типы для уже опубликованных карточек (без новых версий).
- `backup.ps1 -Folder D:\Backup\PEER` — резервная копия библиотеки (.NET, проверка SHA-1).
