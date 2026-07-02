# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ethio Price Radar is a Telegram bot that monitors Ethiopian Telegram shops/channels, extracts product listings (name, price, location) via an LLM, indexes them in Meilisearch, and answers user queries with price intelligence (min/max/average price, best deal, alternatives).

Stack: Telethon (MTProto Telegram client) + FastAPI (health check) + Meilisearch (search/filter engine) + Groq (LLM entity extraction). Deployed as a single Docker container to Hugging Face Spaces, orchestrated by `supervisord`.

## Running locally

There is no test suite, linter, or build step configured in this repo — verification is done by running the components against a live (or local) Meilisearch instance and Telegram API.

Requires a `.env` file (see "Environment variables" below) and Python 3.11. Install deps with:

```
pip install -r requirements.txt
```

Before running the bot or listener, a local Meilisearch instance must be reachable at `MEILI_HOST` (e.g. run `meilisearch` on port 7700, or use `docker-compose up meilisearch`).

Run individual components directly (do not run scripts with plain `python path/to/file.py` when they use package-relative imports — use `-m` with the dotted module path from the repo root):

```
python -m bot.main_bot          # the user-facing bot + FastAPI health server (port 7860)
python -m scraper.listener       # 24/7 real-time listener on TARGET_CHANNELS
python -m scraper.historical_scraper  # one-off backfill of the last 30 days per channel
python -m db.seeder              # runs db init + historical_scraper as an orchestrated seed job
python -m db.database            # initializes/reconfigures the Meilisearch index only
```

Or run the whole stack (Meilisearch + listener + bot + one-shot seeder) via Docker Compose:

```
docker-compose up --build
```

## Architecture

Three long-running processes share one Meilisearch `products` index, managed by `supervisord.conf` in the container (`meilisearch`, `listener`, `bot`, plus a one-shot `seeder`):

1. **`scraper/listener.py`** — Telethon client listening for `NewMessage` events on `TARGET_CHANNELS`. On each new post, builds a raw payload and passes it to `nlp/extractor.py`, then writes the result to Meilisearch via `db/database.py`.
2. **`scraper/historical_scraper.py`** — one-off backfill: iterates the last 30 days of messages per channel in `TARGET_CHANNELS`, filters for messages that look like they contain a price (`is_valid_product_message`), and feeds valid ones through the same extractor → database pipeline. Includes a 1.5s inter-message delay and `FloodWaitError` handling to avoid Telegram rate limits/bans. Invoked via `db/seeder.py` (which also (re)initializes the index first) or directly.
3. **`bot/main_bot.py`** — the user-facing Telethon bot. Parses free-text queries (`parse_user_query`: extracts a max price from phrases like "under 500" and a location from a hardcoded list of Addis Ababa neighborhoods), queries Meilisearch with `price <=` / `location =` filters, and replies with lowest/highest/average price plus the cheapest listing and top alternatives, each linking back to the original `t.me` post. It also embeds a FastAPI app (run concurrently via `asyncio.gather`) exposing `/`, `/ping` (external keep-alive), and `/seed?token=<BOT_TOKEN>` (remote trigger for `db/seeder.py` as a background subprocess) — required because Hugging Face Spaces kills containers that don't bind to port 7860.

**`nlp/extractor.py`** is the shared LLM entity-extraction step used by both the listener and the historical scraper: sends the raw message text to Groq (`llama-3.3-70b-versatile`, JSON mode) with a prompt asking for `product_name`, `price`, `location`, coerces price to an int, and returns `None` if no price was found (payloads without a price are dropped, never indexed).

**`db/database.py`** (`ProductDatabase`) wraps the Meilisearch client: connects with a retry loop (10 attempts, 3s apart) since the container's Meilisearch process may not be up yet, and defines the index schema — searchable (`product_name`, `original_text`), filterable (`price`, `location`, `channel_username`), and sortable (`price`, `timestamp`) attributes.

### Known gotchas (from README, still relevant)

- **Filterable attributes must be set** for `price <=` / `location =` filters to work — `main_bot.py` re-asserts `update_filterable_attributes(['price', 'location'])` on every startup as a safety net if the index was ever wiped/recreated.
- **Meilisearch persistent storage path is fixed** at `/data/meili_data` in `supervisord.conf` — do not change it, or Hugging Face wipes the DB on every Space restart.
- **Bot auth**: Telethon is intentionally started with an empty `StringSession("")` and logs in fresh via `BOT_TOKEN` every restart (not `BOT_SESSION_STRING`), to avoid "user vs bot" session conflicts. The listener/historical scraper instead authenticate as a *user* account via `TELEGRAM_STRING_SESSION` (needed to read channels the bot account may not have joined).
- **Logs**: supervisord routes all component stdout/stderr to `/dev/fd/1`/`/dev/fd/2`; the bot/listener use unbuffered `-u` execution so log lines show up immediately in the HF log viewer.

### Environment variables

Required (see `README.md` for the full list): `TELEGRAM_APP_ID`, `TELEGRAM_API_HASH`, `BOT_TOKEN`, `MEILI_HOST`, `MEILI_MASTER_KEY`, `GROQ_API_KEY`, `TELEGRAM_STRING_SESSION`, `TARGET_CHANNELS` (comma-separated channel usernames, no `@`).
