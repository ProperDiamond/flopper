# Daily Chemistry Quiz

A Discord bot for practising NSW HSC Chemistry questions. It can post daily short-answer questions and run multiple-choice races.

## Setup

1. Install Python 3.11 or newer.
2. Install dependencies with `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and set `DISCORD_TOKEN` to your Discord bot token.
4. Start the bot with `python bot.py`.

The included `chemistry.db` contains the question data used by the bot. To rebuild the question database from the PDFs in `papers/`, run:

```powershell
python buildDatabase.py
python build_chemistry_db.py
```

`CHEMISTRY_DB_PATH` can be set to use a different database file when running either database script.
