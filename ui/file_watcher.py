"""Файловый монитор для Windows через ReadDirectoryChangesW.

Отслеживает изменения в папке и вызывает callback при создании/удалении файлов.
Работает в отдельном потоке, не блокируя основной поток приложения.
"""
import ctypes
import ctypes.wintypes
import logging
import os
import threading

logger = logging.getLogger("file_watcher")

# Константы для ReadDirectoryChangesW
FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# Notification filters
FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
FILE_NOTIFY_CHANGE_SIZE = 0x00000008


class _FileWatcher:
    """Монитор изменений папки через Windows API."""

    def __init__(self, directory: str, callback: Callable, poll_interval: float = 2.0):
        self._directory = os.path.realpath(directory)
        self._callback = callback
        self._poll_interval = poll_interval
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._handle = None  # ctypes c_void_p
        self._buffer_size = 65536  # 64 KB

    def start(self) -> None:
        """Запустить мониторинг в фоновом потоке."""
        if not os.path.isdir(self._directory):
            logger.warning("Папка не существует для мониторинга: %s", self._directory)
            return

        if self._thread and self._thread.is_alive():
            logger.debug("Мониторинг уже запущен для: %s", self._directory)
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop, daemon=True,
            name=f"FileWatcher-{os.path.basename(self._directory)}",
        )
        self._thread.start()
        logger.info("Мониторинг запущен: %s", self._directory)

    def stop(self) -> None:
        """Остановить мониторинг."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Мониторинг остановлен: %s", self._directory)

    def _watch_loop(self) -> None:
        """Основной цикл мониторинга через ReadDirectoryChangesW."""
        try:
            self._open_directory()
        except OSError as e:
            logger.error("Не удалось открыть папку для мониторинга: %s (%s)", self._directory, e)
            return

        if self._handle is None:
            logger.error("Не удалось получить handle папки: %s", self._directory)
            return

        try:
            self._poll_changes()
        finally:
            self._close_directory()

    def _open_directory(self) -> None:
        """Открыть директорию через CreateFileW."""
        kernel32 = ctypes.windll.kernel32
        h = kernel32.CreateFileW(
            self._directory,
            FILE_LIST_DIRECTORY,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if h == ctypes.c_void_p(-1).value:
            raise OSError(f"CreateFileW failed with error {ctypes.get_last_error()}")
        self._handle = h

    def _close_directory(self) -> None:
        """Закрыть handle директории."""
        if self._handle is not None:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None

    def _poll_changes(self) -> None:
        """Ожидать изменения через ReadDirectoryChangesW."""
        buffer = ctypes.create_string_buffer(self._buffer_size)
        bytes_returned = ctypes.c_ulong(0)

        kernel32 = ctypes.windll.kernel32

        # Структура FILE_NOTIFY_INFORMATION
        # typedef struct _FILE_NOTIFY_INFORMATION {
        #   DWORD NextEntryOffset;
        #   DWORD Action;
        #   DWORD FileNameLength;
        #   WCHAR FileName[1];
        # } FILE_NOTIFY_INFORMATION;

        while not self._stop_event.is_set():
            # Ожидаем одно изменение
            result = kernel32.ReadDirectoryChangesW(
                self._handle,
                ctypes.byref(buffer),
                self._buffer_size,
                ctypes.c_long(1),  # bWatchSubTrees = False
                (FILE_NOTIFY_CHANGE_FILE_NAME | FILE_NOTIFY_CHANGE_DIR_NAME |
                 FILE_NOTIFY_CHANGE_SIZE),
                ctypes.byref(bytes_returned),
                None,
                None,
            )

            if not result:
                error = ctypes.get_last_error()
                if error != 995:  # ERROR_OPERATION_ABORTED (норма при stop)
                    logger.debug("ReadDirectoryChangesW error: %d", error)
                break

            # Парсим результаты изменений
            offset = 0
            while offset < bytes_returned.value:
                # NextEntryOffset
                next_entry = ctypes.cast(
                    ctypes.addressof(buffer) + offset,
                    ctypes.POINTER(ctypes.c_ulong),
                ).contents.value

                # Action
                action_offset = offset + ctypes.sizeof(ctypes.c_ulong)
                action = ctypes.cast(
                    ctypes.addressof(buffer) + action_offset,
                    ctypes.POINTER(ctypes.c_ulong),
                ).contents.value

                # FileNameLength
                len_offset = action_offset + ctypes.sizeof(ctypes.c_ulong)
                file_len = ctypes.cast(
                    ctypes.addressof(buffer) + len_offset,
                    ctypes.POINTER(ctypes.c_ulong),
                ).contents.value

                # FileName (wchar)
                name_offset = len_offset + ctypes.sizeof(ctypes.c_ulong)
                name_buf = ctypes.cast(
                    ctypes.addressof(buffer) + name_offset,
                    ctypes.POINTER(ctypes.c_wchar_p),
                ).contents

                if name_buf:
                    action_str = "created" if action == 1 else "deleted" if action == 2 else "modified"
                    logger.debug("Изменение: %s (%s)", name_buf, action_str)

                # Переходим к следующей записи
                if next_entry == 0:
                    break
                offset += next_entry

            # После получения изменений — с задержкой вызываем callback
            # (чтобы собрать пакет изменений)
            self._stop_event.wait(self._poll_interval)
            if not self._stop_event.is_set():
                try:
                    self._callback()
                except Exception as e:
                    logger.error("Ошибка callback файлового монитора: %s", e)

    def __del__(self) -> None:
        self.stop()


def create_file_watcher(directory: str, callback: Callable, poll_interval: float = 2.0) -> _FileWatcher:
    """Создать и запустить файловый монитор.

    Args:
        directory: путь к папке для мониторинга.
        callback: функция, вызываемая при изменениях (в фоне).
        poll_interval: задержка перед вызовом callback (сек) для пакетирования.

    Returns:
        Объект _FileWatcher.
    """
    watcher = _FileWatcher(directory, callback, poll_interval)
    watcher.start()
    return watcher
