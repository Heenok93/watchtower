from storage.database import DB_PATH, get_connection

print("Database:", DB_PATH)

with get_connection() as conn:
    rows = conn.execute("PRAGMA table_info(articles)").fetchall()

print("\nColumns in articles:")

for row in rows:
    print(row["name"], "-", row["type"])