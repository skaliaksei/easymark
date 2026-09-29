import json
from datetime import datetime
from pathlib import Path


TEMPLATE_PATH = Path("./workfolder/templates/template_parents.json")

# Поля дат в current_task.json хранятся в читаемом ISO-формате (YYYY-MM-DD —
# так их отдаёт QDateEdit), а в самом коде GS1 требует формат YYMMDD (AI 11/17).
# Конвертация делается здесь, в момент генерации кода — current_task.json
# при этом остаётся в удобном для чтения/отладки формате.
DATE_FIELDS = {"production_date", "expiration_date"}


def load_template() -> dict | None:
    """Читает ./workfolder/templates/template_parents.json.
    Возвращает None, если файла нет или он повреждён — вызывающий код
    (AppController) должен в этом случае отказаться запускать Агрегацию,
    а не пытаться сканировать без шаблона."""
    if not TEMPLATE_PATH.exists():
        print(f"[parent_code_generator] Файл шаблона не найден: {TEMPLATE_PATH.resolve()}")
        return None
    try:
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            template = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[parent_code_generator] Не удалось прочитать {TEMPLATE_PATH}: {e}")
        return None

    if "boxes" not in template or "pallets" not in template:
        print(f"[parent_code_generator] В шаблоне нет обязательных ключей boxes/pallets")
        return None

    return template


def _to_gs1_date(iso_date: str) -> str:
    """ISO 'YYYY-MM-DD' -> GS1 'YYMMDD'. Если формат неожиданный —
    возвращает значение как есть, не роняя генерацию кода."""
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%y%m%d")
    except ValueError:
        print(f"[parent_code_generator] Неожиданный формат даты: {iso_date!r}")
        return iso_date


def _substitute(template_str: str, task: dict, serial_number: int) -> str:
    """Подставляет в строку шаблона значения из task (переменные названы
    один в один с ключами current_task.json) и serial_number отдельно,
    т.к. его в task нет — он вычисляется в момент генерации."""
    result = template_str
    for key, value in task.items():
        if key in DATE_FIELDS:
            value = _to_gs1_date(str(value))
        result = result.replace(f"<{key}>", str(value))
    result = result.replace("<serial_number>", str(serial_number))
    return result


def generate_package_code(template: dict, task: dict, serial_number: int) -> str:
    return _substitute(template["boxes"], task, serial_number)


def generate_pallet_code(template: dict, task: dict, serial_number: int) -> str:
    return _substitute(template["pallets"], task, serial_number)