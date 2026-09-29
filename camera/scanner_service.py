import socket

from PyQt6.QtCore import QThread, pyqtSignal


BUFFER_SIZE = 4096


class CameraListener(QThread):
    """Слушает TCP-порт камеры в отдельном потоке, чтобы не блокировать UI
    во время ожидания данных (recv() — блокирующий вызов).

    Это первый шаг: подключение + сигналы о состоянии соединения.
    Парсинг сырых сообщений на отдельные коды, буфер, проверка на
    дубли и запись в БД — следующий шаг, сюда пока не входит.
    Поток НИКОГДА не должен трогать базу данных напрямую — только
    эмитить сигналы, которые главный поток (AppController) обрабатывает
    у себя.
    """

    connected = pyqtSignal()
    error = pyqtSignal(str)
    disconnected = pyqtSignal()
    raw_message_received = pyqtSignal(str)

    def __init__(self, ip: str, port: int, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.port = port
        self._running = True
        self._sock = None

    def run(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._sock.settimeout(5)
            self._sock.connect((self.ip, self.port))
            self._sock.settimeout(None)
            self.connected.emit()

            while self._running:
                try:
                    data = self._sock.recv(BUFFER_SIZE)
                except OSError:
                    break
                if not data:
                    break
                message = data.decode("utf-8", errors="replace").strip()
                if message:
                    self.raw_message_received.emit(message)

        except ConnectionRefusedError:
            self.error.emit("Не удалось подключиться. Проверьте IP и порт камеры.")
        except socket.timeout:
            self.error.emit("Превышено время ожидания подключения к камере.")
        except OSError as e:
            self.error.emit(f"Ошибка сети: {e}")
        finally:
            try:
                if self._sock:
                    self._sock.close()
            except OSError:
                pass
            self.disconnected.emit()

    def stop(self):
        """Вызывается из главного потока по кнопке "Стоп". Закрытие сокета
        разблокирует recv() в run(), после чего поток корректно завершится
        (и придёт сигнал disconnected)."""
        self._running = False
        try:
            if self._sock:
                self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
