# Medbook Hospital Booking

Flask + PostgreSQL doctor appointment booking app.

## Quick Start (Local)

```bash
python -m venv .venv
. .venv/Scripts/activate  # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Set env vars (temporary session) — adjust credentials
$env:DATABASE_URL="postgresql://appuser:Pass123!@localhost:5432/medbook"
$env:SECRET_KEY="dev-secret"
# Create tables (if not using schema.sql directly)
python - <<EOF
from Medbook.table import app, db, ensure_schema
with app.app_context():
    db.create_all(); ensure_schema()
EOF
# (Optional) seed
python seed_data.py
# Run
python -m waitress --listen=0.0.0.0:5000 Medbook.table:app
```

Or apply SQL schema:
```bash
psql "postgresql://appuser:Pass123!@localhost:5432/medbook" -f schema.sql
```

Visit: http://localhost:5000/

## Environment Variables
| Name | Description |
|------|-------------|
| DATABASE_URL | Postgres connection string |
| SECRET_KEY | Flask secret key (sessions/JWT) |

## Deployment (Render)
1. Create Postgres service → copy External Database URL.
2. Set `DATABASE_URL` & `SECRET_KEY` in Web Service Environment.
3. Preferred start command (fully qualified module path):
```
python -m waitress --listen=0.0.0.0:$PORT Medbook.table:app
```
    This loads the app from `Medbook/table.py`.

    Alternative (if you must keep `table:app`): a root-level `table.py` shim exists:
```
from Medbook.table import app
```
    Then you may use:
```
python -m waitress --listen=0.0.0.0:$PORT table:app
```
4. Deploy; app will auto use supplied database.

## Seeding Data
Run `python seed_data.py`. Skips if hospitals already exist.

## Prevent Double Booking
`ensure_schema()` adds a unique constraint `(doctorid, appointment_date, appointment_time)` automatically if missing.

## Directory Layout
```
Medbook/            # Flask app (table.py + static HTML)
schema.sql          # DDL for full schema
seed_data.py        # Optional starter data
requirements.txt    # Python deps
render.yaml         # (if present) Render blueprint definition
```

## API (Selected)
- POST /users/register
- POST /users/login
- GET /doctors
- GET /doctors/<id>
- GET /doctors/<id>/availability?date=YYYY-MM-DD
- POST /appointments
- PUT /appointments/<id>/cancel
- GET /users/<id>/appointments

## Development Tips
- If you forget to set `DATABASE_URL`, SQLite file `local_dev.db` is used.
- Use `.env` file; `python-dotenv` auto-loads if installed.
- Rotate any exposed credentials immediately.

## License
Internal / educational use.
