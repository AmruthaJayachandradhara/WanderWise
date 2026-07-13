# Demo Fixtures

Captured responses for offline demo replay (no live API calls required).

Run the Japan demo live once with API keys set (`DUFFEL_API_KEY`, `GEMINI_API_KEY`,
`QDRANT_URL`), then capture:

```bash
uv run python -c "
from backend.app.orchestrator.graph import graph
import json

result = graph.invoke({'user_id': 'demo-user', 'query': 'Plan a 7-day trip to Tokyo, budget \$6000'})
with open('data/fixtures/duffel_flights_japan.json', 'w') as f:
    json.dump(result.get('flights'), f, indent=2)
with open('data/fixtures/duffel_stays_japan.json', 'w') as f:
    json.dump(result.get('hotels'), f, indent=2)
with open('data/fixtures/rag_japan_us_passport.json', 'w') as f:
    json.dump({'rag_results': result.get('rag_results'), 'visa_answer': result.get('visa_answer')}, f, indent=2)
print('Fixtures captured.')
"
```

Files:
- `duffel_flights_japan.json` — SFO→TYO flight offers
- `duffel_stays_japan.json` — Tokyo hotel offers
- `rag_japan_us_passport.json` — RAG result for US passport → Japan

These let the recruiter demo run when sandboxes are flaky or the Gemini daily
quota is tight. Capture is deferred until live API keys are available.

## Phase 4 — full multi-passport narrative

Captures the entire headline demo query end-to-end: query decomposition
(two passports), Duffel flight + hotel booking, a mock restaurant
reservation, the auto-created calendar hold, and the drafted (never
auto-sent) itinerary email. The run pauses at the confirmation gate
(`langgraph.types.interrupt`) partway through, so capture is two calls —
the initial invoke and the approved resume — against the same `thread_id`:

```bash
uv run python -c "
from langgraph.types import Command
from backend.app.orchestrator.graph import graph
import json

config = {'configurable': {'thread_id': 'fixture-japan-two-passports'}}
query = (
    'Plan a Japan trip for me and my partner — I have a US passport, she has '
    'an Indian passport. Book us a flight and hotel to Tokyo, a dinner '
    'reservation, and tell us if we need visas. Budget \$5000.'
)

first = graph.invoke({'user_id': 'demo-user', 'query': query}, config=config)
assert '__interrupt__' in first, 'expected the run to pause at the confirmation gate'

result = graph.invoke(Command(resume={'approved': True}), config=config)

with open('data/fixtures/narrative_japan_two_passports.json', 'w') as f:
    json.dump({
        'query': query,
        'sub_queries': result.get('sub_queries'),
        'visa_answer': result.get('visa_answer'),
        'selected_flight': result.get('selected_flight'),
        'selected_hotel': result.get('selected_hotel'),
        'selected_restaurant': result.get('selected_restaurant'),
        'confirmations': result.get('confirmations'),
        'calendar_ics': result.get('calendar_ics'),
        'email_draft': result.get('email_draft'),
        'email_status': result.get('email_status'),
        'summary': result.get('summary'),
    }, f, indent=2)
print('Fixture captured.')
"
```

Note: this needs the Gemini free-tier *daily* quota to have headroom — a
quota-exhausted run still completes (via the Groq/tier-demotion fallback
chain), but the captured text reflects the fallback model's quality, not
the primary model's. Re-run once quota resets if the captured summary
looks off. `backend/tests/eval/dataset.jsonl` has two `ci_skip: true`
cases (`decompose-narrative-two-passports-japan`,
`booking-narrative-tokyo-full-stack`) that exercise this same path — run
`uv run python backend/tests/eval/run_eval.py --all` to check them
without a full fixture capture.
