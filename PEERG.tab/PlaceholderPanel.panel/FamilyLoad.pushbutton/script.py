# -*- coding: utf-8 -*-

__title__   = "Family Load"
__doc__     = """Version = 1.0
Date    = 02.06.2025
Loads all families from a folder"""


from pyrevit import revit, DB, forms
import os
import re  # модуль для работы с регулярными выражениями

# Путь к папке с семействами
FAMILIES_FOLDER = r"C:\Users\Dmitry\Desktop\Revit 2024\Families"

# Получаем активный документ
doc = revit.doc

# Проверяем, существует ли папка
if not os.path.exists(FAMILIES_FOLDER):
    forms.alert("Папка с семействами не найдена: {}".format(FAMILIES_FOLDER), exitscript=True)

# Получаем список файлов в папке (без подпапок)
family_files = [
    f for f in os.listdir(FAMILIES_FOLDER)
    if os.path.isfile(os.path.join(FAMILIES_FOLDER, f))
    and f.lower().endswith('.rfa')
    and not re.search(r'\.\d{4}\.rfa$', f)  # Исключаем версии семейства (например, .0001.rfa)
]

# Проверяем, есть ли семейства для загрузки
if not family_files:
    forms.alert("В папке '{}' не найдено подходящих файлов семейств (.rfa).".format(FAMILIES_FOLDER), exitscript=True)

# Загружаем семейства (с заменой существующих)
loaded_count = 0
skipped_files = []

with revit.Transaction("Load Families from Folder"):
    for family_file in family_files:
        family_path = os.path.join(FAMILIES_FOLDER, family_file)
        try:
            loaded = doc.LoadFamily(family_path)
            if loaded:
                loaded_count += 1
            else:
                skipped_files.append(family_file)
        except Exception:
            skipped_files.append(family_file)
            continue

# Выводим результат
result_message = "Загружено (или обновлено) {} семейств из папки '{}'.\n".format(loaded_count, FAMILIES_FOLDER)

if skipped_files:
    result_message += "\nНе удалось загрузить следующие файлы:\n" + "\n".join(skipped_files)

forms.alert(result_message)
