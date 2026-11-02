MAX Messenger Bot — Заметки
Бот для MAX Messenger, который автоматически сохраняет incoming сообщения и вложения в локальную базу данных SQLite с шифрованием токена и умным определением типов файлов.

🚀 Возможности
✅ Long polling обновлений из MAX API (platform-api2.max.ru)
✅ Сохранение текстовых сообщений в базу данных SQLite
✅ Скачивание и хранение вложений (фото, видео, файлы, аудио, стикеры)
✅ Автоматическое определение типа файла по содержимому (magic bytes)
✅ Шифрование токена через Windows DPAPI
✅ Структурированное логирование с уровнями DEBUG/INFO/WARNING/ERROR
✅ Graceful shutdown (SIGINT/SIGTERM/SIGBREAK)
✅ Split сообщений длиннее 4000 символов
✅ Inline-кнопки и callback handlers
✅ Health check endpoint для мониторинга
✅ Retry logic для attachment.not.ready
✅ Rate limiting (30 req/s) с экспоненциальным backoff
📋 Требования
Python 3.10+ (синтаксис str | None)
Windows (для DPAPI шифрования токена)
requests — HTTP клиент
MAX Bot Token — токен бота из business.max.ru
🛠 Установка
1. Клонирование репозитория
# Создайте директорию проекта
mkdir C:\Users\Ilya\Python_Project\my_note
cd C:\Users\Ilya\Python_Project\my_note

# Если используете Git:
git clone <repo-url> .
2. Установка зависимостей
# Создайте виртуальное окружение (рекомендуется)
python -m venv venv
.\venv\Scripts\activate

# Установите зависимости
pip install requests
3. Проверка сертификата
MAX API использует сертификат от Минцифры России. Убедитесь, что файл combined_ca.pem или russian_trusted_root_ca.pem присутствует в директории проекта:

# Если нет сертификата, скачайте его:
curl -fsSL -o russian_trusted_root_ca.pem `
  https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt

# Или используйте существующий combined_ca.pem
4. Создание конфигурации (опционально)
Скопируйте пример конфигурации и отредактируйте:

copy config.json.example config.json 2>$null; if ($LASTEXITCODE -ne 0) { Copy-Item config.json config.custom.json }
Основные параметры в config.json:

{
    "api": {
        "base_url": "https://platform-api2.max.ru",
        "rate_limit_rps": 30,
        "long_poll_timeout": 30
    },
    "database": {
        "journal_mode": "WAL",
        "busy_timeout_ms": 10000,
        "notes_dir": "%APPDATA%/MyNotesApp"
    },
    "retry": {
        "attachment_not_ready_max_retries": 3,
        "attachment_not_ready_backoff_seconds": 2
    },
    "health_check": {
        "enabled": true,
        "port": 8080
    }
}
5. Настройка токена MAX
Способ 1: Интерактивный (рекомендуется)

python bot_receiver.py --configure-token
Введите токен два раза (ввод скрыт). Токен будет зашифрован через DPAPI и сохранён в:

%APPDATA%\MyNotesApp\max_bot_token.dpapi
Способ 2: Через переменную окружения

# Получить токен: business.max.ru → Чат-боты → ваш бот → ⋮ → Настройки → Токен
$env:MAX_BOT_TOKEN="f9LHodD0cOLEjyR5DTIzrCuqIUxVoLnGTXK0XkuP3R1tNHDCNq3CykX4A5bvbCgcETfiw63tGQ2kTBLGrtJM"

# Запустить бота
python bot_receiver.py
Способ 3: Через .env файл

# Создайте .env файл
@"
MAX_BOT_TOKEN=ваш_токен_здесь
LOG_LEVEL=INFO
HEALTH_PORT=8080
"@ | Out-File -Encoding utf8 .env

# Установите переменную из файла
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^=]+)=(.+)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'User')
    }
}
▶️ Запуск
Базовый запуск
$env:MAX_BOT_TOKEN="ваш_токен"
python bot_receiver.py
С параметрами
# С логированием DEBUG
python bot_receiver.py --log-level DEBUG

# С health check на порту 8080
python bot_receiver.py --health-port 8080

# Все параметры
python bot_receiver.py --log-level DEBUG --health-port 8080
Через batch-файл
.\run.bat
Через bash-скрипт (WSL/Git Bash)
./run.sh --log-level DEBUG
📊 Структура данных
База данных
Расположение: %APPDATA%\MyNotesApp\notes.db

Таблица notes
Поле	Тип	Описание
id	INTEGER	Уникальный идентификатор
title	TEXT	Заголовок заметки (до 20 символов)
description	TEXT	Полный текст сообщения
created_at	TEXT	Дата создания (ISO формат)
remind_at	TEXT	Напоминание (future feature)
status	TEXT	active / archived
Таблица attachments
Поле	Тип	Описание
id	INTEGER	Уникальный идентификатор
note_id	INTEGER	Ссылка на заметку (FK)
file_path	TEXT	Путь к файлу (относительный)
file_type	TEXT	Тип вложения (image/video/file/audio)
original_name	TEXT	Исходное имя файла
Хранение вложений
Вложения сохраняются в: %APPDATA%\MyNotesApp\inbox\

Пример имени файла: image_a1b2c3d4e5f6.jpg

Шифрование токена
Токен хранится в зашифрованном виде через Windows DPAPI:

%APPDATA%\MyNotesApp\max_bot_token.dpapi
Токен доступен только тому же пользователю и с той же машины.

🎯 Использование API
Отправка сообщений
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
Обработка callback (кнопок)
# В _process_update:
if update_type == "callback":
    callback_data = update.get("callback", {}).get("data")
    if callback_data.startswith("open:"):
        file_path = callback_data[5:]
        # Открыть файл
    elif callback_data.startswith("info:"):
        attachment_type = callback_data[5:]
        # Показать информацию
🔍 Troubleshooting
Ошибка: 401 Unauthorized
Причины:

Токен неверный или отозван
Старый зашифрованный токен конфликтует с новым
Решение:

# 1. Удалите старый токен
Remove-Item "$env:APPDATA\MyNotesApp\max_bot_token.dpapi" -ErrorAction SilentlyContinue

# 2. Настройте новый токен
python bot_receiver.py --configure-token
Ошибка: x509: certificate signed by unknown authority
Причина: Отсутствует CA сертификат Минцифры

Решение:

# Скачайте сертификат
curl -fsSL -o russian_trusted_root_ca.pem https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt

# Или скопируйте combined_ca.pem в текущую директорию
Файлы сохраняются с расширением .bin
Причина: URL upload-сервера не содержит расширения.

Решение: Убедитесь, что вы используете последнюю версию кода с функцией _fix_extension().

Бот не получает сообщения
Причина: Ошибка в структуре обновления или rate limiting.

Решение:

# Запустите с DEBUG логированием
$env:MAX_BOT_TOKEN="ваш_токен"
python bot_receiver.py --log-level DEBUG
Проверьте:

Бот добавлен в чат?
У бота есть право write в чате?
Не превышаете ли вы 30 req/s?
Health check не отвечает
# Проверьте, что порт не занят
netstat -ano | findstr :8080

# Попробуйте другой порт
python bot_receiver.py --health-port 9000
📝 Логирование
Уровни логирования:

Уровень	Описание
DEBUG	Подробная информация для отладки
INFO	Информационные сообщения (по умолчанию)
WARNING	Предупреждения
ERROR	Ошибки
Пример вывода:

2026-11-01 14:00:00 [INFO] max-bot-receiver: Бот запущен. База данных: C:\Users\Ilya\AppData\Roaming\MyNotesApp\notes.db
2026-11-01 14:00:01 [INFO] max-bot-receiver: Сохранена текстовая заметка (chat_id=123456, note_id=1, сообщений=1)
2026-11-01 14:00:02 [INFO] max-bot-receiver: Сохранено вложение: inbox/image_a1b2c3d4.jpg (chat_id=123456)
2026-11-01 14:00:05 [WARNING] max-bot-receiver: Превышен лимит запросов MAX. Повтор через 5 с.
🔒 Безопасность
Токен шифруется через Windows DPAPI (Data Protection API)
Токен хранится только в зашифрованном виде
Токен доступен только тому же пользователю и с той же машины
Никогда не передавайте токен третьим лицам
CA сертификат проверяйте по fingerprint:
certutil -hashfile russian_trusted_root_ca.pem SHA256
# D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31
📦 Файлы проекта
Файл	Описание
bot_receiver.py	Основной файл бота
config.json	Конфигурация приложения
combined_ca.pem	CA сертификат для MAX API
russian_trusted_root_ca.pem	Root CA сертификат Минцифры
run.bat	Запускающий скрипт для Windows
run.sh	Запускающий скрипт для Linux/Mac
.env.example	Пример переменных окружения
README.md	Эта документация
🔗 Ссылки
MAX Bot API Docs
MAX Messenger GitHub
CA Certificate
Skills.sh — MAX Messenger Skill
📄 Лицензия
MIT

# MAX Messenger Bot — Заметки
 
Бот для MAX Messenger, который автоматически сохраняет incoming сообщения и вложения в локальную базу данных SQLite с шифрованием токена и умным определением типов файлов.
 
## 🚀 Возможности
 
- ✅ Long polling обновлений из MAX API (`platform-api2.max.ru`)
- ✅ Сохранение текстовых сообщений в базу данных SQLite
- ✅ Скачивание и хранение вложений (фото, видео, файлы, аудио, стикеры)
- ✅ Автоматическое определение типа файла по содержимому (magic bytes)
- ✅ Шифрование токена через Windows DPAPI
- ✅ Структурированное логирование с уровнями DEBUG/INFO/WARNING/ERROR
- ✅ Graceful shutdown (SIGINT/SIGTERM/SIGBREAK)
- ✅ Split сообщений длиннее 4000 символов
- ✅ Inline-кнопки и callback handlers
- ✅ Health check endpoint для мониторинга
- ✅ Retry logic для `attachment.not.ready`
- ✅ Rate limiting (30 req/s) с экспоненциальным backoff
 
## 📋 Требования
 
- **Python 3.10+** (синтаксис `str | None`)
- **Windows** (для DPAPI шифрования токена)
- **requests** — HTTP клиент
- **MAX Bot Token** — токен бота из business.max.ru
 
## 🛠 Установка
 
### 1. Клонирование репозитория
 
```powershell
# Создайте директорию проекта
mkdir C:\Users\Ilya\Python_Project\my_note
cd C:\Users\Ilya\Python_Project\my_note
 
# Если используете Git:
git clone <repo-url> .
```
 
### 2. Установка зависимостей
 
```powershell
# Создайте виртуальное окружение (рекомендуется)
python -m venv venv
.\venv\Scripts\activate
 
# Установите зависимости
pip install requests
```
 
### 3. Проверка сертификата
 
MAX API использует сертификат от Минцифры России. Убедитесь, что файл `combined_ca.pem` или `russian_trusted_root_ca.pem` присутствует в директории проекта:
 
```powershell
# Если нет сертификата, скачайте его:
curl -fsSL -o russian_trusted_root_ca.pem `
  https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
 
# Или используйте существующий combined_ca.pem
```
 
### 4. Создание конфигурации (опционально)
 
Скопируйте пример конфигурации и отредактируйте:
 
```powershell
copy config.json.example config.json 2>$null; if ($LASTEXITCODE -ne 0) { Copy-Item config.json config.custom.json }
```
 
Основные параметры в `config.json`:
 
```json
{
    "api": {
        "base_url": "https://platform-api2.max.ru",
        "rate_limit_rps": 30,
        "long_poll_timeout": 30
    },
    "database": {
        "journal_mode": "WAL",
        "busy_timeout_ms": 10000,
        "notes_dir": "%APPDATA%/MyNotesApp"
    },
    "retry": {
        "attachment_not_ready_max_retries": 3,
        "attachment_not_ready_backoff_seconds": 2
    },
    "health_check": {
        "enabled": true,
        "port": 8080
    }
}
```
 
### 5. Настройка токена MAX
 
**Способ 1: Интерактивный (рекомендуется)**
 
```powershell
python bot_receiver.py --configure-token
```
 
Введите токен два раза (ввод скрыт). Токен будет зашифрован через DPAPI и сохранён в:
```
%APPDATA%\MyNotesApp\max_bot_token.dpapi
```
 
**Способ 2: Через переменную окружения**
 
```powershell
# Получить токен: business.max.ru → Чат-боты → ваш бот → ⋮ → Настройки → Токен
$env:MAX_BOT_TOKEN="f9LHodD0cOLEjyR5DTIzrCuqIUxVoLnGTXK0XkuP3R1tNHDCNq3CykX4A5bvbCgcETfiw63tGQ2kTBLGrtJM"
 
# Запустить бота
python bot_receiver.py
```
 
**Способ 3: Через .env файл**
 
```powershell
# Создайте .env файл
@"
MAX_BOT_TOKEN=ваш_токен_здесь
LOG_LEVEL=INFO
HEALTH_PORT=8080
"@ | Out-File -Encoding utf8 .env
 
# Установите переменную из файла
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^=]+)=(.+)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'User')
    }
}
```
 
## ▶️ Запуск
 
### Базовый запуск
 
```powershell
$env:MAX_BOT_TOKEN="ваш_токен"
python bot_receiver.py
```
 
### С параметрами
 
```powershell
# С логированием DEBUG
python bot_receiver.py --log-level DEBUG
 
# С health check на порту 8080
python bot_receiver.py --health-port 8080
 
# Все параметры
python bot_receiver.py --log-level DEBUG --health-port 8080
```
 
### Через batch-файл
 
```powershell
.\run.bat
```
 
### Через bash-скрипт (WSL/Git Bash)
 
```bash
./run.sh --log-level DEBUG
```
 
## 📊 Структура данных
 
### База данных
 
Расположение: `%APPDATA%\MyNotesApp\notes.db`
 
#### Таблица notes
 
| Поле        | Тип   | Описание                     |
|-------------|-------|------------------------------|
| id          | INTEGER | Уникальный идентификатор    |
| title       | TEXT  | Заголовок заметки (до 20 символов) |
| description | TEXT  | Полный текст сообщения       |
| created_at  | TEXT  | Дата создания (ISO формат)   |
| remind_at   | TEXT  | Напоминание (future feature) |
| status      | TEXT  | active / archived            |
 
#### Таблица attachments
 
| Поле          | Тип   | Описание                    |
|---------------|-------|-----------------------------|
| id            | INTEGER | Уникальный идентификатор   |
| note_id       | INTEGER | Ссылка на заметку (FK)     |
| file_path     | TEXT  | Путь к файлу (относительный)|
| file_type     | TEXT  | Тип вложения (image/video/file/audio) |
| original_name | TEXT  | Исходное имя файла          |
 
### Хранение вложений
 
Вложения сохраняются в: `%APPDATA%\MyNotesApp\inbox\`
 
Пример имени файла: `image_a1b2c3d4e5f6.jpg`
 
### Шифрование токена
 
Токен хранится в зашифрованном виде через Windows DPAPI:
```
%APPDATA%\MyNotesApp\max_bot_token.dpapi
```
 
Токен доступен только тому же пользователю и с той же машины.
 
## 🎯 Использование API
 
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
 
### Обработка callback (кнопок)
 
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
 
## 🔍 Troubleshooting
 
### Ошибка: `401 Unauthorized`
 
**Причины:**
1. Токен неверный или отозван
2. Старый зашифрованный токен конфликтует с новым
 
**Решение:**
```powershell
# 1. Удалите старый токен
Remove-Item "$env:APPDATA\MyNotesApp\max_bot_token.dpapi" -ErrorAction SilentlyContinue
 
# 2. Настройте новый токен
python bot_receiver.py --configure-token
```
 
### Ошибка: `x509: certificate signed by unknown authority`
 
**Причина:** Отсутствует CA сертификат Минцифры
 
**Решение:**
```powershell
# Скачайте сертификат
curl -fsSL -o russian_trusted_root_ca.pem https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
 
# Или скопируйте combined_ca.pem в текущую директорию
```
 
### Файлы сохраняются с расширением `.bin`
 
**Причина:** URL upload-сервера не содержит расширения.
 
**Решение:** Убедитесь, что вы используете последнюю версию кода с функцией `_fix_extension()`.
 
### Бот не получает сообщения
 
**Причина:** Ошибка в структуре обновления или rate limiting.
 
**Решение:**
```powershell
# Запустите с DEBUG логированием
$env:MAX_BOT_TOKEN="ваш_токен"
python bot_receiver.py --log-level DEBUG
```
 
Проверьте:
- Бот добавлен в чат?
- У бота есть право `write` в чате?
- Не превышаете ли вы 30 req/s?
 
### Health check не отвечает
 
```powershell
# Проверьте, что порт не занят
netstat -ano | findstr :8080
 
# Попробуйте другой порт
python bot_receiver.py --health-port 9000
```
 
## 📝 Логирование
 
Уровни логирования:
 
| Уровень | Описание |
|---------|----------|
| DEBUG   | Подробная информация для отладки |
| INFO    | Информационные сообщения (по умолчанию) |
| WARNING | Предупреждения |
| ERROR   | Ошибки |
 
Пример вывода:
 
```
2026-11-01 14:00:00 [INFO] max-bot-receiver: Бот запущен. База данных: C:\Users\Ilya\AppData\Roaming\MyNotesApp\notes.db
2026-11-01 14:00:01 [INFO] max-bot-receiver: Сохранена текстовая заметка (chat_id=123456, note_id=1, сообщений=1)
2026-11-01 14:00:02 [INFO] max-bot-receiver: Сохранено вложение: inbox/image_a1b2c3d4.jpg (chat_id=123456)
2026-11-01 14:00:05 [WARNING] max-bot-receiver: Превышен лимит запросов MAX. Повтор через 5 с.
```
 
## 🔒 Безопасность
 
- Токен шифруется через **Windows DPAPI** (Data Protection API)
- Токен хранится только в зашифрованном виде
- Токен доступен только тому же пользователю и с той же машины
- **Никогда не передавайте токен третьим лицам**
- CA сертификат проверяйте по fingerprint:
 
```powershell
certutil -hashfile russian_trusted_root_ca.pem SHA256
# D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31
```
 
## 📦 Файлы проекта
 
| Файл | Описание |
|------|----------|
| `bot_receiver.py` | Основной файл бота |
| `config.json` | Конфигурация приложения |
| `combined_ca.pem` | CA сертификат для MAX API |
| `russian_trusted_root_ca.pem` | Root CA сертификат Минцифры |
| `run.bat` | Запускающий скрипт для Windows |
| `run.sh` | Запускающий скрипт для Linux/Mac |
| `.env.example` | Пример переменных окружения |
| `README.md` | Эта документация |
 
## 🔗 Ссылки
 
- [MAX Bot API Docs](https://dev.max.ru/docs-api)
- [MAX Messenger GitHub](https://github.com/max-messenger)
- [CA Certificate](https://www.gosuslugi.ru/crt)
- [Skills.sh](https://skills.sh) — MAX Messenger Skill
 
## 📄 Лицензия
 
MIT
