import json
from pathlib import Path

from PyQt6.QtCore import Qt, QRegularExpression, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator
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
    QFileDialog,
)

from ui.app_icon import get_app_icon
from ui.message_dialog import MessageDialog


BG = "#FAFAF7"
SIDEBAR_BG = "#F3F2EC"
BORDER = "#E8E6DD"
BORDER_INPUT = "#DEDCD1"
TEXT_PRIMARY = "#1A1A1A"
TEXT_MUTED = "#8A8880"
COBALT = "#1F3FA8"
RUST = "#A63B2B"

DEFAULT_BOX_TEMPLATE = r"C:/files/template_files/Template_box.prn"
DEFAULT_PALLET_TEMPLATE = r"C:/files/template_files/Template_pallet.prn"


class ProductDialog(QDialog):
    """Окно "Продукция".

    Слева — форма создания нового продукта (без изменений по составу
    полей). Справа — таблица со всей номенклатурой из
    ./workfolder/products/*.json, перечитывается заново каждый раз
    при открытии окна.

    Как и другие диалоги — ничего не знает о том, что происходит с
    файлом дальше, только сообщает наружу через product_created.
    """

    product_created = pyqtSignal(dict)

    PRODUCTS_DIR = Path("./workfolder/products")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Продукция")
        self.setModal(True)
        self.setFixedSize(900, 560)
        self.setWindowIcon(get_app_icon())

        self._build_ui()
        self._apply_styles()
        self._reload_products_table()

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_form_panel())
        root.addWidget(self._build_table_panel(), stretch=1)

    def _build_form_panel(self):
        panel = QFrame()
        panel.setObjectName("formPanel")
        panel.setFixedWidth(310)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel("Новый продукт")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        digits_validator = QRegularExpressionValidator(
            QRegularExpression(r"^[0-9]{0,14}$")
        )

        self.gtin_input = QLineEdit()
        self.gtin_input.setPlaceholderText("04810389004065")
        self.gtin_input.setValidator(digits_validator)
        self.gtin_input.textChanged.connect(self._clear_gtin_error)
        layout.addWidget(self._field("GTIN", self.gtin_input))

        self.itf14_input = QLineEdit()
        self.itf14_input.setPlaceholderText("14810389004062")
        self.itf14_input.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^[0-9]{0,14}$"))
        )
        self.itf14_input.textChanged.connect(self._clear_itf14_error)
        layout.addWidget(self._field("ITF-14", self.itf14_input))

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Хрен столовый острый")
        self.name_input.textChanged.connect(self._clear_name_error)
        layout.addWidget(self._field("Название", self.name_input))

        self.fullname_input = QLineEdit()
        self.fullname_input.setPlaceholderText(
            "Хрен ORA СТОЛОВЫЙ ОСТРЫЙ в стеклянной банке твист-офф"
        )
        layout.addWidget(self._field("Полное название", self.fullname_input))

        layout.addWidget(
            self._field("Шаблон упаковки", self._browse_row("box_template_input", DEFAULT_BOX_TEMPLATE))
        )
        layout.addWidget(
            self._field("Шаблон паллеты", self._browse_row("pallet_template_input", DEFAULT_PALLET_TEMPLATE))
        )

        layout.addStretch()

        self.create_btn = QPushButton("Создать продукт")
        self.create_btn.setObjectName("createButton")
        self.create_btn.setFixedHeight(40)
        self.create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_btn.clicked.connect(self._on_create_clicked)
        layout.addWidget(self.create_btn)

        return panel

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

    def _browse_row(self, attr_name: str, default_path: str) -> QFrame:
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        line_edit = QLineEdit()
        line_edit.setText(default_path)
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

    def _build_table_panel(self):
        panel = QFrame()
        panel.setObjectName("tablePanel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Вся продукция")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.products_table = QTableWidget(0, 5)
        self.products_table.setObjectName("productsTable")
        self.products_table.setHorizontalHeaderLabels(
            ["№", "Наименование", "GTIN", "ITF-14", ""]
        )
        self.products_table.verticalHeader().setVisible(False)
        self.products_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.products_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.products_table.setShowGrid(False)

        header = self.products_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.products_table.setColumnWidth(0, 40)
        self.products_table.setColumnWidth(2, 130)
        self.products_table.setColumnWidth(3, 130)
        self.products_table.setColumnWidth(4, 44)

        layout.addWidget(self.products_table, stretch=1)

        return panel

    # ------------------------------------------------------------------ #
    def _reload_products_table(self):
        """Читает ./workfolder/products/*.json и заполняет таблицу.
        Битые файлы или файлы без обязательных полей пропускаются,
        не роняя окно."""
        self.products_table.setRowCount(0)

        if not self.PRODUCTS_DIR.exists():
            return

        products = []
        for path in sorted(self.PRODUCTS_DIR.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[ProductDialog] Не удалось прочитать {path}: {e}")
                continue

            if "gtin" not in data or "name" not in data:
                print(f"[ProductDialog] В файле {path} нет обязательных полей gtin/name — пропущен")
                continue

            products.append(data)

        products.sort(key=lambda p: p["name"].lower())
        print(f"[ProductDialog] Загружено продуктов: {len(products)} из {self.PRODUCTS_DIR.resolve()}")

        for index, product in enumerate(products, start=1):
            row = self.products_table.rowCount()
            self.products_table.insertRow(row)
            self.products_table.setItem(row, 0, QTableWidgetItem(str(index)))
            self.products_table.setItem(row, 1, QTableWidgetItem(product.get("name", "")))
            self.products_table.setItem(row, 2, QTableWidgetItem(product.get("gtin", "")))
            self.products_table.setItem(row, 3, QTableWidgetItem(product.get("itf-14", "")))
            self.products_table.setCellWidget(row, 4, self._build_delete_button(product))

    def _build_delete_button(self, product: dict) -> QPushButton:
        btn = QPushButton("🚫")
        btn.setObjectName("deleteButton")
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(
            lambda _checked, p=product: self._on_delete_clicked(p)
        )
        # Кнопка кладётся в контейнер, чтобы центрироваться в ячейке
        wrapper = QFrame()
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrapper_layout.addWidget(btn)
        return wrapper

    def _on_delete_clicked(self, product: dict):
        confirmed = MessageDialog.confirm(
            self,
            "Удалить продукт",
            f"Удалить продукт: {product.get('name', '')}\nGTIN: {product.get('gtin', '')}",
        )
        if not confirmed:
            return

        target_path = self.PRODUCTS_DIR / f"{product.get('gtin', '')}.json"
        try:
            target_path.unlink(missing_ok=True)
        except OSError as e:
            print(f"[ProductDialog] Не удалось удалить {target_path}: {e}")
            return

        self._reload_products_table()

    # ------------------------------------------------------------------ #
    def _on_create_clicked(self):
        gtin = self.gtin_input.text().strip()
        name = self.name_input.text().strip()
        itf14 = self.itf14_input.text().strip()
        fullname = self.fullname_input.text().strip()

        has_error = False
        if len(gtin) != 14:
            self._show_gtin_error()
            has_error = True
        if not name:
            self._show_name_error()
            has_error = True
        if itf14 and len(itf14) != 14:
            self._show_itf14_error()
            has_error = True
        if has_error:
            return

        target_path = self.PRODUCTS_DIR / f"{gtin}.json"
        if target_path.exists():
            self._show_gtin_error()
            MessageDialog.error(
                self,
                "Продукт уже существует",
                f"Продукт с GTIN {gtin} уже существует.",
            )
            return

        product = {
            "gtin": gtin,
            "itf-14": itf14 if itf14 else gtin,
            "name": name,
            "fullname": fullname if fullname else name,
            "box_template": self.box_template_input.text().strip(),
            "pallet_template": self.pallet_template_input.text().strip(),
        }

        try:
            self.PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(product, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[ProductDialog] Не удалось записать {target_path}: {e}")
            return

        self.product_created.emit(product)
        self.accept()

    def _show_gtin_error(self):
        self.gtin_input.setStyleSheet(f"QLineEdit {{ border: 1px solid {RUST}; }}")
        self.gtin_input.setFocus()

    def _clear_gtin_error(self):
        self.gtin_input.setStyleSheet("")

    def _show_name_error(self):
        self.name_input.setStyleSheet(f"QLineEdit {{ border: 1px solid {RUST}; }}")

    def _clear_name_error(self):
        self.name_input.setStyleSheet("")

    def _show_itf14_error(self):
        self.itf14_input.setStyleSheet(f"QLineEdit {{ border: 1px solid {RUST}; }}")

    def _clear_itf14_error(self):
        self.itf14_input.setStyleSheet("")

    # ------------------------------------------------------------------ #
    def _apply_styles(self):
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {BG};
            }}
            #formPanel {{
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
            #fieldLabel {{
                font-size: 11px;
                font-weight: 500;
                color: {TEXT_MUTED};
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
            #productsTable {{
                background-color: white;
                border: 1px solid {BORDER};
                border-radius: 8px;
                font-size: 12px;
                font-family: "JetBrains Mono", "Consolas", monospace;
            }}
            #productsTable::item {{
                padding: 6px 10px;
                border-bottom: 1px solid #F0EFE9;
                color: {TEXT_PRIMARY};
            }}
            #deleteButton {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                padding-top: -12px;
            }}
            #deleteButton:hover {{
                background-color: #FBE7E5;
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