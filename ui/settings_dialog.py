import json
from pathlib import Path

from PyQt6.QtCore import Qt, QDate, QRegularExpression, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QComboBox,
    QDateEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QRadioButton,
    QButtonGroup,
    QFileDialog,
)

from ui.app_icon import get_app_icon
from ui.message_dialog import MessageDialog
from core import task_writer


BG = "#FAFAF7"
BOX_BG = "#F3F2EC"
BORDER_INPUT = "#DEDCD1"
TEXT_PRIMARY = "#1A1A1A"
TEXT_MUTED = "#8A8880"
COBALT = "#1F3FA8"
RUST = "#A63B2B"


# Типы рабочего задания
TYPE_SERIALIZATION = "serialization"
TYPE_GROUP_SERIALIZATION = "group_serialization"
TYPE_AGGREGATION = "aggregation"

WORK_ORDER_TYPES = [
    (TYPE_SERIALIZATION, "Сериализация"),
    (TYPE_GROUP_SERIALIZATION, "Групповая сериализация"),
    (TYPE_AGGREGATION, "Агрегация"),
]


class SettingsDialog(QDialog):
    """Модальное окно "Новое рабочее задание".

    Набор видимых полей зависит от выбранного типа задания:
      - Сериализация: только GTIN + номер задания + оборудование
      - Групповая сериализация: + "Единиц в упаковке"
      - Агрегация: + даты, "Единиц в упаковке", "Упаковок в паллете",
        шаблоны упаковки/паллеты

    Как и раньше, окно ничего не знает о камере/файлах — просто
    собирает данные и отдаёт наружу через work_order_created.
    """

    work_order_created = pyqtSignal(dict)
    task_resumed = pyqtSignal(dict)

    PRODUCTS_DIR = Path("./workfolder/products")
    SETTINGS_FILE = Path("./workfolder/settings/settings.json")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новое рабочее задание")
        self.setModal(True)
        self.setFixedWidth(480)
        self.setWindowIcon(get_app_icon())

        self._build_ui()
        self._apply_styles()

        self._on_type_changed()

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        layout.addWidget(self._field("GTIN", self._build_gtin_combo()))

        self.order_number_input = QLineEdit()
        self.order_number_input.setPlaceholderText("005")
        self.order_number_input.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^[0-9]{0,8}$"))
        )
        self.order_number_input.textChanged.connect(self._clear_order_number_error)
        layout.addWidget(self._field("Номер рабочего задания", self.order_number_input))

        self.type_combo = QComboBox()
        for _, label in WORK_ORDER_TYPES:
            self.type_combo.addItem(label)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addWidget(self._field("Тип рабочего задания", self.type_combo))

        # --- поля для "Групповая сериализация" ---
        self.group_box = QFrame()
        group_layout = QVBoxLayout(self.group_box)
        group_layout.setContentsMargins(0, 0, 0, 0)
        self.units_per_package_input_group = QLineEdit("20")
        group_layout.addWidget(self._field("Единиц в упаковке", self.units_per_package_input_group))
        layout.addWidget(self.group_box)

        # --- поля для "Агрегация" ---
        self.aggregation_box = QFrame()
        self.aggregation_box.setObjectName("aggregationBox")
        agg_layout = QVBoxLayout(self.aggregation_box)
        agg_layout.setContentsMargins(13, 13, 13, 13)
        agg_layout.setSpacing(11)

        dates_row = QHBoxLayout()
        dates_row.setSpacing(10)
        self.production_date = QDateEdit()
        self.production_date.setCalendarPopup(True)
        self.production_date.setDate(QDate.currentDate())
        self.expiry_date = QDateEdit()
        self.expiry_date.setCalendarPopup(True)
        self.expiry_date.setDate(QDate.currentDate().addMonths(6))
        dates_row.addWidget(self._field("Дата производства", self.production_date))
        dates_row.addWidget(self._field("Годен до", self.expiry_date))
        agg_layout.addLayout(dates_row)

        qty_row = QHBoxLayout()
        qty_row.setSpacing(10)
        self.units_per_package_input_agg = QLineEdit("20")
        self.packages_per_pallet_input = QLineEdit("10")
        qty_row.addWidget(self._field("Единиц в упаковке", self.units_per_package_input_agg))
        qty_row.addWidget(self._field("Упаковок в паллете", self.packages_per_pallet_input))
        agg_layout.addLayout(qty_row)

        agg_layout.addWidget(self._field("Шаблон упаковки", self._browse_row("packaging_template_input")))
        agg_layout.addWidget(self._field("Шаблон паллеты", self._browse_row("pallet_template_input")))

        layout.addWidget(self.aggregation_box)

        # --- оборудование (всегда видно) ---
        equip_label = QLabel("ОБОРУДОВАНИЕ")
        equip_label.setObjectName("sectionLabel")
        layout.addWidget(equip_label)

        camera_label = QLabel("КАМЕРА")
        camera_label.setObjectName("sectionLabel")
        layout.addWidget(camera_label)

        camera_row = QHBoxLayout()
        camera_row.setSpacing(6)
        self.camera_ip_input = QLineEdit()
        self.camera_port_input = QLineEdit()
        self.camera_port_input.setFixedWidth(70)
        camera_row.addWidget(self._field("IP-адрес:", self.camera_ip_input))
        camera_row.addWidget(self._field("Порт:", self.camera_port_input))
        layout.addLayout(camera_row)

        printer_label = QLabel("ПРИНТЕР")
        printer_label.setObjectName("sectionLabel")
        layout.addWidget(printer_label)

        printer_row = QHBoxLayout()
        printer_row.setSpacing(6)
        self.printer_name_input = QLineEdit()
        self.printer_ip_input = QLineEdit()
        self.printer_port_input = QLineEdit()
        self.printer_port_input.setFixedWidth(70)
        printer_row.addWidget(self._field("Имя:", self.printer_name_input))
        printer_row.addWidget(self._field("IP-адрес:", self.printer_ip_input))
        printer_row.addWidget(self._field("Порт:", self.printer_port_input))
        layout.addLayout(printer_row)

        self.print_driver_radio = QRadioButton("Печать через драйвер")
        self.print_ip_radio = QRadioButton("Печать через IP")
        self.print_driver_radio.setChecked(True)

        self.print_method_group = QButtonGroup(self)
        self.print_method_group.addButton(self.print_driver_radio)
        self.print_method_group.addButton(self.print_ip_radio)

        print_method_box = QVBoxLayout()
        print_method_box.setSpacing(6)
        print_method_box.addWidget(self.print_driver_radio)
        print_method_box.addWidget(self.print_ip_radio)
        layout.addLayout(print_method_box)

        self._apply_equipment_settings()

        self.gtin_combo.currentIndexChanged.connect(self._update_template_placeholders)
        self._update_template_placeholders()

        self.create_btn = QPushButton("Создать рабочее задание")
        self.create_btn.setObjectName("createButton")
        self.create_btn.setFixedHeight(40)
        self.create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_btn.clicked.connect(self._on_create_clicked)
        layout.addWidget(self.create_btn)

    def _apply_equipment_settings(self):
        settings = self._load_equipment_settings()
        self.camera_ip_input.setText(settings.get("camera_ip", ""))
        self.camera_port_input.setText(settings.get("camera_port", ""))
        self.printer_name_input.setText(settings.get("printer_name", ""))
        self.printer_ip_input.setText(settings.get("printer_ip", ""))
        self.printer_port_input.setText(settings.get("printer_port", ""))

    def _update_template_placeholders(self):
        """Поля шаблонов упаковки/паллеты заполняются реальным значением
        из файла выбранного продукта (box_template/pallet_template).
        Если продукт не выбран или в его файле нет этих полей —
        поле остаётся пустым, а плейсхолдер показывает "Файл не выбран"."""
        product = self.gtin_combo.currentData() or {}
        self.packaging_template_input.setText(product.get("box_template", ""))
        self.pallet_template_input.setText(product.get("pallet_template", ""))

    def _field(self, label_text, widget):
        box = QFrame()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(5)
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        box_layout.addWidget(label)
        box_layout.addWidget(widget)
        return box

    def _load_products(self) -> list[dict]:
        """Читает все *.json файлы из PRODUCTS_DIR и возвращает список
        продуктов вида {"gtin": ..., "itf-14": ..., "name": ...}.
        Файлы без обязательных полей gtin/name или с битым JSON
        пропускаются (не должны ронять приложение)."""
        products = []
        if not self.PRODUCTS_DIR.exists():
            return products

        for path in sorted(self.PRODUCTS_DIR.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[SettingsDialog] Не удалось прочитать {path}: {e}")
                continue

            if "gtin" not in data or "name" not in data:
                print(f"[SettingsDialog] В файле {path} нет обязательных полей gtin/name — пропущен")
                continue

            products.append(data)

        products.sort(key=lambda p: p["name"].lower())
        return products

    def _load_equipment_settings(self) -> dict:
        """Читает ./workfolder/settings/settings.json с настройками
        камеры и принтера. Если файла нет или он битый — возвращает
        пустой словарь, поля просто останутся пустыми."""
        if not self.SETTINGS_FILE.exists():
            return {}
        try:
            with open(self.SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[SettingsDialog] Не удалось прочитать {self.SETTINGS_FILE}: {e}")
            return {}

    def _build_gtin_combo(self):
        self.gtin_combo = QComboBox()
        products = self._load_products()

        if not products:
            self.gtin_combo.addItem("Нет доступных продуктов", userData=None)
            self.gtin_combo.setEnabled(False)
        else:
            for product in products:
                label = f"{product['gtin']} – {product['name']}"
                self.gtin_combo.addItem(label, userData=product)
            self.gtin_combo.setPlaceholderText("Выберите продукт")
            self.gtin_combo.setCurrentIndex(-1)

        self.gtin_combo.currentIndexChanged.connect(self._clear_gtin_error)
        return self.gtin_combo

    def _browse_row(self, attr_name):
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        line_edit = QLineEdit()
        line_edit.setPlaceholderText("Файл не выбран")
        setattr(self, attr_name, line_edit)

        browse_btn = QPushButton("Обзор")
        browse_btn.setObjectName("browseButton")
        browse_btn.setFixedWidth(64)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(lambda: self._on_browse_clicked(line_edit))

        row_layout.addWidget(line_edit)
        row_layout.addWidget(browse_btn)
        return row

    def _on_browse_clicked(self, line_edit: QLineEdit):
        start_dir = str(Path(line_edit.text()).parent) if line_edit.text() else ""
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Выберите файл шаблона этикетки",
            start_dir,
            "Шаблоны этикеток (*.prn);;Все файлы (*)",
        )
        if path:
            line_edit.setText(path)

    # ------------------------------------------------------------------ #
    def _current_type(self) -> str:
        return WORK_ORDER_TYPES[self.type_combo.currentIndex()][0]

    def _on_type_changed(self):
        current = self._current_type()
        self.group_box.setVisible(current == TYPE_GROUP_SERIALIZATION)
        self.aggregation_box.setVisible(current == TYPE_AGGREGATION)
        self.adjustSize()

    def _on_create_clicked(self):
        product = self.gtin_combo.currentData()
        order_number = self.order_number_input.text().strip()

        has_error = False
        if product is None:
            self._show_gtin_error()
            has_error = True
        if not order_number:
            self._show_order_number_error()
            has_error = True
        if has_error:
            return

        history_path = task_writer.find_history_task(order_number)
        if history_path is not None:
            history_task = task_writer.load_history_task(history_path)
            if history_task is not None:
                confirmed = MessageDialog.confirm(
                    self,
                    "Повторное задание",
                    f"Внимание! Задание с номером {order_number} ранее было выполнено.\n"
                    f"GTIN: {history_task.get('gtin', '')}\n"
                    f"Name: {history_task.get('name', '')}\n"
                    "Хотите его продолжить?",
                    tone="warning",
                )
                if not confirmed:
                    self._show_order_number_error()
                    return

                restored = task_writer.restore_history_task(history_path)
                if restored is None:
                    MessageDialog.error(
                        self,
                        "Ошибка восстановления",
                        "Не удалось восстановить задание из архива. Подробности — в консоли.",
                    )
                    return

                self.task_resumed.emit(restored)
                self.accept()
                return

        current = self._current_type()

        data = {
            "gtin": product.get("gtin"),
            "itf14": product.get("itf-14"),
            "product_name": product.get("name", ""),
            "order_number": order_number,
            "work_order_type": current,
            "camera_ip": self.camera_ip_input.text().strip(),
            "camera_port": self.camera_port_input.text().strip(),
            "printer_name": self.printer_name_input.text().strip(),
            "printer_ip": self.printer_ip_input.text().strip(),
            "printer_port": self.printer_port_input.text().strip(),
            "print_with_driver": "true" if self.print_driver_radio.isChecked() else "false",
        }

        if current == TYPE_GROUP_SERIALIZATION:
            data["units_per_package"] = self.units_per_package_input_group.text().strip()

        elif current == TYPE_AGGREGATION:
            data.update(
                {
                    "production_date": self.production_date.date().toString("yyyy-MM-dd"),
                    "expiry_date": self.expiry_date.date().toString("yyyy-MM-dd"),
                    "units_per_package": self.units_per_package_input_agg.text().strip(),
                    "packages_per_pallet": self.packages_per_pallet_input.text().strip(),
                    "packaging_template_path": self.packaging_template_input.text().strip(),
                    "pallet_template_path": self.pallet_template_input.text().strip(),
                }
            )

        self.work_order_created.emit(data)
        self.accept()

    def _show_gtin_error(self):
        self.gtin_combo.setStyleSheet(
            f"QComboBox {{ border: 1px solid {RUST}; }}"
        )
        self.gtin_combo.setFocus()

    def _clear_gtin_error(self):
        self.gtin_combo.setStyleSheet("")

    def _show_order_number_error(self):
        self.order_number_input.setStyleSheet(
            f"QLineEdit {{ border: 1px solid {RUST}; }}"
        )
        self.order_number_input.setFocus()

    def _clear_order_number_error(self):
        self.order_number_input.setStyleSheet("")

    # ------------------------------------------------------------------ #
    def _apply_styles(self):
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {BG};
            }}
            #fieldLabel {{
                font-size: 11px;
                font-weight: 500;
                color: {TEXT_MUTED};
            }}
            #sectionLabel {{
                font-size: 11px;
                font-weight: 500;
                color: {TEXT_MUTED};
                letter-spacing: 0.5px;
            }}
            QLineEdit, QComboBox, QDateEdit {{
                height: 33px;
                border: 1px solid {BORDER_INPUT};
                border-radius: 6px;
                padding: 0 9px;
                font-size: 13px;
                background-color: white;
                color: {TEXT_PRIMARY};
            }}
            QComboBox QAbstractItemView {{
                background-color: black;
                color: white;
                selection-background-color: #3A3A3A;
                selection-color: white;
                border: 1px solid black;
                outline: none;
            }}
            QRadioButton {{
                font-size: 13px;
                color: {TEXT_PRIMARY};
                spacing: 8px;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 1px solid {BORDER_INPUT};
                background-color: white;
            }}
            QRadioButton::indicator:checked {{
                border: 1px solid {COBALT};
                background-color: qradialgradient(
                    cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                    stop:0 {COBALT}, stop:0.45 {COBALT}, stop:0.5 white, stop:1 white
                );
            }}
            #aggregationBox {{
                background-color: {BOX_BG};
                border-radius: 8px;
            }}
            #aggregationBox QLineEdit {{
                background-color: white;
            }}
            #browseButton {{
                height: 31px;
                border: 1px solid {BORDER_INPUT};
                border-radius: 6px;
                background-color: white;
                font-size: 12px;
                color: {TEXT_MUTED};
            }}
            #createButton {{
                background-color: {COBALT};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
            }}
            #createButton:hover {{
                background-color: #17358F;
            }}
            """
        )