"""
hwlock.py — привязка программы к конкретным компьютерам по железу.

Логика выбора идентификатора:
    1. Пытаемся получить ID материнской платы (UUID системы + серийник платы).
    2. Если хотя бы один из них непустой и не похож на "мусорный" плейсхолдер
       (вроде "To be filled by O.E.M.") — хешируем ТОЛЬКО плату.
    3. Если платы нет вообще (оба поля пустые/мусорные) — переходим на
       серийный номер физического диска и хешируем его.

Зачем так: если у машины действительно нет валидного ID платы, использование
пустой строки как "идентификатора" опасно — у любых двух таких машин
(например, клон системы на другом железе) хеш совпадёт. Диск в этом случае —
запасной, но тоже физически привязанный к железу параметр.

Использование:
    1. На каждом разрешённом ПК запустить `python hwlock.py` — скрипт
       выведет хеш этой машины и сохранит hwlock_info.txt рядом со скриптом
       (источник идентификатора, сам идентификатор и хеш).
    2. Эти хеши прописать в ALLOWED_HW_HASHES.
    3. В точке входа программы вызвать check_hw_allowed() — при каждом
       запуске программы этот же hwlock_info.txt будет создаваться/
       обновляться рядом с исполняемым файлом (.exe при сборке PyInstaller,
       .py при обычном запуске).
"""

import hashlib
import os
import subprocess
import sys

INFO_FILENAME = "hwlock_info.txt"

# Значения, которые WMI/wmic возвращают вместо реального ID, когда
# производитель просто не заполнил поле. Такие значения не считаем валидным ID.
_PLACEHOLDER_VALUES = {
    "",
    "to be filled by o.e.m.",
    "default string",
    "system serial number",
    "none",
    "not specified",
    "0",
    "00000000-0000-0000-0000-000000000000",
}


def _is_valid(value: str) -> bool:
    return bool(value) and value.strip().lower() not in _PLACEHOLDER_VALUES


def _run_wmic(cmd: list[str]) -> str:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    return lines[1] if len(lines) > 1 else ""


def get_raw_hw_ids() -> dict:
    """
    Возвращает сырые идентификаторы железа: плата (UUID + серийник) и диск.
    Сначала пробуем WMI (модуль wmi), при ошибке — wmic.
    """
    try:
        import wmi

        c = wmi.WMI()
        info = {"UUID": "", "BoardSerial": "", "DiskSerial": ""}

        products = c.Win32_ComputerSystemProduct()
        if products:
            info["UUID"] = (products[0].UUID or "").strip()

        boards = c.Win32_BaseBoard()
        if boards:
            info["BoardSerial"] = (boards[0].SerialNumber or "").strip()

        disks = c.Win32_DiskDrive()
        if disks:
            # Берём системный диск — обычно первый (Index=0); если нужно
            # именно диск с ОС, можно доп. отфильтровать по DeviceID.
            info["DiskSerial"] = (disks[0].SerialNumber or "").strip()

        return info
    except Exception:
        return {
            "UUID": _run_wmic(["wmic", "csproduct", "get", "UUID"]),
            "BoardSerial": _run_wmic(["wmic", "baseboard", "get", "SerialNumber"]),
            "DiskSerial": _run_wmic(["wmic", "diskdrive", "get", "SerialNumber"]),
        }


def get_current_hw_hash() -> tuple[str, str, str]:
    """
    Возвращает (хеш, источник, сырой_идентификатор).
    Источник — "board" или "disk", либо "" если вообще ничего валидного не нашли
    (тогда и хеш, и сырой идентификатор — тоже пустые строки).

    Приоритет: плата > диск. Если у платы есть валидный UUID и/или серийник —
    хешируем только плату (диск в хеш НЕ подмешивается). Иначе — только диск.
    """
    ids = get_raw_hw_ids()
    uuid = ids.get("UUID", "")
    board_serial = ids.get("BoardSerial", "")
    disk_serial = ids.get("DiskSerial", "")

    board_parts = [v for v in (uuid, board_serial) if _is_valid(v)]
    if board_parts:
        combined = "|".join(board_parts)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest(), "board", combined

    if _is_valid(disk_serial):
        return hashlib.sha256(disk_serial.encode("utf-8")).hexdigest(), "disk", disk_serial

    return "", "", ""


def _executable_dir() -> str:
    """
    Папка рядом с исполняемым файлом: если приложение собрано (PyInstaller
    и т.п.) — рядом с .exe, иначе — рядом с самим .py скриптом.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def write_hw_info_file(path: str | None = None) -> str:
    """
    Пишет рядом с исполняемым файлом txt со сведениями о текущей машине:
    источник идентификатора, сам "сырой" идентификатор и его хеш.

    Полезно для отладки/выдачи ID: не нужно смотреть консольный вывод —
    можно просто открыть файл и скопировать хеш в ALLOWED_HW_HASHES.
    """
    h, source, raw = get_current_hw_hash()

    if path is None:
        path = os.path.join(_executable_dir(), INFO_FILENAME)

    label = {"board": "Motherboard", "disk": "Hard disk (Motherboard has not been found)", "": "Undefined"}[source]

    lines = [
        f"ID source: {label}",
        f"ID: {raw if raw else '(has not been found)'}",
        f"Hash: {h if h else '(has not been found)'}",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return path


# Разрешённые машины (рабочий ПК, ноутбук) — получены запуском
# `python hwlock.py` на каждой из них.
HASH_1 = "233bba2102c0aa68baed0b1eefca6485c4bc031223dc8ebeedb2029d33830c24"
HASH_2 = "0e2cbadec595aacf0cf9c14c07c2111f93aebc734b55defb2339e0ff5a5cb167"

ALLOWED_HW_HASHES = {
    HASH_1,
    HASH_2,
}


def check_hw_allowed(exit_on_fail: bool = True, write_info_file: bool = True) -> bool:
    """
    Проверяет, что текущая машина в списке разрешённых.
    По умолчанию при провале сразу завершает процесс (exit_on_fail=True) —
    удобно вызывать первой строкой в main().

    write_info_file=True (по умолчанию) — при каждой проверке рядом с
    исполняемым файлом создаётся/перезаписывается hwlock_info.txt с
    источником, сырым идентификатором и хешем текущей машины.
    """
    current, _source, _raw = get_current_hw_hash()
    allowed = bool(current) and current in ALLOWED_HW_HASHES

    if write_info_file:
        try:
            write_hw_info_file()
        except Exception:
            # Не даём сбою записи файла (например, нет прав на папку)
            # уронить саму проверку доступа.
            pass

    if not allowed and exit_on_fail:
        print("Ошибка: запуск на этом компьютере не разрешён.")
        sys.exit(1)

    return allowed


if __name__ == "__main__":
    # Утилита: узнать хеш текущей машины и сразу сохранить его в txt рядом
    # со скриптом, чтобы вписать хеш в ALLOWED_HW_HASHES.
    h, source, raw = get_current_hw_hash()
    if not h:
        print("Не удалось получить ни ID платы, ни серийник диска.")
    else:
        label = "материнская плата" if source == "board" else "диск (плата не найдена)"
        print(f"Источник идентификатора: {label}")
        print(f"Идентификатор: {raw}")
        print(f"Хеш текущей машины: {h}")

    out_path = write_hw_info_file()
    print(f"\nСведения сохранены в: {out_path}")
