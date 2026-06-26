FROM python:3.11-slim

# Системные библиотеки для EasyOCR / OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Зависимости Python (отдельным слоем для кэша)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Предзагрузка моделей EasyOCR при сборке (чтобы не грузить при первом запросе)
RUN python -c "import easyocr; easyocr.Reader(['en'], gpu=False)"

# Код приложения
COPY . .

ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python", "bot.py"]
