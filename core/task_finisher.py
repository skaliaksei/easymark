import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.task_writer import CURRENT_TASK_FILE


REPORTS_TXT_DIR = Path("./workfolder/reports/txt")
REPORTS_JSON_DIR = Path("./workfolder/reports/json")
OLD_TASKS_DIR = Path("./workfolder/tasks/history_tasks")


def _insert_finished_at(task: dict, finished_at: str) -> dict:
    """Возвращает копию task с полем finishedAt, вставленным сразу
    после createdAt (а не просто добавленным в конец)."""
    updated = {}
    inserted = False
    for key, value in task.items():
        updated[key] = value
        if key == "createdAt":
            updated["finishedAt"] = finished_at
            inserted = True
    if not inserted:
        # На случай отсутствия createdAt в файле — не теряем finishedAt.
        updated["finishedAt"] = finished_at
    return updated


def _fetch_codes(conn: sqlite3.Connection, task_number: str) -> list[str]:
    cur = conn.execute(
        "SELECT code FROM scans WHERE task_number = ? ORDER BY id ASC", (task_number,)
    )
    return [row[0] for row in cur.fetchall()]


def _fetch_aggregation_groups(conn: sqlite3.Connection, task_number: str) -> tuple[list, list]:
    """Для Агрегации отчёт должен показывать иерархию код -> упаковка -> паллета,
    а не плоский список. Строим её из package_code/pallet_code, которые
    scan_processor уже проставил каждой строке в момент сканирования."""
    cur = conn.execute(
        "SELECT code, package_code, pallet_code FROM scans WHERE task_number = ? ORDER BY id ASC",
        (task_number,),
    )

    boxes: dict[str, list[str]] = {}
    pallets: dict[str, list[str]] = {}
    box_seen = set()

    for code, package_code, pallet_code in cur.fetchall():
        boxes.setdefault(package_code, []).append(code)
        if package_code not in box_seen:
            box_seen.add(package_code)
            pallets.setdefault(pallet_code, []).append(package_code)

    boxes_list = [{"name": pkg, "products": codes} for pkg, codes in boxes.items()]
    pallets_list = [{"name": plt, "boxes": pkgs} for plt, pkgs in pallets.items()]
    return boxes_list, pallets_list


def _write_txt_report(task: dict, codes: list[str]) -> Path:
    REPORTS_TXT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{task['task_number']}-{task['gtin']}.txt"
    path = REPORTS_TXT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(codes))
    return path


def _write_json_report(
    task: dict, conn: sqlite3.Connection, flat_codes: list[str]
) -> Path:
    REPORTS_JSON_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{task['task_number']}-{task['gtin']}.json"
    path = REPORTS_JSON_DIR / filename

    is_aggregation = task.get("task_type") == "agr"

    if is_aggregation:
        boxes_list, pallets_list = _fetch_aggregation_groups(conn, task["task_number"])
        units = {"boxes": boxes_list, "pallets": pallets_list}
    else:
        # Для ser/gser пока плоский список — структура отчёта для них
        # ещё не спроектирована, обсудим отдельно позже.
        units = {"products": flat_codes}

    report = {
        "createdAt": task.get("createdAt"),
        "finishedAt": task.get("finishedAt"),
        "gtin": task.get("gtin"),
        "production_date": task.get("production_date") if is_aggregation else "none",
        "expiration_date": task.get("expiration_date") if is_aggregation else "none",
        "task_number": task.get("task_number"),
        "task_type": task.get("task_type"),
        "name": task.get("name"),
        "units": units,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path


def _archive_current_task(task: dict, filename_ts: str) -> Path:
    OLD_TASKS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{task['task_number']}-{filename_ts}.json"
    path = OLD_TASKS_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    return path


def finish_task(task: dict, conn: sqlite3.Connection) -> Path | None:
    """Полный цикл завершения задания:
    1. Добавляет finishedAt в task (сразу после createdAt) и
       перезаписывает current_task.json обновлённой версией.
    2. Формирует txt- и json-отчёты по кодам этого задания из БД.
    3. Архивирует current_task.json в tasks/history_tasks/.
    4. Удаляет current_task.json.

    Возвращает путь к архивному файлу при успехе, или None при ошибке
    (в этом случае current_task.json НЕ удаляется — ничего не теряется,
    можно повторить попытку)."""
    try:
        now_utc = datetime.now(timezone.utc)
        finished_at_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        # Имя файлов — по локальному системному времени, не UTC (так
        # оператору понятнее, "сейчас" совпадает с часами на компьютере).
        filename_ts = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

        updated_task = _insert_finished_at(task, finished_at_iso)

        with open(CURRENT_TASK_FILE, "w", encoding="utf-8") as f:
            json.dump(updated_task, f, ensure_ascii=False, indent=2)

        codes = _fetch_codes(conn, updated_task["task_number"])

        _write_txt_report(updated_task, codes)
        _write_json_report(updated_task, conn, codes)

        archived_path = _archive_current_task(updated_task, filename_ts)

        CURRENT_TASK_FILE.unlink(missing_ok=True)

        return archived_path

    except (OSError, KeyError) as e:
        print(f"[task_finisher] Не удалось завершить задание: {e}")
        return None