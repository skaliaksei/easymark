from pathlib import Path

from PyQt6.QtGui import QIcon


ICON_PATH = Path("./img/easymark.ico")


def get_app_icon() -> QIcon:
    """Иконка приложения. Если файла нет на диске — QIcon просто
    останется пустым (Qt не упадёт), окно откроется без иконки."""
    return QIcon(str(ICON_PATH))