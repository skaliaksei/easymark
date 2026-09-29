from datetime import datetime, timezone

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QStyledItemDelegate,
)

from ui.app_icon import get_app_icon
from ui.message_dialog import MessageDialog
from core import task_writer, database


BG = "#FAFAF7"
SIDEBAR_BG = "#F3F2EC"
BORDER = "#E8E6DD"
BORDER_INPUT = "#DEDCD1"
TEXT_PRIMARY = "#1A1A1A"
TEXT_MUTED = "#8A8880"
COBALT = "#1F3FA8"
GREEN_BG = "#E1F2E3"
GREEN_BORDER = "#2E7D3A"

TASK_TYPE_LABELS = {
    "ser": "Сериализация",
    "gser": "Групповая сериализация",
    "agr": "Агрегация",
}


class _RowBorderDelegate(QStyledItemDelegate):
    """Рисует зелёную рамку вокруг подсвеченной строки (не заливку фона).
    QTableWidgetItem не умеет рисовать рамку сам по себе — обычная
    заливка через setBackground() не даёт настоящего контура, поэтому
    рамка рисуется вручную поверх стандартной отрисовки ячейки."""

    def __init__(self, parent, highlighted_rows_getter, last_data_column: int):
        super().__init__(parent)
        self._highlighted_rows_getter = highlighted_rows_getter
        self._last_data_column = last_data_column

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.row() not in self._highlighted_rows_getter():
            return

        painter.save()
        pen = QPen(QColor(GREEN_BORDER))
        pen.setWidth(2)
        painter.setPen(pen)
        rect = option.rect
        col = index.column()

        painter.drawLine(rect.topLeft(), rect.topRight())
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        if col == 0:
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
        if col == self._last_data_column:
            painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.restore()


class HistoryDialog(QDialog):
    """Окно "История" — список завершённых заданий из
    ./workfolder/tasks/history_tasks/*.json.

    Слева — детали выбранного задания (клик по строке), справа —
    таблица со всеми завершёнными заданиями + поиск по GTIN (подсветка
    совпавших строк) + кнопка восстановления в каждой строке.

    Как и другие диалоги — ничего не знает о том, что происходит с
    файлом дальше, только сообщает наружу через task_resumed, если
    оператор решил продолжить задание.
    """

    task_resumed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("История")
        self.setModal(True)
        self.setFixedSize(900, 450)
        self.setWindowIcon(get_app_icon())

        self._tasks: list[tuple] = []  # [(path, task_dict), ...] по порядку строк таблицы
        self._highlighted_rows: set[int] = set()

        self._build_ui()
        self._apply_styles()
        self._reload_history_table()

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_details_panel())
        root.addWidget(self._build_table_panel(), stretch=1)

    def _build_details_panel(self):
        panel = QFrame()
        panel.setObjectName("detailsPanel")
        panel.setFixedWidth(280)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title = QLabel("Детали задания")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.details_placeholder = QLabel("Выберите задание из списка")
        self.details_placeholder.setObjectName("detailsPlaceholder")
        self.details_placeholder.setWordWrap(True)
        layout.addWidget(self.details_placeholder)

        self.details_fields_box = QVBoxLayout()
        self.details_fields_box.setSpacing(10)
        layout.addLayout(self.details_fields_box)

        layout.addStretch()
        return panel

    def _build_table_panel(self):
        panel = QFrame()
        panel.setObjectName("tablePanel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("Завершённые задания")
        title.setObjectName("panelTitle")
        header_row.addWidget(title)
        header_row.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по номеру задания")
        self.search_input.setFixedWidth(220)
        self.search_input.textChanged.connect(self._on_search_changed)
        header_row.addWidget(self.search_input)
        layout.addLayout(header_row)

        self.history_table = QTableWidget(0, 5)
        self.history_table.setObjectName("historyTable")
        self.history_table.setHorizontalHeaderLabels(
            ["№", "Номер задания", "Имя продукта", "Дата и время завершения", ""]
        )
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.history_table.setShowGrid(False)
        self.history_table.cellClicked.connect(self._on_row_clicked)
        self.history_table.setItemDelegate(
            _RowBorderDelegate(self.history_table, lambda: self._highlighted_rows, last_data_column=3)
        )

        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(0, 50)
        self.history_table.setColumnWidth(1, 100)
        self.history_table.setColumnWidth(3, 150)
        self.history_table.setColumnWidth(4, 44)

        layout.addWidget(self.history_table, stretch=1)
        return panel

    # ------------------------------------------------------------------ #
    def _reload_history_table(self):
        """Читает ./workfolder/tasks/history_tasks/*.json, сортирует по
        finishedAt (новые сверху). Битые/неполные файлы пропускаются."""
        self.history_table.setRowCount(0)
        self._tasks = []
        self._highlighted_rows = set()

        if not task_writer.HISTORY_TASKS_DIR.exists():
            return

        loaded = []
        for path in sorted(task_writer.HISTORY_TASKS_DIR.glob("*.json")):
            task = task_writer.load_history_task(path)
            if task is None or "task_number" not in task:
                continue
            loaded.append((path, task))

        loaded.sort(key=lambda pair: pair[1].get("finishedAt", ""), reverse=True)
        self._tasks = loaded

        for index, (path, task) in enumerate(loaded, start=1):
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            self.history_table.setItem(row, 0, QTableWidgetItem(str(index)))
            self.history_table.setItem(row, 1, QTableWidgetItem(task.get("task_number", "")))
            self.history_table.setItem(row, 2, QTableWidgetItem(task.get("name", "")))
            self.history_table.setItem(
                row, 3, QTableWidgetItem(self._format_timestamp(task.get("finishedAt", "")))
            )
            self.history_table.setCellWidget(row, 4, self._build_restore_button(path, task))

    def _build_restore_button(self, path, task: dict) -> QFrame:
        btn = QPushButton("↺")
        btn.setObjectName("restoreButton")
        btn.setFixedSize(28, 21)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _checked, p=path, t=task: self._on_restore_clicked(p, t))

        wrapper = QFrame()
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrapper_layout.addWidget(btn)
        return wrapper

    @staticmethod
    def _format_timestamp(finished_at: str) -> str:
        """finishedAt хранится как UTC ISO ('...Z'). Переводим в локальное
        время для отображения (та же логика, что при восстановлении
        таблицы кодов в главном окне)."""
        try:
            dt = datetime.strptime(finished_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            return dt.astimezone().strftime("%d.%m.%Y %H:%M:%S")
        except ValueError:
            return finished_at

    # ------------------------------------------------------------------ #
    def _on_row_clicked(self, row: int, _column: int):
        if row < 0 or row >= len(self._tasks):
            return
        _path, task = self._tasks[row]
        self._show_details(task)

    def _show_details(self, task: dict):
        self.details_placeholder.hide()
        self._clear_details_fields()

        type_label = TASK_TYPE_LABELS.get(task.get("task_type"), task.get("task_type", ""))

        rows = [
            ("Номер задания", task.get("task_number", "")),
            ("GTIN", task.get("gtin", "")),
            ("Наименование", task.get("name", "")),
            ("Тип задания", type_label),
        ]
        if task.get("production_date"):
            rows.append(("Дата изготовления", task["production_date"]))
        if task.get("expiration_date"):
            rows.append(("Срок годности", task["expiration_date"]))

        for label_text, value in rows:
            box = QVBoxLayout()
            box.setSpacing(3)
            label = QLabel(label_text)
            label.setObjectName("fieldLabel")
            value_label = QLabel(str(value))
            value_label.setObjectName("fieldValue")
            value_label.setWordWrap(True)
            box.addWidget(label)
            box.addWidget(value_label)
            self.details_fields_box.addLayout(box)

        done_title = QLabel("Выполнено")
        done_title.setObjectName("panelTitle")
        self.details_fields_box.addWidget(done_title)

        units, packages, pallets = self._fetch_task_stats(task.get("task_number", ""))
        for label_text, value in [
            ("Единиц продукции", units),
            ("Упаковок", packages),
            ("Паллет", pallets),
        ]:
            box = QVBoxLayout()
            box.setSpacing(3)
            label = QLabel(label_text)
            label.setObjectName("fieldLabel")
            value_label = QLabel(str(value))
            value_label.setObjectName("fieldValue")
            box.addWidget(label)
            box.addWidget(value_label)
            self.details_fields_box.addLayout(box)

    @staticmethod
    def _fetch_task_stats(task_number: str) -> tuple[int, int, int]:
        """Читает счётчики из БД по номеру задания — та же логика, что
        AppController._refresh_counters() использует для сайдбара
        главного окна во время активного сканирования."""
        if not task_number:
            return 0, 0, 0
        conn = database.get_connection()
        try:
            units = conn.execute(
                "SELECT COUNT(*) FROM scans WHERE task_number = ?", (task_number,)
            ).fetchone()[0]
            packages = conn.execute(
                "SELECT COUNT(DISTINCT package_code) FROM scans WHERE task_number = ?",
                (task_number,),
            ).fetchone()[0]
            pallets = conn.execute(
                "SELECT COUNT(DISTINCT pallet_code) FROM scans WHERE task_number = ?",
                (task_number,),
            ).fetchone()[0]
            return units, packages, pallets
        finally:
            conn.close()

    def _clear_details_fields(self):
        while self.details_fields_box.count():
            item = self.details_fields_box.takeAt(0)

            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                continue

            layout = item.layout()
            if layout is not None:
                while layout.count():
                    sub_item = layout.takeAt(0)
                    sub_widget = sub_item.widget()
                    if sub_widget is not None:
                        sub_widget.deleteLater()

    # ------------------------------------------------------------------ #
    def _on_search_changed(self, text: str):
        query = text.strip()
        self._highlighted_rows = {
            row
            for row, (_path, task) in enumerate(self._tasks)
            if query and query in task.get("task_number", "")
        }
        self.history_table.viewport().update()

    # ------------------------------------------------------------------ #
    def _on_restore_clicked(self, path, task: dict):
        confirmed = MessageDialog.confirm(
            self,
            "Продолжить задание",
            f"Продолжить задание №{task.get('task_number', '')}?\n"
            f"GTIN: {task.get('gtin', '')}\n"
            f"Наименование: {task.get('name', '')}",
            tone="warning",
        )
        if not confirmed:
            return

        restored = task_writer.restore_history_task(path)
        if restored is None:
            MessageDialog.error(
                self,
                "Ошибка восстановления",
                "Не удалось восстановить задание из архива. Подробности — в консоли.",
            )
            return

        self.task_resumed.emit(restored)
        self.accept()

    # ------------------------------------------------------------------ #
    def _apply_styles(self):
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {BG};
            }}
            #detailsPanel {{
                background-color: {SIDEBAR_BG};
                border-right: 1px solid {BORDER};
            }}
            #tablePanel {{
                background-color: {BG};
            }}
            #panelTitle {{
                font-size: 15px;
                font-weight: 700;
                color: {TEXT_PRIMARY};
            }}
            #detailsPlaceholder {{
                font-size: 12px;
                color: {TEXT_MUTED};
            }}
            #fieldLabel {{
                font-size: 11px;
                font-weight: 500;
                color: {TEXT_MUTED};
            }}
            #fieldValue {{
                font-size: 13px;
                color: {TEXT_PRIMARY};
                font-family: "JetBrains Mono", "Consolas", monospace;
            }}
            QLineEdit {{
                height: 33px;
                border: 1px solid {BORDER_INPUT};
                border-radius: 6px;
                padding: 0 9px;
                font-size: 13px;
                background-color: white;
                color: {TEXT_PRIMARY};
            }}
            #historyTable {{
                background-color: white;
                border: 1px solid {BORDER};
                border-radius: 8px;
                font-size: 12px;
                font-family: "JetBrains Mono", "Consolas", monospace;
            }}
            #historyTable::item {{
                padding: 6px 10px;
                border-bottom: 1px solid #F0EFE9;
                color: {TEXT_PRIMARY};
            }}
            QHeaderView::section {{
                background-color: {SIDEBAR_BG};
                color: {TEXT_MUTED};
                border: none;
                border-bottom: 1px solid {BORDER};
                padding: 8px 10px;
                font-size: 11px;
                font-weight: 500;
                font-family: "Inter", sans-serif;
            }}
            #restoreButton {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                font-size: 15px;
                color: {COBALT};
            }}
            #restoreButton:hover {{
                background-color: #E7ECF9;
            }}
            """
        )