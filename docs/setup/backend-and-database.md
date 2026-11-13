# Backend and database, locally

Run from the repo root. Windows PowerShell shown; use the venv's Python (`.venv\Scripts\python.exe`).

1. **Environment file.** Copy `.env.example` to `.env`, set `POSTGRES_PASSWORD`, put the same password in
   `DATABASE_URL`, and set `TURNWISE_API_TOKEN` to a long random string. `.env` is git-ignored.
2. **Database.** `docker compose up -d db` starts PostgreSQL 16 + PostGIS on `127.0.0.1:5433`.
   Use `127.0.0.1`, not `localhost` (IPv6 fallback makes every connection wait).
3. **Tables.** `alembic upgrade head` creates them from `backend/migrations/`. After editing
   `backend/models.py`, run `alembic revision --autogenerate -m "what changed"`, read the file it writes, then upgrade.
4. **Test database.** `docker exec turnwise-db psql -U turnwise -d postgres -c "CREATE DATABASE turnwise_test;"`
   once. Tests in `tests/db` use it and skip themselves if the database is down (`TURNWISE_REQUIRE_DB=1` makes that an error).
5. **Run the API.** `uvicorn backend.app:app_from_env --factory --reload` (needs Valhalla on :8002 to plan routes).
   Without `DATABASE_URL` trips live in memory only.

Map of the code: `backend/app.py` (endpoints) -> `registry.py` (live trips) -> `persistence.py` (what gets recorded)
-> `repository.py` (SQL) -> `models.py` (tables).
