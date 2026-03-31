# Ethio Price Radar (Telegram Bot)

## 📌 Project Overview

Ethio Price Radar is a real-time Telegram bot designed to monitor Ethiopian Telegram shops and channels, aggregate product data, and provide users with price intelligence including Minimum, Maximum, Average, and the current Best Deal based on their search queries.

**Deployment Environment:** Hugging Face Spaces (Docker / Supervisor)

**Database:** Meilisearch (Vector / Full-Text Search)

**Bot Framework:** Telethon (MTProto) + FastAPI

## 🏗️ Architecture & Core Decisions

### 1. The Telethon Pivot (Bypassing DNS Issues)

The bot initially used Aiogram (HTTP-based). However, Hugging Face Spaces often experience DNS resolution blocks when attempting to reach `api.telegram.org`.

**The Fix:** The core bot was migrated to Telethon. Telethon uses Telegram's native MTProto protocol, connecting directly to Telegram IP addresses such as `149.154.167.91`, which bypasses the DNS block.

### 2. Hugging Face Health Check (Port 7860)

Hugging Face requires a web server to bind to port `7860`; otherwise, the Space is treated as crashed and the container may be terminated.

**The Fix:** A lightweight FastAPI app is embedded directly inside `main_bot.py`. It runs concurrently with the Telethon bot using `asyncio.gather()`, satisfying the HF health check without a separate web server process.

### 3. Process Management (supervisord)

Because the project has multiple moving parts, `supervisord` is used to keep everything running in the same Docker container.

- `meilisearch`: Runs the local search engine on `127.0.0.1:7700`.
- `listener`: A separate Python script (`scraper.listener`) monitors target channels for new inventory and pipes it into Meilisearch.
- `bot`: The user-facing bot (`main_bot.py`) handles queries and serves the FastAPI health check.

## ⚙️ Environment Variables (.env / HF Secrets)

For the bot to start successfully, the following exact keys must exist in your Hugging Face Secrets:

- `TELEGRAM_APP_ID` (Integer, from `my.telegram.org`)
- `TELEGRAM_API_HASH` (String, from `my.telegram.org`)
- `BOT_TOKEN` (String, from `@BotFather`)
- `MEILI_HOST` (e.g. `http://127.0.0.1:7700`)
- `MEILI_MASTER_KEY` (Your secure database password)

> Note: The project intentionally stopped using a `BOT_SESSION_STRING` for the main bot. Telethon is configured with an empty `StringSession("")`, forcing a clean login using `BOT_TOKEN` on every restart. This prevents "User vs. Bot" session conflicts.

## 🔍 Core Features

### 1. NLP Query Parsing

When a user sends a query like `laptop under 70000 bole`, the bot automatically extracts:

- `Query`: `laptop`
- `Max Price`: `70000`
- `Location`: `bole`

### 2. Price Intelligence Engine

The bot queries Meilisearch and fetches up to 50 results to calculate accurate market metrics:

- Lowest Price
- Highest Price
- Average Price
- Best Deal Right Now: highlights the absolute cheapest option and includes a direct `t.me` link to the original seller's post.
- Other Top Options: lists the next 4 cheapest alternatives.

## ⚠️ Known Quirks & "Gotchas" (Read Before Resuming)

### Meilisearch Filterable Attributes

For the `price <= X` and `location = Y` logic to work, Meilisearch must declare those fields as filterable. In `main_bot.py`, there is a startup block that runs:

```python
index.update_filterable_attributes(['price', 'location'])
```

If you ever wipe the database, this ensures the new index is configured correctly.

### Persistent Storage on Hugging Face

In `supervisord.conf`, Meilisearch is strictly pointed to `--db-path /data/meili_data`. Do not change this directory, or Hugging Face may wipe your database every time the Space restarts.

### Log Viewing

In `supervisord.conf`, bot logs are set to `/dev/stdout`. The Python command uses `-u` (`python -u -m bot.main_bot`), so logs are unbuffered and errors appear immediately in the Hugging Face log viewer.

## 🚀 How to Resume Work Later

1. Check HF Secrets: Ensure Telegram credentials have not been revoked due to inactivity.
2. Review the Scraper: Confirm the `scraper.listener` target channels are still active and valid.
3. Run Locally First: If you pull this repository locally, spin up a local Meilisearch instance on port `7700` before running the bot, or initialization may fail.
