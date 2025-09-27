# ================================
# Gemini AI Livegram Bot Dockerfile (MongoDB + Clone Ready)
# ================================
FROM python:3.10-slim

# Prevent python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set workdir
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirement file
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Expose Flask health port
EXPOSE 8080

# Environment variables (can override at runtime)
ENV PORT=8080
ENV API_ID=123456
ENV API_HASH=your_api_hash
ENV BOT_TOKEN=your_bot_token
ENV OWNER_ID=123456789
ENV MONGO_URI=mongodb://mongo:27017

# Start bot
CMD ["python", "main.py"]
