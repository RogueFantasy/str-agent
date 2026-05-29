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


if __name__ == "__main__":
    # quick test: fetch and print one property
    prop = get_property("Pelican Beach 1006")
    print(format_for_prompt(prop))
    print()
    print("Missing property test:")
    print(format_for_prompt(get_property("Nonexistent")))
