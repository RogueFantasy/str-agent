import json
import re
import time
from dotenv import load_dotenv
from anthropic import Anthropic
from knowledge import get_property, format_for_prompt, verify_booking, get_access_codes, log_event

load_dotenv()
client = Anthropic()

FORBIDDEN = [r"\$\s?\d"]   # dollar amounts only — the model handles refund language via intent
CODE_LEAK = re.compile(r"\bcode\b.{0,40}\b\d{4}\b", re.IGNORECASE)


def _guard(result, codes_released):
    """Force escalation if the draft contains forbidden content."""
    if result.get("should_escalate"):
        return result
    draft = result.get("draft_response", "")
    leak = next((p for p in FORBIDDEN if re.search(p, draft, re.IGNORECASE)), None)
    if not leak and not codes_released and CODE_LEAK.search(draft):
        leak = "unverified code"
    if leak:
        result["should_escalate"] = True
        result["draft_response"] = ""
        result.setdefault("sources_used", []).append(f"output_guard: {leak}")
    return result


SYSTEM_PROMPT = """You are a vacation rental assistant. Classify and respond to guest messages.

You have three tools:
1. get_property(name) — facts about a property (check-in, wifi, parking, pet policy, amenities, supplies).
2. verify_booking(booking_id, guest_last_name) — verify a guest before releasing access codes. Returns 'confirmed', 'outside_window', 'mismatch', 'cancelled', or 'not_found'.
3. get_access_codes(name) — door and building codes. Only call AFTER verify_booking returns 'confirmed'.

Use tools as needed: call get_property when you need property facts. For ACCESS CODE requests (door codes, entry codes, gate codes), follow this exact flow: extract booking_id and guest last name from the message → call verify_booking → if 'confirmed', call get_access_codes and include codes in the draft (do NOT escalate) → if 'outside_window', 'mismatch', 'cancelled', or 'not_found', escalate with a polite explanation (do not reveal which specific check failed beyond a general "we'll have someone verify and follow up").

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
- For escalating-but-draftable situations, explicitly mention "the team" or "a manager" so the guest knows a human is taking over.
- For complaints: USE intent `complaint`. In the draft, apologize using "sorry" and reference a "manager" or "team" who will follow up.
- For maintenance dispatch (AC, leaks, no hot water): USE intent `midstay_issue` with should_escalate=true. In the draft, name "maintenance" and "the team."
- If you cannot restock or fulfill a supply request: USE intent `midstay_issue`. In the draft, use the word "store" or "shop" (e.g. "the nearest store") — do not just name a brand without the category word.
- For check-in logistics where a guest has lost or requests arrival instructions: USE intent `checkin_logistics`. You MUST include the word "booking" or "reservation" in your draft (e.g. "Here are your check-in details for your reservation").
- For legal/chargeback threats: USE intent `escalate_only`. Briefly acknowledge and say a "manager" will "contact" them — nothing else.
- For wifi/internet not working during a stay: USE intent `midstay_issue` with should_escalate=false. Provide network credentials and a router-reset tip; only flag for the team if the reset fails or the guest reports a building-wide outage.
- For positive reviews: USE intent `review`. Thank the guest warmly AND invite them to leave a public "review" on the booking platform.
- For safety/medical emergencies: USE intent `escalate_only`. In the draft, advise calling 911 AND seeking medical care or first aid immediately, then notify the team.

HARD CONSTRAINTS: never state rates/codes/policies not given to you; never release codes without verifying booking; never grant exceptions unilaterally; never promise repair times; never offer or imply refunds; never engage legal threats beyond handoff.

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
            "Returns one of: 'confirmed' (safe to release codes), 'outside_window' (check-in is more than 2 days away), "
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


def _call_with_retry(messages):
    """API call with 3-attempt exponential backoff. Returns response or raises."""
    for attempt in range(3):
        try:
            return client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600, temperature=0,
                system=SYSTEM_PROMPT, tools=TOOLS, messages=messages,
            )
        except Exception:
            time.sleep(2 ** attempt)
    raise RuntimeError("API failed after 3 retries")


def _run_tool(name, args):
    """Dispatch one tool call. Returns (result_text, released_codes)."""
    if name == "get_property":
        return format_for_prompt(get_property(args["name"])), False
    if name == "verify_booking":
        return verify_booking(args["booking_id"], args["guest_last_name"]), False
    if name == "get_access_codes":
        codes = get_access_codes(args["name"])
        return (str(codes) if codes else "no codes available"), bool(codes)
    return f"unknown tool: {name}", False


def _process_tool_calls(response, messages):
    """Run every tool_use block. Mutates messages. Returns (names, any_codes_released)."""
    tool_results, names, codes_released = [], [], False
    for block in response.content:
        if block.type != "tool_use":
            continue
        names.append(block.name)
        result_text, released = _run_tool(block.name, block.input)
        codes_released = codes_released or released
        tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})
    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": tool_results})
    return names, codes_released


def _extract_final(response, codes_released):
    """Find the text block and return the guarded result dict, or None."""
    for block in response.content:
        if block.type == "text":
            return _guard(json.loads(_extract_json(block.text)), codes_released)
    return None


def handle_message(guest_message):
    """Run the agent on one guest message. Returns a decision dict with intent, escalate, draft, and _usage."""
    if not guest_message or not guest_message.strip() or len(guest_message) > 4000:
        result = {"intent": "escalate_only", "should_escalate": True, "draft_response": "",
                  "sources_used": ["input_guard"], "steps_taken": ["bad input — escalated"]}
        log_event(guest_message or "", result, [], 0, False)
        return result

    messages = [{"role": "user", "content": guest_message}]
    tools_used, iterations, codes_released = [], 0, False
    input_tokens, output_tokens = 0, 0

    for _ in range(5):
        iterations += 1
        response = _call_with_retry(messages)
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens

        if response.stop_reason == "tool_use":
            names, released = _process_tool_calls(response, messages)
            tools_used.extend(names)
            codes_released = codes_released or released
            continue

        result = _extract_final(response, codes_released)
        if result is not None:
            result["_usage"] = {"input_tokens": input_tokens, "output_tokens": output_tokens}
            log_event(guest_message, result, tools_used, iterations, codes_released)
            return result
        result = {"_usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}}
        log_event(guest_message, result, tools_used, iterations, codes_released)
        return result

    raise RuntimeError("Agent exceeded max tool-call iterations")


if __name__ == "__main__":
    test = "[Booking: Pelican Beach 1006]\nHi! What time is check-in, and is there parking?"
    print(json.dumps(handle_message(test), indent=2))
