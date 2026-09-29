from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
)

from ui.app_icon import get_app_icon


BG = "#FAFAF7"
TEXT_PRIMARY = "#1A1A1A"
TEXT_SECONDARY = "#5F5E5A"
COBALT = "#1F3FA8"
AMBER_BG = "#FBF1DC"
AMBER_BORDER = "#EAD4A0"
AMBER_TEXT = "#8A6512"
RUST_BG = "#FBE7E5"
RUST_BORDER = "#EFC0BA"
RUST_TEXT = "#8F281E"
GREEN_BG = "#E1F2E3"
GREEN_BORDER = "#B8DFC0"
GREEN_TEXT = "#1E5D28"


# Пресеты внешнего вида в зависимости от смысла сообщения
_TONE_PRESETS = {
    "warning": ("!", AMBER_BG, AMBER_BORDER, AMBER_TEXT),
    "error": ("!", RUST_BG, RUST_BORDER, RUST_TEXT),
    "info": ("i", GREEN_BG, GREEN_BORDER, GREEN_TEXT),
}


class MessageDialog(QDialog):
    """Модальное уведомление в фирменном стиле EasyMark — замена
    стандартному QMessageBox, который выглядит как системное окно
    Windows и выбивается из общего вида приложения.

    tone: 'warning' | 'error' | 'info'
    confirm: если True — вместо одной кнопки ОК показывает Нет/Да
             и возвращает bool через статический метод confirm()
    """

    def __init__(
        self,
        parent,
        title: str,
        message: str,
        tone: str = "warning",
        confirm: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(380)
        self.setWindowIcon(get_app_icon())

        icon_char, icon_bg, icon_border, icon_color = _TONE_PRESETS.get(
            tone, _TONE_PRESETS["warning"]
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        icon = QLabel(icon_char)
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"""
            background-color: {icon_bg};
            border: 1px solid {icon_border};
            color: {icon_color};
            border-radius: 16px;
            font-size: 15px;
            font-weight: 700;
            """
        )
        header_row.addWidget(icon)

        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")
        title_label.setWordWrap(True)
        header_row.addWidget(title_label, stretch=1)
        layout.addLayout(header_row)

        message_label = QLabel(message)
        message_label.setObjectName("dialogMessage")
        message_label.setWordWrap(True)
        layout.addWidget(message_label)

        button_row = QHBoxLayout()
        button_row.addStretch()

        if confirm:
            self.no_btn = QPushButton("Нет")
            self.no_btn.setObjectName("secondaryButton")
            self.no_btn.setFixedSize(96, 36)
            self.no_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.no_btn.clicked.connect(self.reject)
            button_row.addWidget(self.no_btn)

            self.yes_btn = QPushButton("Да")
            self.yes_btn.setObjectName("okButton")
            self.yes_btn.setFixedSize(96, 36)
            self.yes_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.yes_btn.clicked.connect(self.accept)
            self.yes_btn.setDefault(True)
            button_row.addWidget(self.yes_btn)
        else:
            self.ok_btn = QPushButton("ОК")
            self.ok_btn.setObjectName("okButton")
            self.ok_btn.setFixedSize(96, 36)
            self.ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.ok_btn.clicked.connect(self.accept)
            self.ok_btn.setDefault(True)
            button_row.addWidget(self.ok_btn)

        layout.addLayout(button_row)

        self._apply_styles()

    def _apply_styles(self):
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {BG};
            }}
            #dialogTitle {{
                font-size: 15px;
                font-weight: 700;
                color: {TEXT_PRIMARY};
            }}
            #dialogMessage {{
                font-size: 13px;
                color: {TEXT_SECONDARY};
                line-height: 1.4;
            }}
            #okButton {{
                background-color: {COBALT};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
            }}
            #okButton:hover {{
                background-color: #17358F;
            }}
            #secondaryButton {{
                background-color: white;
                color: {TEXT_PRIMARY};
                border: 1px solid #DEDCD1;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
            }}
            #secondaryButton:hover {{
                background-color: #F3F2EC;
            }}
            """
        )

    @staticmethod
    def warning(parent, title: str, message: str):
        MessageDialog(parent, title, message, tone="warning").exec()

    @staticmethod
    def error(parent, title: str, message: str):
        MessageDialog(parent, title, message, tone="error").exec()

    @staticmethod
    def info(parent, title: str, message: str):
        MessageDialog(parent, title, message, tone="info").exec()

    @staticmethod
    def confirm(parent, title: str, message: str, tone: str = "error") -> bool:
        """Показывает диалог Да/Нет, возвращает True если нажали "Да"."""
        dialog = MessageDialog(parent, title, message, tone=tone, confirm=True)
        return dialog.exec() == QDialog.DialogCode.Accepted