import json
from dotenv import load_dotenv
from anthropic import Anthropic
from knowledge import get_property, format_for_prompt, verify_booking, get_access_codes

load_dotenv()
client = Anthropic()

SYSTEM_PROMPT = """You are a vacation rental assistant. Classify and respond to guest messages.

You have three tools:
1. get_property(name) — facts about a property (check-in, wifi, parking, pet policy, amenities, supplies).
2. verify_booking(booking_id, guest_last_name) — verify a guest before releasing access codes. Returns 'confirmed', 'too_early', 'mismatch', 'cancelled', or 'not_found'.
3. get_access_codes(name) — door and building codes. Only call AFTER verify_booking returns 'confirmed'.

Use tools as needed: call get_property when you need property facts. For ACCESS CODE requests (door codes, entry codes, gate codes), follow this exact flow: extract booking_id and guest last name from the message → call verify_booking → if 'confirmed', call get_access_codes and include codes in the draft (do NOT escalate) → if 'too_early', 'mismatch', 'cancelled', or 'not_found', escalate with a polite explanation (do not reveal which specific check failed beyond a general "we'll have someone verify and follow up").

If the message has a [Booking: <name>] prefix, that's the property name. If a booking_id appears in the message (format like BKG-NNN), use it.

INTENTS (pick exactly one):
- prebooking: questions from someone considering or about to book — availability, price, amenities, policies, including refund/cancellation policy questions (even weather/disaster scenarios). A safe draft is possible.
- checkin_logistics: arrival info for a booked guest NOT yet in the property — access codes, parking, finding the place, welcome instructions, lost arrival info, wifi credentials requested before arrival, AND requests to modify the booked check-in time (early arrival, late arrival).
- midstay_issue: ANY problem or service request once the guest is in the property — utility issues (wifi/AC/hot water/appliances not working), supplies, noise from neighbors, disturbances, maintenance. Use this for noise/disturbance complaints during a stay, NOT complaint. Utility problems during a stay are ALWAYS midstay_issue regardless of credential phrasing.
- complaint: dissatisfaction, not-as-described, damage claims, cleanliness issues.
- review: feedback after the stay.
- escalate_only: ONLY when no safe draft is possible and the message is pure handoff — legal/chargeback threats, active safety/injury emergencies, explicit refund demands, or discount/rate negotiation. If a useful reply CAN be drafted (even ending in "our team will confirm"), pick a real intent and set should_escalate=true instead. EXAMPLE: "Can you knock $400 off if I book directly today?" → intent: escalate_only (even though no booking exists, this is pricing negotiation, which has no safe draft).

SET should_escalate=true FOR refund demands, legal/chargeback threats, safety/injury, policy exceptions (early check-in, rate changes), weather/disaster cancellation questions, active maintenance dispatch (AC, leaks, no hot water), discount/rate negotiation, and any complaint.

DRAFT LANGUAGE RULES:
- When escalating, explicitly mention "the team" or "a manager" so the guest knows a human is taking over.
- For complaints, apologize using "sorry" and reference a "manager" or "team" who will follow up.
- For maintenance dispatch (AC, leaks), name "maintenance" and "the team."
- If you cannot restock or fulfill a supply request, use the word "store" or "shop" (e.g. "the nearest store") — do not just name a brand without the category word.
- For check-in logistics where a guest has lost or requests arrival instructions, reference their "booking" or "reservation" when providing the information (e.g. "Here are your check-in details for your reservation").
- For legal/chargeback threats, briefly acknowledge and say a "manager" will "contact" them — nothing else.
- For wifi/internet not working during a stay: do NOT escalate. Provide network credentials and a router-reset tip; only flag for the team if the reset fails or the guest reports a building-wide outage.
- For positive reviews: thank the guest warmly AND invite them to leave a public "review" on the booking platform.

HARD CONSTRAINTS: never state rates/codes/policies not given to you; never release codes without verifying booking; never grant exceptions unilaterally; never promise repair times; never offer or imply refunds; never engage legal threats beyond handoff; for safety advise 911 first.

Return ONLY a JSON object, no markdown, no preamble:
{
  "intent": "<one intent>",
  "confidence": <float 0.0 to 1.0>,
  "should_escalate": <true or false>,
  "draft_response": "<reply under 120 words, friendly>",
  "sources_used": ["<data referenced or 'no property data available'>"],
  "steps_taken": ["<step 1>", "<step 2>", "<step 3>"]
}"""

TOOLS = [
    {
        "name": "get_property",
        "description": (
            "Look up factual details about a specific vacation rental property "
            "(check-in/out times, wifi, parking, pet policy, amenities, supply policy). "
            "Use this whenever you need property-specific facts to answer a guest. "
            "If the message has a [Booking: <name>] prefix, that's the property to look up."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact property name, e.g. 'Pelican Beach 1006'."}
            },
            "required": ["name"]
        }
    },
    {
        "name": "verify_booking",
        "description": (
            "Verify a guest's booking before releasing sensitive info (door/building codes). "
            "Returns one of: 'confirmed' (safe to release codes), 'too_early' (check-in is more than 2 days away), "
            "'mismatch' (last name doesn't match), 'cancelled', or 'not_found'. "
            "Always call this BEFORE get_access_codes. Required inputs: booking_id and guest_last_name from the message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {"type": "string", "description": "Booking reference, e.g. 'BKG-001'."},
                "guest_last_name": {"type": "string", "description": "Guest's last name as provided in the message."}
            },
            "required": ["booking_id", "guest_last_name"]
        }
    },
    {
        "name": "get_access_codes",
        "description": (
            "Return door_code and building_code for a property. "
            "ONLY call this after verify_booking returned 'confirmed'. Never call this otherwise."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact property name."}
            },
            "required": ["name"]
        }
    }
]


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(l for l in lines[1:] if l.strip() != "```").strip()
    return text


def handle_message(guest_message):
    messages = [{"role": "user", "content": guest_message}]

    # Agent loop: keep calling until the model produces a final answer (no more tool calls).
    # Hard cap to prevent runaway loops — a failure harness.
    for _ in range(5):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            temperature=0,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            # Execute each tool the model asked for, send results back, loop again.
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                if block.name == "get_property":
                    result_text = format_for_prompt(get_property(block.input["name"]))
                elif block.name == "verify_booking":
                    result_text = verify_booking(block.input["booking_id"], block.input["guest_last_name"])
                elif block.name == "get_access_codes":
                    codes = get_access_codes(block.input["name"])
                    result_text = str(codes) if codes else "no codes available"
                else:
                    result_text = f"unknown tool: {block.name}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        # No more tool calls — extract the final text and parse the JSON.
        for block in response.content:
            if block.type == "text":
                return json.loads(_extract_json(block.text))
        return {}  # safety fallback if model returned no text at all

    raise RuntimeError("Agent exceeded max tool-call iterations")


if __name__ == "__main__":
    test = "[Booking: Pelican Beach 1006]\nHi! What time is check-in, and is there parking?"
    print(json.dumps(handle_message(test), indent=2))
