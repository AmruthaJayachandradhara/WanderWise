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
