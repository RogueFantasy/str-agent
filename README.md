# str-agent

An AI agent that triages and drafts replies to vacation-rental guest messages — classifying intent, pulling property facts from Postgres, verifying bookings before releasing door codes, and escalating to a human whenever a safe draft isn't possible.

Built as a learning project: one agent, three tools, a golden eval set, and a hard rule that every change must hold 20/20 on the evals before it ships.

## The numbers

| Metric | Value |
|---|---|
| Golden eval set | **20/20 passing** |
| Cost per message | **$0.0048** avg |
| Latency per message | **3.97s** avg |
| Model | `claude-haiku-4-5` at temperature 0 |

Cost and latency are measured by the eval runner itself on every run, so regressions in any of the three show up immediately.

## Architecture

```
guest message
     │
     ▼
┌─────────────────────────────────────────────┐
│ agent.py — handle_message()                 │
│                                             │
│  input guard (empty / oversized → escalate) │
│  conversation memory (last 10 turns)        │
│  tool-use loop (max 5 iterations, retry w/  │
│  exponential backoff)                       │
│  output guard (regex: $-amounts, code leak  │
│  without verified booking → force escalate) │
└──────┬──────────────────────────────┬───────┘
       │ tools                        │ audit
       ▼                              ▼
┌──────────────────────┐      ┌──────────────┐
│ knowledge.py         │      │  agent_log   │
│  get_property        │      └──────────────┘
│  verify_booking      │
│  get_access_codes    │              Postgres tables:
└──────┬───────────────┘              properties, bookings,
       ▼                              agent_log, conversations
   PostgreSQL
```

- **`agent.py`** — the agent loop. Classifies each message into one of six intents (`prebooking`, `checkin_logistics`, `midstay_issue`, `complaint`, `review`, `escalate_only`), decides whether to escalate, and drafts a reply under 120 words. Returns structured JSON with sources used and steps taken.
- **`knowledge.py`** — all database access. The access-code flow is the security-critical path: `verify_booking` checks booking ID + last name + check-in window (today or tomorrow only) and returns `confirmed` / `outside_window` / `mismatch` / `cancelled` / `not_found`; codes are only released on `confirmed`. A regex output guard backstops the model: if a draft contains something code-shaped and no booking was verified this turn, the draft is discarded and the message escalates.
- **`eval_runner.py`** — runs all 20 golden cases and scores four things per case: intent, escalation flag, must-include synonym groups, and must-not forbidden phrases. Prints per-case cost and latency.
- **`golden-eval-set.json`** — 20 cases spanning all six intents, including adversarial ones (code request with wrong last name, refund demands, legal threats, hurricane cancellation questions).
- **`seed.py`** — seeds bookings with check-in dates *relative to today*, so the verification-window tests don't rot.
- **`mcp_server.py`** — exposes the same three tools over MCP (stdio), so any MCP client (e.g. Claude Code, Claude Desktop) can use the property/booking knowledge base directly.

## How to run

Requires Python 3.11+, PostgreSQL, and an Anthropic API key.

```bash
git clone <repo-url> && cd str-agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cat > .env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://user:pass@localhost/str_agent
EOF
```

Create the schema and demo properties (tables + three demo property rows; bookings are seeded separately so dates stay relative to today):

```bash
psql "$DATABASE_URL" -f schema.sql
```

Then:

```bash
python db_test.py       # sanity-check the Postgres connection
python seed.py          # seed bookings relative to today's date
python eval_runner.py   # run all 20 golden cases (re-seeds automatically)
python agent.py         # demo: one guest message through the full loop
```

To use the knowledge base from Claude Code as an MCP server:

```bash
claude mcp add str-agent -- /path/to/venv/bin/python /path/to/str-agent/mcp_server.py
```

## Deliberately deferred (and why)

These were considered and cut, not overlooked. Each stays out until the eval set or real traffic proves it's needed.

- **Multi-agent orchestration.** One model call with three tools handles every case in the eval set. A classifier-agent → drafter-agent → reviewer-agent pipeline would roughly triple cost and latency for zero measured accuracy gain at this scale. Smaller surface, fewer failure modes. Revisit if intent count grows past what one prompt can hold.

- **Conversation summarization.** Multi-turn memory loads the last 10 raw turns from Postgres. Guest threads are short (a few messages), so summarization would add an extra LLM call per message to compress context that already fits. Becomes worth it when threads regularly exceed the window.

- **LLM-as-judge evals.** The eval runner scores with deterministic checks: exact intent match, exact escalation flag, synonym groups for must-include phrases, and a must-not blocklist. That's free, instant, and perfectly reproducible — no judge variance, no judge cost, no "judge drifted" debugging. The tradeoff is brittleness (the prompt has to teach specific draft wording), which is acceptable at 20 cases. An LLM judge earns its place when the rubric outgrows string matching — e.g. scoring tone or factual grounding.

- **Property resolver.** Messages arrive with a `[Booking: <property name>]` prefix, mirroring how a rental platform delivers messages already attached to a listing — so the agent never guesses which property a guest means. Fuzzy resolution from free text ("the beachfront condo") is a real problem, but solving it before having real inbound message data would be guessing at the input distribution.

Known gaps that are *debt*, not deferral: no migration tooling (`schema.sql` is create-only, no versioning), and `conversations` memory isn't used by the eval set yet.
