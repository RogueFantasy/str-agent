import logging
import os
from datetime import date

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _connect(**kwargs):
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, **kwargs)


def get_property(name):
    """Fetch one property's facts from Postgres. Returns a dict, or None if not found."""
    with _connect() as conn:
        return conn.execute(
            "SELECT name, check_in_time, check_out_time, wifi_name, wifi_password, "
            "parking_info, pet_policy, amenities, supply_policy "
            "FROM properties WHERE name = %s",
            (name,),
        ).fetchone()


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
    Returns (status, property_name). property_name is set only on 'confirmed',
    so callers can bind code release to the verified booking's property.
    Status is one of:
      'confirmed'        — booking exists, name matches, check-in is today or tomorrow
      'outside_window'   — booking exists and matches but check-in is more than 2 days out
      'mismatch'         — booking_id exists but last name doesn't match
      'not_found'        — no booking with that id
      'cancelled'        — booking exists but is cancelled
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT guest_last_name, status, check_in_date, property_name "
            "FROM bookings WHERE booking_id = %s",
            (booking_id,),
        ).fetchone()

    if row is None:
        return "not_found", None
    if row["status"] == "cancelled":
        return "cancelled", None
    if row["guest_last_name"].lower() != guest_last_name.lower():
        return "mismatch", None

    days_until = (row["check_in_date"] - date.today()).days
    if days_until < 0 or days_until > 2:
        return "outside_window", None

    return "confirmed", row["property_name"]


def get_access_codes(property_name):
    """Return {door_code, building_code} for a property, or None. Callers must
    only release these for the property a confirmed booking is bound to."""
    with _connect() as conn:
        return conn.execute(
            "SELECT door_code, building_code FROM properties WHERE name = %s",
            (property_name,),
        ).fetchone()


def log_event(guest_message, result, tools_used, iterations, codes_released):
    """Append one row to agent_log. Best-effort — never let a logging failure crash the agent."""
    try:
        with _connect(autocommit=True) as conn:
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
        logger.warning("log_event failed: %s", e)


def load_conversation(conversation_id, max_turns=10):
    """Load the last N turns of a conversation, oldest first. Returns list of {role, content} dicts."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM conversations "
            "WHERE conversation_id = %s "
            "ORDER BY ts DESC LIMIT %s",
            (conversation_id, max_turns),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def save_turn(conversation_id, role, content):
    """Append one turn to the conversation. Fails open."""
    try:
        with _connect(autocommit=True) as conn:
            conn.execute(
                "INSERT INTO conversations (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conversation_id, role, content),
            )
    except Exception as e:
        logger.warning("save_turn failed: %s", e)


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
