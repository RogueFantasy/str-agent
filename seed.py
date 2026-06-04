import os
from datetime import date, timedelta
import psycopg
from dotenv import load_dotenv

load_dotenv()

TODAY = date.today()


def seed():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM bookings")
        conn.execute(
            "INSERT INTO bookings (booking_id, guest_last_name, property_name, check_in_date, check_out_date, status) VALUES "
            "(%s, %s, %s, %s, %s, %s), "
            "(%s, %s, %s, %s, %s, %s), "
            "(%s, %s, %s, %s, %s, %s)",
            (
                "BKG-001", "Smith",   "Pelican Beach 1006", TODAY + timedelta(days=1),  TODAY + timedelta(days=8),  "confirmed",
                "BKG-002", "Johnson", "Pelican Beach 707",  TODAY + timedelta(days=30), TODAY + timedelta(days=37), "confirmed",
                "BKG-003", "Davis",   "Okaloosa 3BR",       TODAY - timedelta(days=5),  TODAY + timedelta(days=2),  "cancelled",
            ),
        )
        print(f"Seeded 3 bookings relative to {TODAY}")
        print(f"  BKG-001 Smith     check-in {TODAY + timedelta(days=1)}  (confirmed, within window)")
        print(f"  BKG-002 Johnson   check-in {TODAY + timedelta(days=30)} (confirmed, too early)")
        print(f"  BKG-003 Davis     check-in {TODAY - timedelta(days=5)}  (cancelled)")


if __name__ == "__main__":
    seed()
