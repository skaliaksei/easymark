import sys
import hwlock
from datetime import datetime, timezone

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.settings_dialog import SettingsDialog
from ui.message_dialog import MessageDialog
from ui.product_dialog import ProductDialog
from ui.history_dialog import HistoryDialog
from ui.hierarchy_dialog import HierarchyDialog
from ui.app_icon import get_app_icon
from core import task_writer, database, scan_processor, task_finisher
from camera.scanner_service import CameraListener
from printing.print_worker import PrintQueueWorker, PrintJob, format_gs1_readable


class AppController:
    """Пока просто связывает окна между собой: слушает сигналы UI
    и решает, что показать. Когда появится camera/ и настоящая
    логика сканирования, она тоже будет подключаться сюда —
    сами окна (MainWindow, SettingsDialog) об этом не знают.
    """

    def __init__(self):
        self.window = MainWindow()
        self.window.settings_clicked.connect(self.open_settings)
        self.window.product_clicked.connect(self.open_product_dialog)
        self.window.history_clicked.connect(self.open_history_dialog)
        self.window.start_stop_clicked.connect(self.on_start_stop_clicked)
        self.window.finish_clicked.connect(self.on_finish_clicked)
        self.camera_listener = None
        self._stop_requested = False
        self._camera_was_connected = False
        self._db_conn = None
        self._scan_processor = None
        self._current_task = None

        # Очередь печати работает в режиме ожидания весь срок жизни
        # приложения — не пересоздаётся на каждое задание/сканирование.
        self.print_queue = PrintQueueWorker()
        self.print_queue.start()

    def open_product_dialog(self):
        # Кнопка визуально превращается в "Иерархия", пока есть активное
        # задание — маршрутизируем клик по факту наличия current_task.json,
        # а не по какому-то отдельному кэшированному флагу.
        task = task_writer.load_current_task()
        if task is not None:
            dialog = HierarchyDialog(self.window, task, self.print_queue)
            dialog.exec()
            return

        dialog = ProductDialog(self.window)
        dialog.product_created.connect(self.on_product_created)
        dialog.exec()

    def on_product_created(self, product: dict):
        # Пока просто уведомляем оператора об успехе. Список GTIN
        # в SettingsDialog перечитывается заново при каждом открытии
        # окна настроек, так что новый продукт сразу там появится.
        MessageDialog.info(
            self.window,
            "Продукт создан",
            f"Продукт «{product['name']}» (GTIN {product['gtin']}) успешно создан.",
        )

    def open_history_dialog(self):
        dialog = HistoryDialog(self.window)
        dialog.task_resumed.connect(self.on_task_resumed)
        dialog.exec()

    def open_settings(self):
        dialog = SettingsDialog(self.window)
        dialog.work_order_created.connect(self.on_work_order_created)
        dialog.task_resumed.connect(self.on_task_resumed)
        dialog.exec()

    def on_work_order_created(self, data: dict):
        # Пишем задание на диск — дальше камера/логика буфера будут
        # читать именно этот файл, а не держать состояние в памяти UI.
        try:
            path = task_writer.write_current_task(data)
            print(f"[AppController] Задание записано: {path}")
        except OSError as e:
            print(f"[AppController] Не удалось записать задание: {e}")

        self.window.set_gtin(data["gtin"], data["product_name"])
        self.window.set_task_number(data["order_number"])
        self.window.set_task_active(True)

    def on_task_resumed(self, task: dict):
        # Файл уже перенесён в current_task.json внутри SettingsDialog
        # (task_writer.restore_history_task) — тут только отражаем это
        # в главном окне, повторно ничего не пишем.
        self.window.set_gtin(task.get("gtin", "—"), task.get("name", ""))
        self.window.set_task_number(task.get("task_number", ""))
        self.window.set_task_active(True)

    def on_start_stop_clicked(self):
        if self.window._is_running:
            self._stop_camera()
        else:
            self._start_camera()

    def _start_camera(self):
        task = task_writer.load_current_task()
        if task is None:
            MessageDialog.error(
                self.window,
                "Нет активного задания",
                "Сначала создайте рабочее задание в Настройках.",
            )
            return

        ip = task.get("camera_ip")
        port_raw = task.get("camera_port")
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            MessageDialog.error(
                self.window,
                "Некорректный порт камеры",
                f"Порт камеры в задании указан неверно: {port_raw!r}",
            )
            return

        # Собираем обработчик сканов ДО подключения к камере — нет смысла
        # открывать соединение, если потом нечем будет обрабатывать данные
        # (неизвестный task_type, или для Агрегации не нашёлся/битый шаблон
        # родительских кодов).
        conn = database.get_connection()
        processor = scan_processor.build_scan_processor(task, conn)
        if processor is None:
            conn.close()
            MessageDialog.error(
                self.window,
                "Не удалось запустить сканирование",
                "Проверьте тип задания и наличие файла шаблона родительских "
                "кодов (для Агрегации) в ./workfolder/templates/.",
            )
            return

        self._db_conn = conn
        self._scan_processor = processor
        self._current_task = task

        self.window.set_connecting(True)
        self._stop_requested = False
        self._camera_was_connected = False

        self.camera_listener = CameraListener(ip, port)
        self.camera_listener.connected.connect(self._on_camera_connected)
        self.camera_listener.error.connect(self._on_camera_error)
        self.camera_listener.disconnected.connect(self._on_camera_disconnected)
        self.camera_listener.raw_message_received.connect(self._on_raw_message_received)
        self.camera_listener.start()

    def _stop_camera(self):
        self._stop_requested = True
        if self.camera_listener:
            self.camera_listener.stop()
        # Кнопка вернётся в состояние "Пуск" в _on_camera_disconnected,
        # когда поток реально завершится — не раньше.

    def _on_camera_connected(self):
        self._camera_was_connected = True
        self.window.set_connecting(False)
        self.window.set_running(True)
        self.window.set_camera_connected(True)
        self._restore_table_from_db()
        self._refresh_counters()

    def _on_camera_error(self, message: str):
        self.window.set_connecting(False)
        self.window.set_camera_connected(False)
        MessageDialog.error(self.window, "Ошибка подключения к камере", message)

    def _on_camera_disconnected(self):
        # Отличаем ожидаемое отключение (оператор нажал "Стоп" или
        # "Завершить задание") от неожиданного обрыва связи (камеру
        # выключили, оборвался кабель/сеть) — сообщаем только про второе,
        # иначе окно ошибки выскакивало бы при каждом обычном "Стоп".
        unexpected = not self._stop_requested and self._camera_was_connected
        self._stop_requested = False
        self._camera_was_connected = False

        self.window.set_connecting(False)
        self.window.set_running(False)
        self.window.set_camera_connected(False)
        self.camera_listener = None

        if self._db_conn is not None:
            self._db_conn.close()
        self._db_conn = None
        self._scan_processor = None
        self._current_task = None

        if unexpected:
            MessageDialog.error(
                self.window,
                "Соединение потеряно",
                "Связь с камерой прервалась. Проверьте кабель и питание камеры, затем запустите сканирование заново.",
            )

    def _on_raw_message_received(self, message: str):
        result = self._scan_processor.handle_message(message)
        self._handle_scan_result(result)

    def _handle_scan_result(self, result: scan_processor.ScanResult):
        self.window.set_scan_status(result.status, result.reason or "")

        if result.status == "good":
            timestamp = datetime.now().strftime("%H:%M:%S")
            for code in result.codes:
                self.window.add_scan_row(code, "GOOD", timestamp)
            self._refresh_counters()
            self._enqueue_box_print_job(result)
            # Зелёный статус — кратковременное подтверждение, гаснет через
            # 1.5 сек и возвращается к "ожиданию". Красный/жёлтый статусы
            # остаются на экране до следующего скана — оператору нужно
            # время заметить и отреагировать на проблему.
            QTimer.singleShot(1500, lambda: self.window.set_scan_status("idle"))
        else:
            # error/duplicate: причина пока только в консоли, отдельное
            # место для неё в UI ещё не выбрано (открытый вопрос).
            print(f"[AppController] {result.status}: {result.reason}")

    def _enqueue_box_print_job(self, result: scan_processor.ScanResult):
        """Печать доступна только для Агрегации, и пока только для
        этикетки упаковки — этикетки паллет печатаются вручную отдельной
        функцией (сделаем позже, решили упростить)."""
        if self._current_task is None or self._current_task.get("task_type") != "agr":
            return
        if result.package_code is None:
            return

        task = self._current_task
        gs1_128 = result.package_code.replace("\x1d", "!102")
        gs1_128_description = format_gs1_readable(result.package_code)

        self.print_queue.enqueue(
            PrintJob(
                template_path=task.get("box_template", ""),
                gs1_128_value=gs1_128,
                gs1_128_description_value=gs1_128_description,
                print_with_driver=task.get("print_with_driver", "true") == "true",
                printer_name=task.get("printer_name", ""),
                printer_ip=task.get("printer_ip", ""),
                printer_port=task.get("printer_port", ""),
            )
        )

    def _restore_table_from_db(self):
        """При подключении (в т.ч. если это продолжение ранее начатого
        задания — например, после сбоя питания) подтягивает уже
        существующие в БД коды этого task_number и заполняет ими таблицу,
        чтобы оператор сразу видел, что сканирование продолжается с того
        же места, а не с нуля."""
        if self._db_conn is None or self._current_task is None:
            return

        self.window.clear_table()
        task_number = self._current_task["task_number"]
        cur = self._db_conn.execute(
            "SELECT code, scanned_at FROM scans WHERE task_number = ? ORDER BY id ASC",
            (task_number,),
        )
        for code, scanned_at in cur.fetchall():
            self.window.add_scan_row(code, "GOOD", self._format_timestamp(scanned_at))

    @staticmethod
    def _format_timestamp(scanned_at: str) -> str:
        """scanned_at хранится в БД как UTC ISO ('...Z'). Переводим в
        локальное время, чтобы восстановленные строки не отличались по
        смыслу от тех, что добавляются вживую (datetime.now() — локальное)."""
        try:
            dt = datetime.strptime(scanned_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            return dt.astimezone().strftime("%H:%M:%S")
        except ValueError:
            return scanned_at

    def _refresh_counters(self):
        if self._db_conn is None or self._current_task is None:
            return
        task_number = self._current_task["task_number"]

        cur = self._db_conn.execute(
            "SELECT COUNT(*) FROM scans WHERE task_number = ?", (task_number,)
        )
        units = cur.fetchone()[0]

        cur = self._db_conn.execute(
            "SELECT COUNT(DISTINCT package_code) FROM scans WHERE task_number = ?",
            (task_number,),
        )
        packages = cur.fetchone()[0]

        cur = self._db_conn.execute(
            "SELECT COUNT(DISTINCT pallet_code) FROM scans WHERE task_number = ?",
            (task_number,),
        )
        pallets = cur.fetchone()[0]

        self.window.set_session_stats(units=units, packages=packages, pallets=pallets)

    def on_finish_clicked(self):
        # Защитный код на случай, если сигнал всё же пришёл во время
        # работы (в норме кнопка заблокирована — см. set_running/
        # set_connecting в MainWindow, но лучше перестраховаться).
        if self.window._is_running:
            self._stop_camera()

        task = task_writer.load_current_task()
        if task is None:
            MessageDialog.error(
                self.window,
                "Нет активного задания",
                "Нечего завершать — активное задание не найдено.",
            )
            return

        conn = database.get_connection()
        try:
            archived_path = task_finisher.finish_task(task, conn)
        finally:
            conn.close()

        if archived_path is None:
            MessageDialog.error(
                self.window,
                "Не удалось завершить задание",
                "Не получилось сформировать отчёты или архивировать задание. "
                "Подробности — в консоли. Задание НЕ закрыто, можно повторить попытку.",
            )
            return

        print(f"[AppController] Задание завершено, архив: {archived_path}")

        # Возвращаем UI в состояние "как при включении программы".
        self.window.set_gtin("—", "Продукт не выбран")
        self.window.set_task_number("")
        self.window.set_session_stats(units=0, packages=0, pallets=0)
        self.window.clear_table()
        self.window.set_camera_connected(False)
        self.window.set_task_active(False)

        MessageDialog.info(
            self.window,
            "Задание завершено",
            "Задание завершено. Отчёты сохранены в рабочую папку.",
        )

    def show(self):
        self.window.show()
        self._check_for_unfinished_task()

    def _check_for_unfinished_task(self):
        """При запуске проверяем, не остался ли на диске current_task.json
        с прошлого сеанса (например, компьютер выключился раньше, чем
        оператор успел нажать "Завершить задание"). Пока просто
        предупреждаем и подставляем GTIN/продукт из найденного файла —
        восстановление счётчиков сессии появится вместе с camera/,
        когда будет готов буфер и файл-отчёт.
        """
        task = task_writer.load_current_task()
        if task is None:
            return

        MessageDialog.warning(
            self.window,
            "Незавершённое задание",
            "Внимание! Обнаружено незавершённое задание.\nЗапускаем для продолжения.",
        )
        self.window.set_gtin(task.get("gtin", "—"), task.get("name", ""))
        self.window.set_task_number(task.get("task_number", ""))
        self.window.set_task_active(True)


def main():
    hwlock.check_hw_allowed()

    app = QApplication(sys.argv)
    app.setWindowIcon(get_app_icon())
    database.init_db()
    controller = AppController()
    controller.show()

    def _on_quit():
        controller.print_queue.stop()
        controller.print_queue.wait(2000)

    app.aboutToQuit.connect(_on_quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()