FROM python:3.11-slim

WORKDIR /app

# Install curl and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 7860 is default for Hugging Face Spaces; Render/Koyeb injects $PORT automatically
EXPOSE 7860
ENV PORT=7860

CMD ["python", "bot.py"]
