---
title: Ethio Price Radar
emoji: 🚀
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

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
- `GROQ_API_KEY`
- `TELEGRAM_STRING_SESSION`
- `TARGET_CHANNELS=nevacomputer,heyonlinemarket,ethicomputer,abmobilet,amanelectronics1`

> Note: The project intentionally stopped using a `BOT_SESSION_STRING` for the main bot. Telethon is configured with an empty `StringSession("")`, forcing a clean login using `BOT_TOKEN` on every restart. This prevents "User vs. Bot" session conflicts.

> Optional: `GROQ_MODEL` (defaults to `llama-3.3-70b-versatile`) and `BACKFILL_DAYS` (defaults to `30`, how far back the historical scraper goes).

## 🔍 Core Features

### 1. LLM Query Understanding (with regex fallback)

When a user sends a query like `I want a macbook m2 16gb under 120k in bole`, `nlp/query_parser.py` uses Groq to extract:

- `Query`: `macbook m2 16gb`
- `Max Price`: `120000` (understands `120k`, `50,000`, "budget of", "up to", ...)
- `Location`: `bole`

If the LLM is down, slow (>6s), or returns garbage, a pure-regex parser (`parse_user_query_fallback`) takes over so the bot always answers. Budget-only queries ("anything under 5000") are searched cheapest-first.

### 2. Price Intelligence Engine

The bot runs a two-tier relevance search against Meilisearch before calculating any market metrics, so "cheapest" never overrides "relevant":

1. **Strict pass** (`matchingStrategy: "all"`): every word in the query must appear in the listing (e.g. `samsung a25` only matches listings mentioning both terms).
2. **Fallback pass** (only runs if the strict pass returns fewer than 5 hits): broadens with `matchingStrategy: "last"`, keeping only hits whose `_rankingScore` clears `RELEVANCE_THRESHOLD` (0.35 in `main_bot.py`). This is what lets close variants (e.g. `a24` for an `a25` search) show up as extras without letting weakly-related noise back in.

Only this relevance-filtered set is then used to calculate:

- Lowest Price
- Highest Price
- Average Price
- Best Deal Right Now: highlights the cheapest option *within the relevant set* and includes a direct `t.me` link to the original seller's post.
- Other Top Options: lists the next 4 cheapest alternatives from that same set.

Each listing shows how fresh it is (e.g. `🕒 3d ago`), and product names/locations are HTML-escaped before being sent to Telegram.

### 3. Ingestion Pipeline (listener + historical scraper)

Both feed the same `products` Meilisearch index through the same steps:

1. **Cheap pre-filter** (`scraper/filters.py`): messages without a plausible price never reach the LLM. Phone numbers (`09...`/`+2519...`) are masked first so they don't masquerade as prices.
2. **LLM extraction** (`nlp/extractor.py`, AsyncGroq): pulls `product_name` (brand + model + specs), `price` (ETB integer) and `location`. Retries on rate limits; rejects prices outside sanity bounds (100 – 50,000,000 ETB).
3. **Dedupe**: the historical scraper checks `document_exists(id)` *before* calling the LLM, so re-running the seeder doesn't re-spend Groq quota.
4. **Index write** (`db/database.py`): includes synonyms (macbook/mac book, laptop/notebook, ...) so shopper spelling variants still match.

### 4. Tests

Pure-function tests (no network) cover the price pre-filter and the regex query parser:

```
pip install pytest
python -m pytest tests/ -q
```

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
