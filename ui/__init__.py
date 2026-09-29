from PyQt6.QtWidgets import QMainWindow, QLabel


class MainWindow(QMainWindow):
    """Главное окно EasyMark. Наполнение (сайдбар, таблица, статус)
    добавим следующим шагом — пока минимальная заглушка,
    чтобы main.py можно было запустить и проверить, что окно открывается.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EasyMark – ООО «Мирана»")
        self.resize(900, 460)
        self.setCentralWidget(QLabel("Главное окно — в разработке"))