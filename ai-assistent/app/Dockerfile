# Используем легковесный образ Python
FROM python:3.11-slim

# Отключаем создание .pyc файлов и буферизацию вывода (полезно для логов)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Рабочая директория внутри контейнера
WORKDIR /app

# Устанавливаем системные зависимости (если нужны для сборки пакетов)
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код проекта
COPY . .