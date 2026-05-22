import os, psycopg
from dotenv import load_dotenv
load_dotenv()
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS ping (id serial primary key, note text)")
    conn.execute("INSERT INTO ping (note) VALUES (%s)", ("hello",))
    rows = conn.execute("SELECT * FROM ping").fetchall()
    print("Postgres works:", rows)
