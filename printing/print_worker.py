import shutil
import socket
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty

from PyQt6.QtCore import QThread


PRINT_DIR = Path("./workfolder/templates/print")

# Длины значений для стандартных Application Identifier GS1 (см. GS1
# General Specifications) — это международный стандарт, а НЕ что-то
# привязанное к нашему конкретному template_parents.json. AI из этого
# списка ВСЕГДА имеют фиксированную длину значения по стандарту (поэтому
# в коде после них никогда не бывает GS-разделителя); AI, которых здесь
# нет (например 10, 21, 30, 37 — партия/серийник/количество), по
# стандарту имеют ПЕРЕМЕННУЮ длину, и их значение всегда ограничено
# либо GS-байтом, либо концом строки. Именно поэтому разбор ниже не
# зависит от порядка или набора AI в шаблоне — он опирается на сам
# стандарт GS1, а не на структуру нашего шаблона.
GS1_AI_FIXED_LENGTHS = {
    "00": 18, "01": 14, "02": 14,
    "11": 6, "13": 6, "15": 6, "17": 6,
    "20": 2,
    "31": 10, "32": 10, "33": 10, "34": 10, "35": 10, "36": 10,
    "41": 14,
}


def format_gs1_readable(code: str) -> str:
    """Строит человекочитаемое представление кода вида
    "(01)04810389004126(11)260909(17)270309(10)006(37)5(21)4" —
    разбирает по правилам GS1 (см. GS1_AI_FIXED_LENGTHS), а не по
    структуре нашего шаблона, поэтому остаётся верным, даже если
    пользователь поменяет состав/порядок AI в template_parents.json —
    пока это настоящие GS1-коды, разбор работает."""
    parts = []
    i, n = 0, len(code)
    while i < n:
        if code[i] == "\x1d":
            i += 1
            continue
        ai = code[i : i + 2]
        i += 2
        fixed_len = GS1_AI_FIXED_LENGTHS.get(ai)
        if fixed_len is not None:
            value = code[i : i + fixed_len]
            i += fixed_len
        else:
            gs_pos = code.find("\x1d", i)
            if gs_pos == -1:
                value = code[i:]
                i = n
            else:
                value = code[i:gs_pos]
                i = gs_pos
        parts.append(f"({ai}){value}")
    return "".join(parts)

# ВРЕМЕННЫЙ флаг для отладки: True — обычное поведение (файл удаляется
# сразу после печати); False — файл current_print_box.prn остаётся в
# ./workfolder/templates/print/ после печати, чтобы можно было открыть
# и посмотреть, что реально ушло на принтер. Не забыть вернуть в True.
DELETE_AFTER_PRINT = False


@dataclass
class PrintJob:
    """Задание на печать этикетки упаковки. Этикетки паллет пока НЕ
    печатаются автоматически (решено упростить — печатать их будем
    вручную отдельной функцией, реализуем позже)."""

    template_path: str
    output_filename: str = "current_print_box.prn"
    gs1_128_value: str = ""
    gs1_128_description_value: str = ""
    print_with_driver: bool = True
    printer_name: str = ""
    printer_ip: str = ""
    printer_port: str = ""


def _build_label_bytes(
    output_path: Path, gs1_128_value: str, gs1_128_description_value: str
) -> bytes:
    """Читает уже скопированный файл-копию шаблона как чистые байты
    (без интерпретации кодировки — печатаем "как есть", ровно как при
    ручном COPY /B) и подставляет переменные."""
    with open(output_path, "rb") as f:
        content = f.read()
    content = content.replace(
        b"<gs1-128_description>", gs1_128_description_value.encode("ascii")
    )
    content = content.replace(b"<gs1-128>", gs1_128_value.encode("ascii"))
    return content


def _print_via_driver(printer_name: str, raw_data: bytes, doc_name: str = "EasyMark label") -> None:
    import win32print  # импорт здесь — чтобы режим TCP работал вообще без pywin32

    hPrinter = win32print.OpenPrinter(printer_name)
    try:
        # datatype "RAW": спулер передаёт данные как есть, без попытки
        # интерпретировать через драйвер — то же самое, что COPY /B.
        job_info = (doc_name, None, "RAW")
        win32print.StartDocPrinter(hPrinter, 1, job_info)
        try:
            win32print.StartPagePrinter(hPrinter)
            win32print.WritePrinter(hPrinter, raw_data)
            win32print.EndPagePrinter(hPrinter)
        finally:
            win32print.EndDocPrinter(hPrinter)
    finally:
        win32print.ClosePrinter(hPrinter)


def _print_via_tcp(ip: str, port: int, raw_data: bytes, timeout: float = 5.0) -> None:
    with socket.create_connection((ip, port), timeout=timeout) as sock:
        sock.sendall(raw_data)


def process_print_job(job: PrintJob) -> None:
    """Копирует шаблон → current_print_box.prn, подставляет переменные,
    печатает, удаляет файл. При любой ошибке — сообщение в консоль,
    файл НЕ удаляется (остаётся для диагностики), сканирование не
    прерывается — вызывающий код (очередь) просто переходит к следующему
    заданию."""
    PRINT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PRINT_DIR / job.output_filename

    try:
        shutil.copy(job.template_path, output_path)
    except OSError as e:
        print(f"[print_worker] Не удалось скопировать шаблон {job.template_path}: {e}")
        return

    try:
        raw_data = _build_label_bytes(
            output_path, job.gs1_128_value, job.gs1_128_description_value
        )
        with open(output_path, "wb") as f:
            f.write(raw_data)
    except OSError as e:
        print(f"[print_worker] Не удалось подготовить файл печати {output_path}: {e}")
        return

    try:
        if job.print_with_driver:
            _print_via_driver(job.printer_name, raw_data)
        else:
            _print_via_tcp(job.printer_ip, int(job.printer_port), raw_data)
    except Exception as e:
        # Печать — граница с внешним оборудованием (драйвер/сеть), тут
        # может прилететь что угодно (pywintypes.error, socket.timeout,
        # OSError...) — ловим широко, чтобы очередь не встала намертво.
        print(f"[print_worker] Ошибка печати {output_path}: {e}")
        return  # файл намеренно НЕ удаляем — для диагностики

    if not DELETE_AFTER_PRINT:
        print(f"[print_worker] DELETE_AFTER_PRINT=False — файл оставлен: {output_path}")
        return

    try:
        output_path.unlink(missing_ok=True)
    except OSError as e:
        print(f"[print_worker] Не удалось удалить {output_path} после печати: {e}")


class PrintQueueWorker(QThread):
    """Фоновый поток-очередь печати. Работает в режиме ожидания весь
    жизненный цикл приложения (запускается один раз при старте, не
    пересоздаётся на каждое задание) и выполняет задания строго одно
    за другим."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: "Queue[PrintJob]" = Queue()
        self._running = True

    def enqueue(self, job: PrintJob) -> None:
        """Вызывается из главного потока — просто кладёт задание в
        потокобезопасную очередь, ничего не блокирует."""
        self._queue.put(job)

    def run(self) -> None:
        while self._running:
            try:
                job = self._queue.get(timeout=0.5)
            except Empty:
                continue
            process_print_job(job)

    def stop(self) -> None:
        self._running = False