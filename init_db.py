from pathlib import Path
import sqlite3

DB_FILE = "watchtower.db"
MIGRATIONS_DIR = Path("storage/migrations")

conn = sqlite3.connect(DB_FILE)

for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):

    print(f"Applying {migration.name}")

    sql = migration.read_text(
        encoding="utf-8"
    )

    conn.executescript(sql)

conn.commit()
conn.close()

print("Database initialized")