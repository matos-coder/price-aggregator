# Use a lightweight Python image
FROM python:3.11-slim

# Install system dependencies (curl to download Meilisearch, supervisor to manage processes)
RUN apt-get update && apt-get install -y curl supervisor && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Download the Meilisearch binary directly into the container
RUN curl -L https://install.meilisearch.com | sh

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your codebase
COPY . .

# CRITICAL: Create the directory for persistent data and grant read/write permissions
RUN mkdir -p /data/meili_data && chmod -R 777 /data

# Expose the specific port Hugging Face requires
EXPOSE 7860

# Command to start the Orchestrator
CMD ["supervisord", "-c", "supervisord.conf"]