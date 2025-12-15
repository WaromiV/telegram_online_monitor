# unhinged-spyware

Telegram presence-based sleep inference prototype. Passive presence polling only; no biometric data.

## Quick start

1. Install deps and create the in-project venv: `poetry install`
2. Copy env template: `cp .env.example .env` and fill in your Telegram API credentials and `USER_TIMEZONES` (`user_id:TZ,user_id:TZ`). Use a real `TELEGRAM_SESSION_STRING` (preferred) for user presence access; a bot token works only if your use-case allows bot presence reads. Placeholders or short strings are rejected.
3. Activate the venv for local commands: `source .venv/bin/activate` or `poetry shell`.
4. Start the presence collector (event-driven, listens to Telegram status updates): `poetry run python -m unhinged_spyware.collector`
5. Run aggregation to materialize offline intervals, sleep windows, and anomalies: `poetry run python -m unhinged_spyware.aggregator`
6. Serve the API (FastAPI + Uvicorn): `poetry run python -m unhinged_spyware.api` then hit `GET /users` etc.

## Docker Compose

Build and run the stack (collector + aggregator loop + API) sharing a single SQLite volume:

```bash
docker compose up --build -d
```

Services:
- `collector`: listens to Telegram status updates (no polling)
- `aggregator`: runs `python -m unhinged_spyware.aggregator` every `AGGREGATE_INTERVAL_SECONDS` (default 600s)
- `api`: serves FastAPI on `18080:8000` (external: 18080, internal app: 8000)

To view logs:
```bash
docker compose logs -f collector
docker compose logs -f aggregator
docker compose logs -f api
```

To hit the API:
```bash
curl http://localhost:18080/users
curl "http://localhost:18080/users/<user_id>/sleep"
```
