from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

from ui.app_icon import get_app_icon


# --- Цветовая палитра EasyMark (Concept B) --------------------------------
BG = "#FAFAF7"
SIDEBAR_BG = "#F3F2EC"
BORDER = "#E8E6DD"
BORDER_INPUT = "#DEDCD1"
TEXT_PRIMARY = "#1A1A1A"
TEXT_SECONDARY = "#5F5E5A"
TEXT_MUTED = "#8A8880"
COBALT = "#1F3FA8"
RUST = "#A63B2B"
GREEN = "#3B9E4F"
GREEN_BG = "#E1F2E3"
GREEN_BORDER = "#B8DFC0"
GREEN_TEXT = "#1E5D28"
RED = "#C43A2E"
RED_BG = "#FBE7E5"
RED_BORDER = "#EFC0BA"
RED_TEXT = "#8F281E"
AMBER_BG = "#FBF1DC"
AMBER_BORDER = "#EAD4A0"
AMBER_TEXT = "#8A6512"
GRAY_DOT = "#9A9890"

# Цвета статуса кода в таблице
TABLE_STATUS_COLORS = {
    "GOOD": COBALT,
    "DUPLICATE": AMBER_TEXT,
    "ERROR": RUST,
}


class MainWindow(QMainWindow):
    """Главное окно EasyMark.

    UI ничего не знает о камере/сети — только отображает состояние
    и сообщает наружу о действиях пользователя через сигналы.
    Логика (подключение к камере, обработка кодов) будет жить в
    camera/ и подключаться к этим сигналам и публичным методам снаружи.
    """

    start_stop_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    product_clicked = pyqtSignal()
    finish_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EasyMark v2.1.0")
        self.resize(960, 650)
        self.setMinimumSize(820, 460)
        self.setWindowIcon(get_app_icon())

        self._is_running = False
        self._scan_row_counter = 0

        self._build_ui()
        self._apply_styles()

        # начальные значения
        self.set_camera_connected(False)
        self.set_session_stats(units=0, packages=0, pallets=0)
        self.set_scan_status("idle")

    # ------------------------------------------------------------------ #
    # Построение интерфейса
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._build_sidebar())
        body_layout.addWidget(self._build_main_area(), stretch=1)
        root.addWidget(body, stretch=1)

    def _build_header(self):
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(48)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 0, 18, 0)

        title = QLabel("EasyMark – ООО «Мирана»")
        title.setObjectName("appTitle")
        layout.addWidget(title)
        layout.addStretch()

        self.finish_btn = QPushButton("Завершить задание")
        self.finish_btn.setObjectName("finishButton")
        self.finish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.finish_btn.clicked.connect(self.finish_clicked.emit)
        layout.addWidget(self.finish_btn)

        return header

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(22)

        # --- Оборудование ---
        equip_block = QVBoxLayout()
        equip_block.setSpacing(10)
        equip_label = QLabel("ОБОРУДОВАНИЕ")
        equip_label.setObjectName("sectionLabel")
        equip_block.addWidget(equip_label)

        cam_row = QHBoxLayout()
        cam_row.setSpacing(8)
        self.camera_dot = QLabel()
        self.camera_dot.setFixedSize(9, 9)
        cam_row.addWidget(self.camera_dot)
        cam_text = QLabel("Камера")
        cam_text.setObjectName("cameraLabel")
        cam_row.addWidget(cam_text)
        cam_row.addStretch()
        equip_block.addLayout(cam_row)
        layout.addLayout(equip_block)

        # --- Сессия ---
        session_block = QVBoxLayout()
        session_block.setSpacing(14)
        session_label = QLabel("СЕССИЯ")
        session_label.setObjectName("sectionLabel")
        session_block.addWidget(session_label)

        self.units_value = self._make_stat(session_block, "Единиц продукции")
        self.packages_value = self._make_stat(session_block, "Упаковок")
        self.pallets_value = self._make_stat(session_block, "Паллет")
        layout.addLayout(session_block)

        layout.addStretch()

        # --- Кнопки управления ---
        self.start_stop_btn = QPushButton("Пуск")
        self.start_stop_btn.setObjectName("startButton")
        self.start_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_stop_btn.setFixedHeight(38)
        self.start_stop_btn.clicked.connect(self._on_start_stop_clicked)
        layout.addWidget(self.start_stop_btn)

        self.product_btn = QPushButton("Продукция")
        self.product_btn.setObjectName("settingsButton")
        self.product_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.product_btn.setFixedHeight(36)
        self.product_btn.clicked.connect(self.product_clicked.emit)
        layout.addWidget(self.product_btn)

        self.settings_btn = QPushButton("Настройки")
        self.settings_btn.setObjectName("settingsButton")
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setFixedHeight(36)
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        layout.addWidget(self.settings_btn)

        return sidebar

    def _make_stat(self, parent_layout, label_text):
        box = QVBoxLayout()
        box.setSpacing(2)
        label = QLabel(label_text)
        label.setObjectName("statLabel")
        value = QLabel("0")
        value.setObjectName("statValue")
        box.addWidget(label)
        box.addWidget(value)
        parent_layout.addLayout(box)
        return value

    def _build_main_area(self):
        main = QFrame()
        main.setObjectName("mainArea")

        layout = QVBoxLayout(main)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # --- строка GTIN / продукт / статус сканирования ---
        top_row = QHBoxLayout()

        gtin_box = QVBoxLayout()
        gtin_box.setSpacing(3)
        self.gtin_value = QLabel("—")
        self.gtin_value.setObjectName("gtinValue")
        self.product_name = QLabel("Продукт не выбран")
        self.product_name.setObjectName("productName")
        gtin_box.addWidget(self.gtin_value)
        gtin_box.addWidget(self.product_name)
        top_row.addLayout(gtin_box)
        top_row.addStretch()

        self.scan_status = QFrame()
        self.scan_status.setObjectName("scanStatus")
        status_layout = QVBoxLayout(self.scan_status)
        status_layout.setContentsMargins(16, 8, 16, 8)
        status_layout.setSpacing(2)
        self.scan_status_title = QLabel("ОЖИДАНИЕ")
        self.scan_status_title.setObjectName("scanStatusTitle")
        self.scan_status_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_status_value = QLabel("—")
        self.scan_status_value.setObjectName("scanStatusValue")
        self.scan_status_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.scan_status_title)
        status_layout.addWidget(self.scan_status_value)
        top_row.addWidget(self.scan_status)

        layout.addLayout(top_row)

        # --- таблица кодов ---
        self.table = QTableWidget(0, 4)
        self.table.setObjectName("codesTable")
        self.table.setHorizontalHeaderLabels(["№", "Код", "Статус", "Дата-время"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setShowGrid(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 130)

        layout.addWidget(self.table, stretch=1)

        return main

    # ------------------------------------------------------------------ #
    # Публичные методы — вызываются извне (контроллером/камерой)
    # ------------------------------------------------------------------ #
    def set_camera_connected(self, connected: bool):
        color = GREEN if connected else GRAY_DOT
        self.camera_dot.setStyleSheet(
            f"background-color: {color}; border-radius: 4px;"
        )

    def set_gtin(self, gtin: str, product_name: str):
        self.gtin_value.setText(gtin)
        self.product_name.setText(product_name)

    def set_session_stats(self, units: int, packages: int, pallets: int):
        self.units_value.setText(str(units))
        self.packages_value.setText(str(packages))
        self.pallets_value.setText(str(pallets))

    def set_running(self, running: bool):
        """Вызывается контроллером после того, как процесс реально
        запущен/остановлен (а не сразу по клику на кнопку)."""
        self._is_running = running
        self.start_stop_btn.setEnabled(True)
        if running:
            self.start_stop_btn.setText("Стоп")
            self.start_stop_btn.setObjectName("stopButton")
        else:
            self.start_stop_btn.setText("Пуск")
            self.start_stop_btn.setObjectName("startButton")
        # objectName сменился — перевыпускаем стиль, чтобы применился новый QSS-селектор
        self.start_stop_btn.style().unpolish(self.start_stop_btn)
        self.start_stop_btn.style().polish(self.start_stop_btn)
        self.settings_btn.setEnabled(not running)

    def set_connecting(self, connecting: bool):
        """Промежуточное состояние между кликом на "Пуск" и реальным
        подтверждением подключения (сигналы connected/error из
        CameraListener). Кнопка временно блокируется, чтобы оператор
        не мог кликнуть повторно, пока идёт попытка соединения."""
        if connecting:
            self.start_stop_btn.setText("Подключение...")
            self.start_stop_btn.setEnabled(False)
        else:
            self.start_stop_btn.setEnabled(True)

    def set_scan_status(self, status: str):
        """status: 'idle' | 'good' | 'error' | 'duplicate'"""
        presets = {
            "idle": ("ОЖИДАНИЕ", "—", "#EEEDE5", BORDER_INPUT, TEXT_MUTED),
            "good": ("ГРУППА СЧИТАНА", "OK", GREEN_BG, GREEN_BORDER, GREEN_TEXT),
            "error": ("ОШИБКА", "!", RED_BG, RED_BORDER, RED_TEXT),
            "duplicate": ("ПОВТОРЫ", "!", AMBER_BG, AMBER_BORDER, AMBER_TEXT),
        }
        title, value, bg, border, text_color = presets.get(status, presets["idle"])
        self.scan_status_title.setText(title)
        self.scan_status_value.setText(value)
        self.scan_status.setStyleSheet(
            f"""
            #scanStatus {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
            }}
            """
        )
        self.scan_status_title.setStyleSheet(f"color: {text_color};")
        self.scan_status_value.setStyleSheet(f"color: {text_color};")

    def add_scan_row(self, code: str, status: str, timestamp: str):
        """Добавляет строку в таблицу СВЕРХУ (новые коды всегда над старыми).
        status: 'GOOD' | 'DUPLICATE' | 'ERROR'.
        № — отдельный растущий счётчик по порядку сканирования, не привязан
        к визуальной позиции строки (иначе при вставке сверху нумерация
        шла бы в обратную сторону)."""
        self._scan_row_counter += 1
        self.table.insertRow(0)

        self.table.setItem(0, 0, QTableWidgetItem(str(self._scan_row_counter)))
        self.table.setItem(0, 1, QTableWidgetItem(code))

        status_item = QTableWidgetItem(status)
        color_hex = TABLE_STATUS_COLORS.get(status)
        if color_hex:
            status_item.setForeground(QColor(color_hex))
        self.table.setItem(0, 2, status_item)

        self.table.setItem(0, 3, QTableWidgetItem(timestamp))
        self.table.scrollToTop()

    def clear_table(self):
        self.table.setRowCount(0)
        self._scan_row_counter = 0

    # ------------------------------------------------------------------ #
    # Внутренние обработчики
    # ------------------------------------------------------------------ #
    def _on_start_stop_clicked(self):
        # UI сам не решает, запущен процесс или нет — просто сообщает
        # наружу о клике. Реальное состояние подтвердит контроллер
        # через set_running(), когда камера действительно подключится/отключится.
        self.start_stop_clicked.emit()

    # ------------------------------------------------------------------ #
    # Стили
    # ------------------------------------------------------------------ #
    def _apply_styles(self):
        self.setStyleSheet(
            f"""
            #central {{
                background-color: {BG};
            }}
            #header {{
                background-color: #FFFFFF;
                border-bottom: 1px solid {BORDER};
            }}
            #appTitle {{
                font-size: 15px;
                font-weight: 700;
                color: {TEXT_PRIMARY};
            }}
            #finishButton {{
                background-color: transparent;
                color: {RUST};
                border: 1px solid #E8B4AC;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            #finishButton:hover {{
                background-color: #FBEDEA;
            }}
            #sidebar {{
                background-color: {SIDEBAR_BG};
                border-right: 1px solid {BORDER};
            }}
            #sectionLabel {{
                font-size: 11px;
                font-weight: 500;
                color: {TEXT_MUTED};
                letter-spacing: 0.5px;
            }}
            #cameraLabel {{
                font-size: 13px;
                color: {TEXT_PRIMARY};
            }}
            #statLabel {{
                font-size: 11px;
                color: {TEXT_MUTED};
            }}
            #statValue {{
                font-size: 22px;
                font-weight: 500;
                color: {TEXT_PRIMARY};
                font-family: "JetBrains Mono", "Consolas", monospace;
            }}
            #startButton {{
                background-color: {COBALT};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
            }}
            #startButton:hover {{
                background-color: #17358F;
            }}
            #startButton:disabled {{
                background-color: #9AA9D6;
                color: #F0F1F8;
            }}
            #stopButton {{
                background-color: {RED};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
            }}
            #stopButton:hover {{
                background-color: #A9301F;
            }}
            #stopButton:disabled {{
                background-color: #E3A69E;
                color: #FBEDEA;
            }}
            #settingsButton {{
                background-color: white;
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_INPUT};
                border-radius: 6px;
                font-size: 13px;
            }}
            #settingsButton:disabled {{
                color: {TEXT_MUTED};
                background-color: #FAFAF7;
            }}
            #settingsButton:hover:!disabled {{
                background-color: #F3F2EC;
            }}
            #mainArea {{
                background-color: {BG};
            }}
            #gtinValue {{
                font-size: 15px;
                color: {TEXT_PRIMARY};
                font-family: "JetBrains Mono", "Consolas", monospace;
            }}
            #productName {{
                font-size: 12px;
                color: {TEXT_SECONDARY};
            }}
            #scanStatusTitle {{
                font-size: 10px;
                font-weight: 500;
                letter-spacing: 0.5px;
            }}
            #scanStatusValue {{
                font-size: 16px;
                font-weight: 500;
                font-family: "JetBrains Mono", "Consolas", monospace;
            }}
            #codesTable {{
                background-color: white;
                border: 1px solid {BORDER};
                border-radius: 8px;
                font-size: 12px;
                font-family: "JetBrains Mono", "Consolas", monospace;
            }}
            #codesTable::item {{
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
            """
        )