#!/bin/bash
# Запуск MAX Bot Receiver
echo "Запуск MAX Bot Receiver..."

# Проверка существования config.json
if [ ! -f "config.json" ]; then
    echo "Warning: config.json not found. Using defaults."
fi

# Запуск с поддержкой параметров
python bot_receiver.py "$@"
