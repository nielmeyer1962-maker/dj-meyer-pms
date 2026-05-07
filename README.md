# DJ Meyer & Co — Practice Management System

Internal practice management system for DJ Meyer & Co. Tracks statutory obligations, due dates, and staff assignments across all clients.

## Prerequisites

- Python 3.12+
- PostgreSQL 15+

## Local setup

```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Configure environment
copy .env.example .env
# Edit .env: set DATABASE_URL, SECRET_KEY, and mail credentials

# Run the development server
python run.py
```

The app will be available at http://localhost:5000.

## Database setup

```bash
# After configuring DATABASE_URL in .env:
flask db upgrade
```

## Running tests

```bash
pytest
```

## Linting and formatting

```bash
ruff check .      # lint
ruff format .     # format
```

## Deployment

Run with Gunicorn behind nginx on Ubuntu. Set `DEBUG=False` and use a strong `SECRET_KEY` in production.

```bash
gunicorn -w 4 "run:app"
```
