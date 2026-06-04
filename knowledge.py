import os
import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_property(name):
    """Fetch one property's facts from Postgres. Returns a dict, or None if not found."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute(
            "SELECT name, check_in_time, check_out_time, wifi_name, wifi_password, "
            "parking_info, pet_policy, amenities, supply_policy "
            "FROM properties WHERE name = %s",
            (name,),
        ).fetchone()

    if row is None:
        return None
    return {
        "name": row[0],
        "check_in_time": row[1],
        "check_out_time": row[2],
        "wifi_name": row[3],
        "wifi_password": row[4],
        "parking_info": row[5],
        "pet_policy": row[6],
        "amenities": row[7],
        "supply_policy": row[8],
    }


def format_for_prompt(prop):
    """Turn a property dict into a text block to paste into the system prompt."""
    if prop is None:
        return "no property data available"
    return (
        f"PROPERTY DATA — {prop['name']}\n"
        f"- Check-in: {prop['check_in_time']} | Check-out: {prop['check_out_time']}\n"
        f"- Wifi: network '{prop['wifi_name']}', password '{prop['wifi_password']}'\n"
        f"- Parking: {prop['parking_info']}\n"
        f"- Pet policy: {prop['pet_policy']}\n"
        f"- Amenities: {prop['amenities']}\n"
        f"- Supplies: {prop['supply_policy']}"
    )

def verify_booking(booking_id, guest_last_name):
    """
    Check if a booking is valid for releasing codes.
    Returns one of:
      'confirmed'   — booking exists, name matches, check-in is today or tomorrow → safe to release codes
      'outside_window'   — booking exists and matches but check-in is more than 2 days out
      'mismatch'    — booking_id exists but last name doesn't match
      'not_found'   — no booking with that id
      'cancelled'   — booking exists but is cancelled
    """
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute(
            "SELECT guest_last_name, status, check_in_date "
            "FROM bookings WHERE booking_id = %s",
            (booking_id,),
        ).fetchone()

    if row is None:
        return "not_found"

    stored_name, status, check_in_date = row

    if status == "cancelled":
        return "cancelled"
    if stored_name.lower() != guest_last_name.lower():
        return "mismatch"

    from datetime import date
    days_until = (check_in_date - date.today()).days
    if days_until < 0 or days_until > 2:
        return "outside_window"

    return "confirmed"


def get_access_codes(property_name):
    """Return door_code and building_code for a property. Only call after verify_booking == 'confirmed'."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute(
            "SELECT door_code, building_code FROM properties WHERE name = %s",
            (property_name,),
        ).fetchone()
    if row is None:
        return None
    return {"door_code": row[0], "building_code": row[1]}


def log_event(guest_message, result, tools_used, iterations, codes_released):
    """Append one row to agent_log. Best-effort — never let a logging failure crash the agent."""
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
            conn.execute(
                "INSERT INTO agent_log "
                "(guest_message, intent, should_escalate, draft_response, tools_used, iterations, codes_released) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    guest_message,
                    result.get("intent"),
                    result.get("should_escalate"),
                    result.get("draft_response"),
                    ",".join(tools_used) if tools_used else None,
                    iterations,
                    codes_released,
                ),
            )
    except Exception as e:
        print(f"[log_event failed: {e}]")


if __name__ == "__main__":
    # property lookup
    print(format_for_prompt(get_property("Pelican Beach 1006")))
    print()

    # verification tests
    print("BKG-001 / Smith   (happy path):  ", verify_booking("BKG-001", "Smith"))
    print("BKG-001 / Jones   (mismatch):    ", verify_booking("BKG-001", "Jones"))
    print("BKG-002 / Johnson (too early):   ", verify_booking("BKG-002", "Johnson"))
    print("BKG-003 / Davis   (cancelled):   ", verify_booking("BKG-003", "Davis"))
    print("BKG-999 / Smith   (not found):   ", verify_booking("BKG-999", "Smith"))
    print()
    print("Codes for Pelican Beach 1006:   ", get_access_codes("Pelican Beach 1006"))

