import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
)

from ui.app_icon import get_app_icon
from ui.message_dialog import MessageDialog
from ui.scanner_line_edit import GS1LineEdit
from core import database, task_writer
from printing.print_worker import PrintJob, format_gs1_readable


BG = "#FAFAF7"
SIDEBAR_BG = "#F3F2EC"
BORDER = "#E8E6DD"
BORDER_INPUT = "#DEDCD1"
TEXT_PRIMARY = "#1A1A1A"
TEXT_MUTED = "#8A8880"
COBALT = "#1F3FA8"
RUST = "#A63B2B"
GREEN_BORDER = "#2E7D3A"

LEVEL_PRODUCT = "Продукт"
LEVEL_BOX = "Упаковка"
LEVEL_PALLET = "Паллета"

# QTreeWidget не даёт настраивать отступ для отдельной колонки через
# обычный QSS-padding (он действует на всю ячейку разом) — поэтому сдвиг
# кода вправо и прогрессивное увеличение отступа по уровню вложенности
# сделаны через несколько пробелов перед текстом. Точных миллиметров это
# не даёт (зависит от шрифта/DPI), но управляемо через эти константы.
CODE_BASE_INDENT = 1  # общий сдвиг кода вправо на всех уровнях (было 3, убрали 2 по просьбе)
CODE_TAB_INDENT = 4  # доп. отступ за каждый уровень вложенности ("один таб")

# Роль для хранения метаданных узла дерева (код/уровень/дата и т.д.)
NODE_DATA_ROLE = Qt.ItemDataRole.UserRole


class HierarchyDialog(QDialog):
    """Окно "Иерархия" — дерево кодов текущего активного задания.

    Для Агрегации — настоящее раскрывающееся дерево: Паллета → Упаковки →
    Коды продукции. Для Сериализации/Групповой сериализации — плоский
    список (тот же QTreeWidget, просто без дочерних узлов).

    Как и остальные диалоги — сама ничего не решает про завершение
    задания и т.д., только показывает данные и предупреждает через
    MessageDialog, если найденный код принадлежит другому заданию.
    """

    def __init__(self, parent, task: dict, print_queue):
        super().__init__(parent)
        self.task = task
        self.print_queue = print_queue
        self._selected_node_data: dict | None = None
        self.setWindowTitle("Иерархия")
        self.setModal(True)
        self.setFixedSize(900, 450)
        self.setWindowIcon(get_app_icon())

        self._build_ui()
        self._apply_styles()
        self._load_tree()

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_details_panel())
        root.addWidget(self._build_tree_panel(), stretch=1)

    def _build_details_panel(self):
        panel = QFrame()
        panel.setObjectName("detailsPanel")
        panel.setFixedWidth(280)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Детали кода")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.details_placeholder = QLabel("Выберите код в дереве")
        self.details_placeholder.setObjectName("detailsPlaceholder")
        self.details_placeholder.setWordWrap(True)
        layout.addWidget(self.details_placeholder)

        self.details_fields_box = QVBoxLayout()
        self.details_fields_box.setSpacing(12)
        layout.addLayout(self.details_fields_box)

        layout.addStretch()

        self.print_code_btn = QPushButton("Печать кода")
        self.print_code_btn.setObjectName("printCodeButton")
        self.print_code_btn.setFixedHeight(38)
        self.print_code_btn.setEnabled(False)  # активна только когда выбрана упаковка/паллета
        self.print_code_btn.clicked.connect(self._on_print_code_clicked)
        layout.addWidget(self.print_code_btn)

        return panel

    def _build_tree_panel(self):
        panel = QFrame()
        panel.setObjectName("treePanel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        title = QLabel("Иерархия кодов")
        title.setObjectName("panelTitle")
        header_row.addWidget(title)
        header_row.addStretch()

        self.search_input = GS1LineEdit()
        self.search_input.setPlaceholderText("Поиск кода")
        self.search_input.setFixedWidth(260)
        self.search_input.returnPressed.connect(self._on_search)
        self.search_input.textChanged.connect(self._clear_search_state)
        header_row.addWidget(self.search_input)
        layout.addLayout(header_row)

        self.search_error_label = QLabel("Код не найден")
        self.search_error_label.setObjectName("searchErrorLabel")
        self.search_error_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.search_error_label.hide()
        layout.addWidget(self.search_error_label)

        self.tree = QTreeWidget()
        self.tree.setObjectName("hierarchyTree")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 150)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        layout.addWidget(self.tree, stretch=1)

        return panel

    # ------------------------------------------------------------------ #
    def _load_tree(self):
        self.tree.clear()
        self._tree_items_by_code: dict[str, QTreeWidgetItem] = {}
        conn = database.get_connection()
        try:
            task_number = self.task.get("task_number", "")
            if self.task.get("task_type") == "agr":
                self._load_aggregation_tree(conn, task_number)
            else:
                self._load_flat_list(conn, task_number)
        finally:
            conn.close()

    def _load_aggregation_tree(self, conn, task_number: str):
        cur = conn.execute(
            "SELECT code, package_code, pallet_code, scanned_at FROM scans "
            "WHERE task_number = ? ORDER BY id ASC",
            (task_number,),
        )
        # Группируем в памяти, сохраняя порядок первого появления
        # (обычные dict в Python сохраняют порядок вставки).
        pallets: dict[str, dict] = {}
        for code, package_code, pallet_code, scanned_at in cur.fetchall():
            pallet_entry = pallets.setdefault(
                pallet_code, {"first_seen": scanned_at, "boxes": {}}
            )
            box_entry = pallet_entry["boxes"].setdefault(
                package_code, {"first_seen": scanned_at, "codes": []}
            )
            box_entry["codes"].append((code, scanned_at))

        pallet_number = 0
        box_number = 0  # сквозная нумерация упаковок по всему заданию,
                         # НЕ сбрасывается на каждой паллете — совпадает
                         # с порядком, в котором реально назначались
                         # серийники package_code/pallet_code

        for pallet_code, pallet_data in pallets.items():
            pallet_number += 1
            pallet_item = QTreeWidgetItem([f"Паллета {pallet_number}", self._indented_code(pallet_code, 0)])
            self._style_label_cell(pallet_item)
            pallet_item.setData(
                0,
                NODE_DATA_ROLE,
                self._node_data(LEVEL_PALLET, pallet_code, pallet_data["first_seen"]),
            )
            self.tree.addTopLevelItem(pallet_item)
            self._tree_items_by_code[pallet_code] = pallet_item

            for package_code, box_data in pallet_data["boxes"].items():
                box_number += 1
                box_item = QTreeWidgetItem([f"Упаковка {box_number}", self._indented_code(package_code, 1)])
                self._style_label_cell(box_item)
                box_item.setData(
                    0,
                    NODE_DATA_ROLE,
                    self._node_data(LEVEL_BOX, package_code, box_data["first_seen"]),
                )
                pallet_item.addChild(box_item)
                self._tree_items_by_code[package_code] = box_item

                for code, scanned_at in box_data["codes"]:
                    code_item = QTreeWidgetItem(["", self._indented_code(code, 2)])
                    code_item.setData(
                        0, NODE_DATA_ROLE, self._node_data(LEVEL_PRODUCT, code, scanned_at)
                    )
                    box_item.addChild(code_item)
                    self._tree_items_by_code[code] = code_item

    def _load_flat_list(self, conn, task_number: str):
        cur = conn.execute(
            "SELECT code, scanned_at FROM scans WHERE task_number = ? ORDER BY id ASC",
            (task_number,),
        )
        for code, scanned_at in cur.fetchall():
            item = QTreeWidgetItem(["", self._indented_code(code, 0)])
            item.setData(0, NODE_DATA_ROLE, self._node_data(LEVEL_PRODUCT, code, scanned_at))
            self.tree.addTopLevelItem(item)
            self._tree_items_by_code[code] = item

    def _style_label_cell(self, item: QTreeWidgetItem):
        """Подпись "Паллета N"/"Упаковка N" в левой колонке — жирным
        кобальтовым цветом, чтобы визуально отличаться от самого кода
        (правая колонка, обычный моноширинный текст)."""
        item.setForeground(0, QColor(COBALT))
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)

    @staticmethod
    def _indented_code(code: str, depth: int) -> str:
        """Текст кода со сдвигом вправо: базовый отступ на всех уровнях
        (чтобы код не липнул к подписи слева) + доп. отступ за каждый
        уровень вложенности ("один таб" на упаковку, ещё один — на
        код продукции), чтобы визуально была видна глубина иерархии
        даже в самой колонке с кодом, не только по стрелочкам дерева."""
        return " " * (CODE_BASE_INDENT + depth * CODE_TAB_INDENT) + code

    def _node_data(self, level: str, code: str, created_at: str) -> dict:
        return {
            "level": level,
            "code": code,
            "task_number": self.task.get("task_number", ""),
            "created_at": created_at,
        }

    # ------------------------------------------------------------------ #
    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _column: int):
        data = item.data(0, NODE_DATA_ROLE)
        if not data:
            return
        self._selected_node_data = data
        self._show_details(data)
        # "Печать кода" активна только для упаковки/паллеты — у листьев
        # (кодов продукции) собственной этикетки/шаблона нет.
        self.print_code_btn.setEnabled(data["level"] in (LEVEL_BOX, LEVEL_PALLET))

    def _on_print_code_clicked(self):
        """Ручная (пере)печать этикетки уже существующего кода упаковки
        или паллеты — сам код уже лежит в данных выбранного узла (мы его
        туда положили при построении дерева из БД), заново искать не
        нужно. Используем ту же очередь печати, что и живое сканирование —
        чтобы ручная печать и автопечать во время работы камеры не могли
        одновременно уйти на один и тот же принтер."""
        if self._selected_node_data is None:
            return

        level = self._selected_node_data["level"]
        code = self._selected_node_data["code"]

        if level == LEVEL_BOX:
            template_path = self.task.get("box_template", "")
            output_filename = "current_print_box.prn"
        elif level == LEVEL_PALLET:
            template_path = self.task.get("pallet_template", "")
            output_filename = "current_print_pallet.prn"
        else:
            return

        self.print_queue.enqueue(
            PrintJob(
                template_path=template_path,
                output_filename=output_filename,
                gs1_128_value=code.replace("\x1d", "!102"),
                gs1_128_description_value=format_gs1_readable(code),
                print_with_driver=self.task.get("print_with_driver", "true") == "true",
                printer_name=self.task.get("printer_name", ""),
                printer_ip=self.task.get("printer_ip", ""),
                printer_port=self.task.get("printer_port", ""),
            )
        )

    def _show_details(self, data: dict):
        self.details_placeholder.hide()
        self._clear_details_fields()

        rows = [
            ("Код", data["code"]),
            ("Задание", f"№{data['task_number']} — {self.task.get('name', '')}"),
            ("Уровень иерархии", data["level"]),
            ("Дата-время создания", data.get("created_at", "")),
        ]
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
    def _clear_search_state(self):
        self.search_input.setStyleSheet("")
        self.search_error_label.hide()

    @staticmethod
    def _normalize_search_code(raw: str) -> str:
        """Настоящий байт GS (0x1D) почти никогда не переживает
        копирование через буфер обмена — теряется или превращается в
        пробел ещё на стороне источника/самого Qt. Коды маркировки
        никогда не содержат настоящих пробелов, поэтому безопасно
        считать любую пробельную последовательность (сколько бы их ни
        оказалось после вставки) заменой за GS. Заодно поддерживаем наш
        собственный маркер "<GS>" (тот же, что используется в таблице
        главного окна) — на случай, если оператор наберёт его вручную."""
        normalized = raw.replace("<GS>", "\x1d")
        normalized = re.sub(r"\s+", "\x1d", normalized)
        return normalized

    def _on_search(self):
        code = self._normalize_search_code(self.search_input.text().strip())
        if not code:
            return

        conn = database.get_connection()
        try:
            row = conn.execute(
                "SELECT task_number FROM scans "
                "WHERE code = ? OR package_code = ? OR pallet_code = ? LIMIT 1",
                (code, code, code),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            self._show_search_error()
            return

        self._show_search_success()

        found_task_number = row[0]
        current_task_number = self.task.get("task_number", "")
        if found_task_number == current_task_number:
            # Код принадлежит текущему заданию — раскрываем дерево до
            # нужного узла и выделяем его, чтобы оператор сразу видел
            # результат, не разворачивая ветки вручную.
            self._select_in_tree(code)
            self._reset_search_input()
            return

        other_name = self._lookup_task_name(found_task_number)
        MessageDialog.warning(
            self,
            "Код из другого задания",
            f"Внимание, код из задания №{found_task_number} {other_name}.\n"
            "Для работы с найденным кодом, завершите текущее задание, "
            "и войдите в соответствующее.",
        )
        self._reset_search_input()

    def _select_in_tree(self, code: str):
        item = self._tree_items_by_code.get(code)
        if item is None:
            return
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self._on_tree_item_clicked(item, 0)

    def _reset_search_input(self):
        """После успешного поиска очищаем поле и возвращаем в него фокус —
        оператор сразу готов вставить/отсканировать следующий код, не
        кликая по полю заново."""
        self.search_input.clear()
        self.search_input.setFocus()

    @staticmethod
    def _lookup_task_name(task_number: str) -> str:
        """Код с другим task_number всегда принадлежит уже завершённому
        (архивному) заданию — текущее задание всегда ровно одно."""
        path = task_writer.find_history_task(task_number)
        if path is None:
            return ""
        other_task = task_writer.load_history_task(path)
        return other_task.get("name", "") if other_task else ""

    def _show_search_error(self):
        self.search_input.setStyleSheet(f"QLineEdit {{ border: 1px solid {RUST}; }}")
        self.search_error_label.show()

    def _show_search_success(self):
        self.search_input.setStyleSheet(f"QLineEdit {{ border: 1px solid {GREEN_BORDER}; }}")
        self.search_error_label.hide()

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
            #treePanel {{
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
            #searchErrorLabel {{
                font-size: 11px;
                color: {RUST};
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
            #hierarchyTree {{
                background-color: white;
                border: 1px solid {BORDER};
                border-radius: 8px;
                font-size: 12px;
                font-family: "JetBrains Mono", "Consolas", monospace;
                color: {TEXT_PRIMARY};
            }}
            #hierarchyTree::item {{
                padding: 5px 4px;
                border-bottom: 1px solid #F0EFE9;
            }}
            #hierarchyTree::item:selected {{
                background-color: {COBALT};
                color: white;
            }}
            #printCodeButton {{
                background-color: {COBALT};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
            }}
            #printCodeButton:disabled {{
                background-color: #C9CFE3;
                color: #F0F1F8;
            }}
            """
        )