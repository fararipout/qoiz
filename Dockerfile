# از یک تصویر پایه پایتون استفاده می‌کنیم
FROM python:3.10-slim

# تنظیم محیط کاری داخل کانتینر
WORKDIR /app

# نصب وابستگی‌های لازم سیستم‌عامل برای ساخت tgcrypto
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# کپی فایل‌های پروژه به کانتینر (اختیاری، اگر پروژه‌ای دارید)
# COPY . .

# نصب pyrogram و tgcrypto
RUN pip install --no-cache-dir pyrogram tgcrypto

# اجرای فایل اصلی (در صورت نیاز)
CMD ["python", "bot.py"]
