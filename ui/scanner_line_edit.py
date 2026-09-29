from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLineEdit


class GS1LineEdit(QLineEdit):
    """QLineEdit, который не теряет управляющие символы вроде GS (0x1D).

    Проблема: внутри QLineEdit есть встроенный обработчик клавиш
    (QWidgetLineControl::processKeyEvent), который явно отбрасывает
    одиночные управляющие символы с кодом < 0x20 при обычном наборе
    текста — так сделано, чтобы случайно введённые control-коды не
    портили текстовое поле. GS = 0x1D как раз под это подпадает.
    Поэтому даже сканер, работающий в режиме HID-клавиатуры и реально
    посылающий GS как часть последовательности "нажатий" (например,
    через Alt+Numpad), теряет этот символ уже на уровне виджета — уже
    после того, как он дошёл от ОС до Qt.

    Решение: перехватываем событие клавиши ДО того, как оно попадёт во
    внутреннюю логику QLineEdit, и вставляем текст вручную через
    insert() — этот метод такой фильтрации не делает.

    В отличие от исходного примера, Enter здесь НЕ перехватывается и
    НЕ очищает поле сам — просто отдаётся стандартному обработчику,
    чтобы штатный сигнал returnPressed продолжал работать как обычно
    (используется для запуска поиска)."""

    def keyPressEvent(self, event):
        key = event.key()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            super().keyPressEvent(event)
            return

        # Backspace и навигацию отдаём стандартному обработчику как есть.
        if key in (
            Qt.Key.Key_Backspace,
            Qt.Key.Key_Delete,
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
        ):
            super().keyPressEvent(event)
            return

        text = event.text()
        if text:
            # insert() не делает фильтрации control-символов, в отличие
            # от штатного пути processKeyEvent.
            self.insert(text)
            event.accept()
            return

        super().keyPressEvent(event)
