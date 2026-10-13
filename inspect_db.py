from storage.database import get_connection


conn = get_connection()

cur = conn.cursor()

cur.execute(
    """
    SELECT
        id,
        title,
        doi
    FROM articles
    LIMIT 20
    """
)

rows = cur.fetchall()

for row in rows:

    print(row)

conn.close()