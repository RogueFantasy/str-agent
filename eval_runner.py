import time
import json
from agent import handle_message
from seed import seed
seed()

# --- Step 1: load the test cases ---
with open("golden-eval-set.json") as f:
    cases = json.load(f)

# --- Step 2: loop over each case and score it ---
INPUT_PRICE = 0.80 / 1_000_000
OUTPUT_PRICE = 4.00 / 1_000_000
total_cost = 0.0
total_latency = 0.0
passed = 0

for case in cases:
    contextual = f"[Booking: Pelican Beach 1006]\n{case['message']}"
    t0 = time.perf_counter()
    result = handle_message(contextual)
    latency_s = time.perf_counter() - t0
    usage = result.get("_usage", {}) or {}
    cost_usd = usage.get("input_tokens", 0) * INPUT_PRICE + usage.get("output_tokens", 0) * OUTPUT_PRICE
    total_cost += cost_usd
    total_latency += latency_s

    intent = result.get("intent")
    escalate = result.get("should_escalate")
    draft = result.get("draft_response", "").lower()

    # --- Step 3: compare agent's answer to the case's correct answer ---
    intent_ok = intent == case["expected_intent"]
    escalate_ok = escalate == case["expected_escalate"]

    # must_include is now a list of SYNONYM GROUPS.
    # for each group, at least one synonym must appear in the draft.
    must_include = case.get("must_include", [])
    include_ok = all(
        any(syn.lower() in draft for syn in group)
        for group in must_include
    )

    # must_not stays flat — any forbidden phrase fails the case
    must_not = case.get("must_not", [])
    no_violations = not any(kw.lower() in draft for kw in must_not)

    case_passed = intent_ok and escalate_ok and include_ok and no_violations

    if case_passed:
        passed += 1

    mark = "PASS" if case_passed else "FAIL"
    print(f"[{mark}] case {case['id']:>2}: {case['title']}  ({latency_s:.2f}s  ${cost_usd:.5f})")
    if not case_passed:
        if not intent_ok:    print(f"         intent: got {intent}, expected {case['expected_intent']}")
        if not escalate_ok:  print(f"         escalate: got {escalate}, expected {case['expected_escalate']}")
        if not include_ok:
            # show which group(s) missed entirely
            missed = [g for g in must_include if not any(syn.lower() in draft for syn in g)]
            print(f"         missing a synonym from each of: {missed}")
        if not no_violations:
            hit = [kw for kw in must_not if kw.lower() in draft]
            print(f"         contained forbidden phrase: {hit}")

# --- Step 4: print the final tally ---
print(f"\n{passed}/{len(cases)} cases passed")
print(f"total cost: ${total_cost:.4f}   per-message avg: ${total_cost/len(cases):.5f}   avg latency: {total_latency/len(cases):.2f}s")
