import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute("select current_database(), inet_server_port(), version()")
print(cur.fetchone())

cur.execute(
    "select table_schema, table_name from information_schema.tables "
    "where table_name in ('companies', 'filings')"
)
print(cur.fetchall())