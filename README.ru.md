# PEER для Revit — установка

[English](README.md) | **Русский**

Нужно: Revit и [pyRevit](https://github.com/pyrevitlabs/pyRevit/releases). Git не нужен.

## Установка (один раз)

**1.** Закройте Revit.

**2.** Скачайте **[install.bat](https://github.com/Danilchenko79/PyRevit/raw/main/install.bat)**.

![Скачивание install.bat](docs/img/01-download.png)

**3.** Запустите файл. Если Windows предупредит: **Подробнее → Выполнить в любом случае**.

![Предупреждение Windows](docs/img/02-smartscreen.png)

**4.** Дождитесь надписи `[OK]` и нажмите любую клавишу.

![Установка завершена](docs/img/03-install-ok.png)

**5.** Запустите Revit — появится вкладка **PEER**.

![Вкладка PEER](docs/img/04-peer-tab.png)

## Обновления

Обновляется само при каждом запуске Revit.
Обновить сразу: **pyRevit → Update**.

![Кнопка Update](docs/img/05-update.png)

## Что-то не работает?

- **Нет вкладки PEER** — перезапустите Revit.
- **Перестало обновляться** — закройте Revit и запустите `install.bat` ещё раз.
- **Ошибка `Could not download`** — проверьте, открывается ли github.com.

Не меняйте файлы в папке расширения — обновление перестанет работать.
