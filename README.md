# Meal Planner

Personal meal planning assistant — Telegram bot + read-only web UI. Powered by Claude.

---

## VPS Setup

### 1. Clone the repo

```bash
git clone git@github.com:peteD900/mealPlanner.git
cd mealPlanner
```

### 2. Create your `.env` file

```bash
cp .env.example .env
nano .env
```

Fill in:
```
TELEGRAM_TOKEN=your-telegram-bot-token
ANTHROPIC_API_KEY=your-anthropic-api-key
```

### 3. Check the data files

`data/ingredients.txt` and `data/sites.txt` are already in the repo. Edit them to match your setup:

- `data/ingredients.txt` — ingredients locally available to you
- `data/sites.txt` — cooking sites to draw recipe inspiration from

### 4. Build and start

```bash
docker compose up -d --build
```

The container starts automatically on boot (`restart: unless-stopped`).

### 5. Where things live

| What | Where |
|---|---|
| Database | `./data/mealplanner.db` (on the host, persisted via volume) |
| Ingredients | `./data/ingredients.txt` |
| Inspiration sites | `./data/sites.txt` |
| Web UI | `http://localhost:8000` (internal only) |
| Logs | `docker compose logs -f` |

---

## Nginx Proxy Manager

The web UI runs on `127.0.0.1:8000` inside the VPS — it is **not** exposed publicly by default. To make it accessible via a domain:

1. In NPM, add a **Proxy Host**
2. **Domain**: your domain or subdomain (e.g. `meals.yourdomain.com`)
3. **Forward Hostname / IP**: `127.0.0.1`
4. **Forward Port**: `8000`
5. Enable SSL via Let's Encrypt

The Telegram bot connects outbound to Telegram's servers — no inbound port needed for the bot to work.

---

## Updating

```bash
git pull
docker compose up -d --build
```

The `./data` volume is untouched by rebuilds — your recipes and meal plans are safe.

## Dev reset (clear plan + history, keep recipes)

```bash
docker compose exec mealplanner uv run python scripts/reset_dev.py
```
