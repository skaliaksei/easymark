import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.parent_code_generator import (
    load_template,
    generate_package_code,
    generate_pallet_code,
)


DELIMITER = "@@@"


def extract_gtin(code: str) -> str | None:
    """GTIN — это AI '01' + 14 цифр сразу после него.
    Возвращает None, если код короче ожидаемого или не начинается с '01'."""
    if len(code) < 16 or code[0:2] != "01":
        return None
    return code[2:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ScanResult:
    """Результат обработки одного входящего сообщения от камеры.

    status: 'good' | 'error' | 'duplicate'
    codes: коды, которые были РЕАЛЬНО ЗАПИСАНЫ в базу (пусто, если
           status != 'good' — отклонённые коды в таблицу не попадают,
           только через цветной индикатор статуса)
    reason: причина отказа, для будущего UI (пока нигде не отображается)
    package_code: агрегационный код упаковки (только для agr, иначе None) —
           нужен модулю печати этикетки упаковки. pallet_code в ScanResult
           намеренно не выносится — этикетки паллет пока не печатаются
           автоматически (упростили; сама генерация pallet_code в БД
           никак не изменилась).
    """

    status: str
    codes: list[str] = field(default_factory=list)
    reason: str | None = None
    package_code: str | None = None


class ScanProcessor:
    """Общая база для всех трёх правил. Держит открытое соединение с БД
    (используется только из главного потока — соединение живёт всю
    сессию сканирования, от "Пуск" до "Стоп")."""

    def __init__(self, task: dict, conn: sqlite3.Connection):
        self.task = task
        self.conn = conn

    def handle_message(self, raw_message: str) -> ScanResult:
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    def _is_duplicate(self, code: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM scans WHERE code = ?", (code,))
        return cur.fetchone() is not None

    def _any_duplicate(self, codes: list[str]) -> bool:
        placeholders = ",".join("?" for _ in codes)
        cur = self.conn.execute(
            f"SELECT 1 FROM scans WHERE code IN ({placeholders}) LIMIT 1", codes
        )
        return cur.fetchone() is not None

    def _insert(self, codes: list[str], package_code: str | None, pallet_code: str | None):
        now = _now_iso()
        task_number = self.task["task_number"]
        self.conn.executemany(
            """
            INSERT INTO scans (task_number, code, package_code, pallet_code, scanned_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(task_number, code, package_code, pallet_code, now) for code in codes],
        )
        self.conn.commit()


class SerializationProcessor(ScanProcessor):
    """Один код в сообщении = один код на обработку. Без буфера."""

    def handle_message(self, raw_message: str) -> ScanResult:
        code = raw_message.strip()
        if not code:
            return ScanResult(status="error", reason="Пустое сообщение от камеры")

        gtin = extract_gtin(code)
        if gtin is None or gtin != self.task["gtin"]:
            return ScanResult(status="error", reason=f"GTIN не совпадает: {code}")

        if self._is_duplicate(code):
            return ScanResult(status="duplicate", reason=f"Код уже отсканирован: {code}")

        self._insert([code], package_code=None, pallet_code=None)
        return ScanResult(status="good", codes=[code])


class GroupSerializationProcessor(ScanProcessor):
    """Группа кодов через разделитель @@@. Принцип целостности группы:
    любая проваленная проверка отклоняет ВСЮ группу целиком."""

    def _split_and_dedupe(self, raw_message: str) -> list[str]:
        codes = [c for c in raw_message.split(DELIMITER) if c]
        # de-dup с сохранением порядка (на случай, если камера
        # случайно продублировала код внутри одного сообщения)
        return list(dict.fromkeys(codes))

    def _check_gtin(self, codes: list[str]) -> str | None:
        """Возвращает код, у которого GTIN не совпал, или None если все ок."""
        expected_gtin = self.task["gtin"]
        for code in codes:
            gtin = extract_gtin(code)
            if gtin is None or gtin != expected_gtin:
                return code
        return None

    def handle_message(self, raw_message: str) -> ScanResult:
        codes = self._split_and_dedupe(raw_message)

        bad_code = self._check_gtin(codes)
        if bad_code is not None:
            return ScanResult(status="error", reason=f"GTIN не совпадает: {bad_code}")

        expected_count = int(self.task["items_per_box"])
        if len(codes) != expected_count:
            return ScanResult(
                status="error",
                reason=f"Ожидалось {expected_count} кодов, получено {len(codes)}",
            )

        if self._any_duplicate(codes):
            return ScanResult(status="duplicate", reason="Один или несколько кодов уже отсканированы")

        self._insert(codes, package_code=None, pallet_code=None)
        return ScanResult(status="good", codes=codes)


class AggregationProcessor(GroupSerializationProcessor):
    """Та же логика группы, что и Групповая сериализация, плюс назначение
    package_code/pallet_code в момент успешной записи."""

    def __init__(self, task: dict, conn: sqlite3.Connection, template: dict):
        super().__init__(task, conn)
        self.template = template

    def handle_message(self, raw_message: str) -> ScanResult:
        codes = self._split_and_dedupe(raw_message)

        bad_code = self._check_gtin(codes)
        if bad_code is not None:
            return ScanResult(status="error", reason=f"GTIN не совпадает: {bad_code}")

        expected_count = int(self.task["items_per_box"])
        if len(codes) != expected_count:
            return ScanResult(
                status="error",
                reason=f"Ожидалось {expected_count} кодов, получено {len(codes)}",
            )

        if self._any_duplicate(codes):
            return ScanResult(status="duplicate", reason="Один или несколько кодов уже отсканированы")

        # Родительские коды генерируются только теперь, когда точно
        # знаем, что группа будет записана — чтобы не тратить серийники
        # впустую на отбракованные группы.
        package_code, pallet_code = self._assign_parents()
        self._insert(codes, package_code=package_code, pallet_code=pallet_code)
        return ScanResult(status="good", codes=codes, package_code=package_code)

    # ------------------------------------------------------------------ #
    def _count_distinct(self, column: str, task_number: str) -> int:
        cur = self.conn.execute(
            f"SELECT COUNT(DISTINCT {column}) FROM scans WHERE task_number = ?",
            (task_number,),
        )
        return cur.fetchone()[0]

    def _current_pallet_code(self, task_number: str) -> str | None:
        cur = self.conn.execute(
            "SELECT pallet_code FROM scans WHERE task_number = ? ORDER BY id DESC LIMIT 1",
            (task_number,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def _packages_on_pallet(self, pallet_code: str, task_number: str) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(DISTINCT package_code) FROM scans WHERE task_number = ? AND pallet_code = ?",
            (task_number, pallet_code),
        )
        return cur.fetchone()[0]

    def _assign_parents(self) -> tuple[str, str]:
        task_number = self.task["task_number"]

        package_serial = self._count_distinct("package_code", task_number) + 1
        package_code = generate_package_code(self.template, self.task, package_serial)

        boxes_per_pallet = int(self.task["boxes_per_pallet"])
        pallet_code = self._current_pallet_code(task_number)

        pallet_is_full = (
            pallet_code is None
            or self._packages_on_pallet(pallet_code, task_number) >= boxes_per_pallet
        )
        if pallet_is_full:
            pallet_serial = self._count_distinct("pallet_code", task_number) + 1
            pallet_code = generate_pallet_code(self.template, self.task, pallet_serial)

        return package_code, pallet_code


TASK_TYPE_PROCESSORS = {
    "ser": SerializationProcessor,
    "gser": GroupSerializationProcessor,
    "agr": AggregationProcessor,
}


def build_scan_processor(task: dict, conn: sqlite3.Connection) -> ScanProcessor | None:
    """Читает task_type из задания и собирает подходящий обработчик —
    вызывается ОДИН раз при "Пуск", не на каждое сообщение (task_type
    не может измениться, пока идёт сканирование — "Настройки" заблокированы).
    Возвращает None, если тип неизвестен или (для Агрегации) шаблон
    родительских кодов не удалось загрузить — в этом случае вызывающий
    код должен отказаться запускать сканирование."""
    task_type = task.get("task_type")

    if task_type == "agr":
        template = load_template()
        if template is None:
            return None
        return AggregationProcessor(task, conn, template)

    processor_cls = TASK_TYPE_PROCESSORS.get(task_type)
    if processor_cls is None:
        print(f"[scan_processor] Неизвестный task_type: {task_type!r}")
        return None
    return processor_cls(task, conn)