import json
from datetime import datetime, timezone
from pathlib import Path


TASKS_DIR = Path("./workfolder/tasks")
CURRENT_TASK_FILE = TASKS_DIR / "current_task.json"
HISTORY_TASKS_DIR = TASKS_DIR / "history_tasks"

# Коды типа задания внутри файла (совпадают со значениями
# work_order_type, которые присылает ui/settings_dialog.py)
TASK_TYPE_CODES = {
    "serialization": "ser",
    "group_serialization": "gser",
    "aggregation": "agr",
}


def _now_iso() -> str:
    """UTC-время в формате 2026-08-16T17:02:32Z (без микросекунд)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_task_payload(data: dict) -> dict:
    """Собирает словарь для записи в current_task.json на основе данных,
    которые прислал SettingsDialog через сигнал work_order_created.
    Набор ключей зависит от типа задания."""
    task_type_code = TASK_TYPE_CODES[data["work_order_type"]]

    payload = {
        "gtin": data.get("gtin"),
        "name": data.get("product_name"),
        "createdAt": _now_iso(),
    }

    if task_type_code == "agr":
        payload["production_date"] = data.get("production_date")
        payload["expiration_date"] = data.get("expiry_date")

    payload["task_number"] = data.get("order_number")
    payload["task_type"] = task_type_code

    if task_type_code in ("gser", "agr"):
        payload["items_per_box"] = data.get("units_per_package")

    if task_type_code == "agr":
        payload["boxes_per_pallet"] = data.get("packages_per_pallet")
        payload["box_template"] = data.get("packaging_template_path", "")
        payload["pallet_template"] = data.get("pallet_template_path", "")

    payload.update(
        {
            "camera_ip": data.get("camera_ip"),
            "camera_port": data.get("camera_port"),
            "printer_name": data.get("printer_name"),
            "printer_ip": data.get("printer_ip"),
            "printer_port": data.get("printer_port"),
            "print_with_driver": data.get("print_with_driver", "true"),
        }
    )

    return payload


def write_current_task(data: dict) -> Path:
    """Формирует payload и пишет его в ./workfolder/tasks/current_task.json.
    Создаёт папку tasks/, если её ещё нет. Возвращает путь к файлу."""
    payload = build_task_payload(data)

    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CURRENT_TASK_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return CURRENT_TASK_FILE


def load_current_task() -> dict | None:
    """Проверяет, есть ли незавершённое задание с прошлого запуска
    (current_task.json остался на диске — например, из-за внезапного
    выключения питания). Возвращает словарь задания или None, если
    файла нет или он повреждён."""
    if not CURRENT_TASK_FILE.exists():
        return None
    try:
        with open(CURRENT_TASK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[task_writer] Не удалось прочитать {CURRENT_TASK_FILE}: {e}")
        return None


def find_history_task(task_number: str) -> Path | None:
    """Ищет в tasks/history_tasks/ архивный файл ранее выполненного
    задания с таким же номером (имена вида <task_number>-<дата-время>.json).
    Возвращает путь к первому найденному файлу или None."""
    if not HISTORY_TASKS_DIR.exists():
        return None
    matches = sorted(HISTORY_TASKS_DIR.glob(f"{task_number}-*.json"))
    return matches[0] if matches else None


def load_history_task(path: Path) -> dict | None:
    """Читает архивный файл задания. None при отсутствии/повреждении."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[task_writer] Не удалось прочитать {path}: {e}")
        return None


def restore_history_task(path: Path) -> dict | None:
    """Переносит архивный файл задания обратно в tasks/current_task.json
    (если там уже что-то было — перезаписывает без предупреждения; защита
    от этого сценария появится позже, когда "Настройки" будут блокироваться
    при активном задании) и удаляет архивную копию. Возвращает
    восстановленный task dict, или None при ошибке — в этом случае ничего
    не удаляется/не перезаписывается."""
    task = load_history_task(path)
    if task is None:
        return None
    try:
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        with open(CURRENT_TASK_FILE, "w", encoding="utf-8") as f:
            json.dump(task, f, ensure_ascii=False, indent=2)
        path.unlink(missing_ok=True)
    except OSError as e:
        print(f"[task_writer] Не удалось восстановить задание из {path}: {e}")
        return None
    return task