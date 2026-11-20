# Сервис доступа PEER Library (Cloudflare)

Небольшой Worker перед хранилищем R2: проверяет личный ключ и роль, отдаёт файлы,
принимает публикации и предложения. Ключи, предложения и журнал действий лежат в D1.
Код — `src/worker.js`, схема — `schema.sql`. На компьютерах пользователей эта папка не
используется (pyRevit её игнорирует).

Стоимость для офиса на 10–20 человек — бесплатный тариф: R2 10 ГБ, исходящий трафик бесплатно,
Workers 100 000 запросов в день. Workers Paid — 5 $ в месяц на аккаунт, если упрёмся в лимиты.

## Развернуть с нуля (один раз, около 20 минут)
Нужны: аккаунт Cloudflare, Node.js (`node --version`). Команды выполнять в папке `service`.

1. Зарегистрироваться на dash.cloudflare.com. В разделе **R2** нажать «Enable / Purchase R2»
   (бесплатный тариф; Cloudflare может попросить привязать карту).
2. Войти из командной строки (откроется браузер):
   ```
   npx wrangler login
   ```
3. Создать хранилище и базу:
   ```
   npx wrangler r2 bucket create peer-library
   npx wrangler d1 create peer-library
   ```
   Команда `d1 create` печатает `database_id` — вставить его в `wrangler.toml` вместо
   `PASTE-DATABASE-ID-HERE`.
4. Создать таблицы и опубликовать сервис:
   ```
   npx wrangler d1 execute peer-library --remote --file=schema.sql
   npx wrangler deploy
   ```
   `deploy` печатает адрес вида `https://peer-library.<имя>.workers.dev`.
5. Первый ключ админа:
   ```
   node scripts/first_key.mjs "Дима"
   ```
   Скрипт печатает ключ (один раз — сохранить в менеджер паролей) и команду
   `npx wrangler d1 execute ... --command "INSERT ..."` — выполнить её.
6. В Revit: Shift+Click по **Library** → «Library service address» → вставить адрес;
   затем **Library** → вставить ключ. После pyRevit → Reload появятся кнопки админа
   (Publish, Inbox, Keys).
7. Загрузить семейства: Revit **2024** → Publish → «Publish a sorted folder» →
   `Desktop\PEER-Library-Source`.

## Раздать коллегам
1. Адрес сервиса положить в `lib/peer_library/settings.json`:
   ```json
   {"backend": "http", "url": "https://peer-library.<имя>.workers.dev"}
   ```
   и выпустить в `main` (автообновление PEER). Адрес не секрет — без ключа сервис ничего не отдаёт.
2. Доступ: человек жмёт **Library** → «Request access» (имя + заметка). У админа в **Keys**
   появляется заявка → «Approve as user» — при следующем нажатии Library человек входит сам,
   ключ никто не пересылает. Можно и вручную: Keys → «Create key», отправить лично.
   Ушёл человек — «Revoke selected key», ключ перестаёт работать сразу.
3. Пока адреса сервиса в настройках нет, панель Library у коллег скрыта.

## Проверочный и боевой сервис
В `wrangler.toml` два окружения с отдельными Worker, R2 и D1 — данные не пересекаются:

| | Worker | R2 | D1 | Команды |
|---|---|---|---|---|
| проверочный (песочница) | `peer-library` | `peer-library` | `peer-library` | `npx wrangler deploy` |
| боевой (офис) | `peer` | `peer-prod` | `peer-prod` | `npx wrangler deploy --env production` |

Боевой создаётся один раз (команды — в комментарии над `[env.production]`): bucket, база, `database_id` в
`wrangler.toml`, схема, deploy, первый ключ админа. После этого адрес боевого сервиса кладётся в
`lib/peer_library/settings.json` (`{"backend": "http", "url": "https://peer.<аккаунт>.workers.dev"}`) и в
`installer/install.bat` (`PEER_URL`). Свой компьютер на проверочном сервисе — тот же адрес в
`%APPDATA%\PEER\library.json` (он сильнее файла из репозитория). Ключи у двух сервисов разные.

Боевой создан 20.11.2026: `https://peer.<аккаунт>.workers.dev` (Worker `peer`, R2 `peer-prod`, D1 `peer-prod`;
точный адрес — у админа, в репозиторий не пишется, пока в нём личное имя аккаунта).
Первый ключ админа сделан на компьютере автора и лежит только зашифрованным (DPAPI) в
`%APPDATA%\PEER\library_key_production.bin` — нигде не печатался. Перейти своим компьютером на боевой: этот файл
положить вместо `library_key.bin` (старый сохранить) и адрес — в `library.json`.

## Раздача самого PEER и шаблона (`/release/...`)
Пакет PEER (`ext`), открытый загрузчик (`boot`: Account + обновление, без инструментов; читается без ключа —
`GET /boot/manifest`, `/boot/file/<v>`) и шаблон проекта (`template`) лежат в R2 под `PEER-Releases/<product>/`. Версия загружается
один раз и не меняется; каналы `stable` и `beta` — указатели на версию, откат = перевести указатель на старую.
Хранятся последние 5 версий и те, на которые указывает канал. Скачать может любой действующий ключ, загрузить
и переключить — только админ. Команды — `lib/peer_library/tools/release/release.ps1`.

База, созданная до 20.11.2026, перед деплоем этой версии сервиса требует одной команды (колонка версии PEER у ключа):
```
npx wrangler d1 execute peer-library --remote --file=migrations/001_key_version.sql
npx wrangler deploy
```
Порядок важен: сначала миграция, потом deploy (иначе проверка ключа падает с ошибкой 500).

## Резервная копия
- Файлы библиотеки:
  `powershell -ExecutionPolicy Bypass -File lib\peer_library\tools\backup.ps1 -Folder D:\Backup\PEER`
  (ключ админа берётся из PEER этого пользователя Windows; проверяет SHA-1 каждого файла).
- Ключи, предложения, журнал: `npx wrangler d1 export peer-library --remote --output=D:\Backup\PEER\d1.sql`

## Проверка без Cloudflare
```
node --test test                     # 24 теста сервиса (R2 и D1 подменены, node:sqlite)
node test/dev_server.mjs 8787        # локальная копия сервиса, печатает тестовые ключи
py -3 -m unittest discover -s ..\lib\peer_library\tests   # в т.ч. клиент против dev_server
```

## Безопасность
- Сервер хранит только SHA-256 ключа; сам ключ показывается один раз.
- У пользователя ключ хранится зашифрованным DPAPI (`%APPDATA%\PEER\library_key.bin`),
  в логи не пишется.
- Роль проверяет сервер на каждом запросе: `user` — читать и предлагать, `admin` — ещё публиковать,
  отклонять, выдавать и отзывать ключи.
- Журнал действий (кто что скачал, опубликовал, предложил) — `GET /audit` (админ).
- Секретов в репозитории нет: `wrangler.toml` содержит только имена и id базы.
