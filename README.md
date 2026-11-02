# MAX Messenger Bot Receiver

Бот-получатель для MAX Messenger, который сохраняетincoming сообщения и вложения в локальную базу данных SQLite.

## Возможности

- ✅ Long polling обновлений из MAX API (`platform-api2.max.ru`)
- ✅ Сохранение текстовых сообщений и вложений в SQLite
- ✅ Шифрование токена через DPAPI (Windows)
- ✅ **Новое:** Structured logging (logging вместо print)
- ✅ **Новое:** Graceful shutdown (SIGINT/SIGTERM/SIGBREAK)
- ✅ **Новое:** Split текста >4000 символов
- ✅ **Новое:** Inline-кнопки и callback handlers
- ✅ **Новое:** Health check endpoint для мониторинга
- ✅ **Новое:** Retry logic для `attachment.not.ready`
- ✅ **Новое:** Экспоненциальный backoff при ошибках
- ✅ Rate limiting (30 req/s)

## Установка

### 1. Клонируйте репозиторий

```bash
git clone <your-repo-url>
cd my_note
```

### 2. Установите зависимости

```bash
pip install requests
```

### 3. Настройте CA сертификат

MAX API использует сертификат от Минцифры России. Скачайте его:

```bash
curl -fsSL -o russian_trusted_root_ca.pem https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
```

Или используйте уже существующий `combined_ca.pem`.

### 4. Настройте токен

```bash
python bot_receiver.py --configure-token
```

Или установите переменную окружения:

```bash
set MAX_BOT_TOKEN=your_token_here
```

### 5. (Опционально) Настройте config.json

Отредактируйте `config.json` для изменения параметров:

```json
{
    "api": {
        "base_url": "https://platform-api2.max.ru",
        "rate_limit_rps": 30
    },
    "health_check": {
        "enabled": true,
        "port": 8080
    }
}
```

## Использование

### Запуск бота

```bash
python bot_receiver.py
```

### Запуск с параметрами

```bash
# С настройкой уровня логирования
python bot_receiver.py --log-level DEBUG

# С включённым health check
python bot_receiver.py --health-port 8080

# Все параметры вместе
python bot_receiver.py --log-level DEBUG --health-port 8080
```

### Health Check

Если запущен с `--health-port`, доступен endpoint:

```bash
curl http://127.0.0.1:8080/health
# Ответ: {"status": "ok"}
```

### Остановка бота

- **Windows:** `Ctrl+Break` или `Ctrl+C`
- **Linux/Mac:** `Ctrl+C` или `kill <PID>` (SIGTERM)

Бот корректно завершит обработку текущих сообщений.

## Структура данных

### База данных

Расположение: `%APPDATA%\MyNotesApp\notes.db`

#### Таблица notes

| Поле         | Тип    | Описание                    |
|--------------|--------|-----------------------------|
| id           | INTEGER | Уникальный идентификатор    |
| title        | TEXT   | Заголовок заметки           |
| description  | TEXT   | Полный текст сообщения      |
| created_at   | TEXT   | Дата создания (ISO format)  |
| remind_at    | TEXT   | Напоминание (future)        |
| status       | TEXT   | Статус (active/archived)    |

#### Таблица attachments

| Поле         | Тип    | Описание                    |
|--------------|--------|-----------------------------|
| id           | INTEGER | Уникальный идентификатор    |
| note_id      | INTEGER | Ссылка на заметку           |
| file_path    | TEXT   | Путь к файлу                |
| file_type    | TEXT   | Тип вложения                |
| original_name| TEXT   | Исходное имя файла          |

### Хранение вложений

Вложения сохраняются в: `%APPDATA%\MyNotesApp\inbox\`

## API MAX Messenger

### Поддерживаемые типы обновлений

- `message_created` — новые сообщения
- `callback` — нажатия на inline-кнопки

### Отправка сообщений

```python
from bot_receiver import (
    send_message,
    send_message_with_split,
    send_keyboard_message,
    answer_callback
)

# Простое сообщение
send_message(token, chat_id, "Привет!")

# Сообщение >4000 символов (автоматический split)
send_message_with_split(token, chat_id, long_text)

# Сообщение с кнопками
buttons = [
    {"text": "Кнопка 1", "callback": "action1"},
    {"text": "Кнопка 2", "callback": "action2"}
]
send_keyboard_message(token, chat_id, "Выберите действие", buttons)

# Ответ на callback
answer_callback(token, callback_id, "✅ Обработано")
```

## Паттерны использования

### 1. Обработка кнопок

```python
# В _process_update:
if update_type == "callback":
    callback_data = update.get("callback", {}).get("data")
    if callback_data.startswith("open:"):
        file_path = callback_data[5:]
        # Открыть файл
    elif callback_data.startswith("info:"):
        attachment_type = callback_data[5:]
        # Показать информацию
```

### 2. Graceful shutdown

```python
import signal
from bot_receiver import _running

# Бот автоматически обрабатывает сигналы
# Для ручной остановки:
_running = False  # Бот завершит текущую и操作цию
```

### 3. Health check мониторинг

```python
import requests

def check_health():
    try:
        resp = requests.get("http://127.0.0.1:8080/health")
        return resp.json()["status"] == "ok"
    except requests.ConnectionError:
        return False
```

## Troubleshooting

### Ошибка x509: certificate signed by unknown authority

Добавьте CA сертификат в доверенные:

```python
import os
os.environ["REQUESTS_CA_BUNDLE"] = "path/to/russian_trusted_root_ca.pem"
```

### 401 Unauthorized

Токен неверный или отозван. Пересоздайте токен:

```bash
python bot_receiver.py --configure-token
```

### 429 Too Many Requests

Превышен лимит 30 req/s. Бот автоматически делает backoff.

### attachment.not.ready

Бот автоматически повторит попытку до 3 раз с экспоненциальной задержкой.

## Логирование

Уровни логирования:

- **DEBUG** — подробная информация для отладки
- **INFO** — информационные сообщения (по умолчанию)
- **WARNING** — предупреждения
- **ERROR** — ошибки

Пример логов:

```
2026-11-01 12:34:56 [INFO] max-bot-receiver: Бот запущен. База данных: C:\Users\Ilya\AppData\Roaming\MyNotesApp\notes.db
2026-11-01 12:34:57 [INFO] max-bot-receiver: Сохранена текстовая заметка (chat_id=123456, note_id=1, сообщений=1)
2026-11-01 12:34:58 [INFO] max-bot-receiver: Сохранено вложение: inbox/image_a1b2c3d4.jpg (chat_id=123456)
2026-11-01 12:35:00 [WARNING] max-bot-receiver: Превышен лимит запросов MAX. Повтор через 5 с.
```

## Безопасность

- Токен шифруется через DPAPI (Windows Data Protection API)
- Токен хранится только в зашифрованном виде
- Никогда не передавайте токен третьим лицам
- CA сертификат проверяйте по fingerprint

## Лицензия

MIT

## Ссылки

- [MAX Bot API Docs](https://dev.max.ru/docs-api)
- [MAX Messenger GitHub](https://github.com/max-messenger)
- [CA Certificate](https://www.gosuslugi.ru/crt)
