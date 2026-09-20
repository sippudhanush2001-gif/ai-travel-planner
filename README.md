# AI Travel Planner

A multi-agent **AI travel planning assistant** with a **human-in-the-loop
approval** gate, built on **LangGraph** and served with **FastAPI**.

The user submits a travel request (destination, dates, budget, interests,
travelers). The system researches the destination, builds a day-by-day
itinerary, pauses for the user to **approve / revise / modify**, and only then
produces the finalized plan.

```
User ──POST /plan──▶ Orchestrator (LangGraph StateGraph)
                        │
                        ▼
                  ┌─────────────┐   web_search (Serper/Exa)
                  │   Research   │   weather_forecast (Open-Meteo)
                  │    Agent     │
                  └──────┬──────┘
                         ▼
                  ┌─────────────┐   places_database (curated KB)
                  │  Itinerary   │   local_guides (restaurants, packing)
                  │    Agent     │
                  └──────┬──────┘
                         ▼
                  ┌─────────────┐        ┌────────────────────────┐
                  │    Review    │──HITL──▶ approve  ──▶ finalize   │
                  │  (interrupt) │◀──────── revise  ──▶ research/plan
                  └─────────────┘          modify   ──▶ plan       │
                          │                                    │
                          │   state persisted in SQLite        ▼
                          ▼                             GET /plan/{id}/final
                  Finalized Plan ───────────────────────────────────────────
```

## What's inside

| Layer | Contents |
| ----- | -------- |
| `app/orchestrator` | LangGraph `StateGraph`: `validate → research → plan → review → finalize`. The `review` node calls `interrupt()` for HITL; it is resumed with `Command(resume=...)`. State is checkpointed to SQLite and survives restarts. |
| `app/agents` | A small, transparent ReAct runner (`agent.py`) + the two agents. **Research Agent** tools: `web_search` (Serper / Exa / mock) and `weather_forecast` (Open-Meteo / mock). **Itinerary Agent** tools: `places_database` (curated attraction KB matched to interests) and `local_guides` (restaurants, packing list, local tips). |
| `app/planning` | Deterministic builders that turn raw tool output into schema-valid documents. Used by the offline mock and as a JSON-repair fallback if a real LLM misbehaves. |
| `app/runtime` | `WorkflowManager`: creates plans (thread id = plan_id), executes/resumes the graph in background threads, reads status from the checkpointer, serializes access to SQLite. |
| `app/core` | LLM provider abstraction (`mock` / `openai` / `anthropic`) + `MockChatModel`, a scripted deterministic model that exercises the same tools a real LLM would, so the app runs fully offline. |
| `app/api` | FastAPI routes (see API below). |
| `tests` | `pytest` suite covering the builder logic, the full graph + HITL cycle, and the HTTP API (all offline). |

## Requirements

- Python **3.11+** (developed and tested on 3.12)
- Network access only needed for real providers (Serper/Exa/OpenAI/Anthropic);
  Open-Meteo weather is keyless.

## Setup

```bash
cd ai-travel-planner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # or: uv pip install -r requirements.txt
cp .env.example .env                     # optional: add API keys
```

> The app runs **end-to-end with no API keys** — `LLM_PROVIDER=mock`,
> `WEB_SEARCH_PROVIDER=mock`, `WEATHER_PROVIDER=openmeteo` are the defaults
> (Open-Meteo is free and keyless).

### Enabling real providers

Edit `.env`:

```ini
LLM_PROVIDER=openai           # or anthropic
OPENAI_API_KEY=sk-...

WEB_SEARCH_PROVIDER=serper    # or exa
SERPER_API_KEY=...

WEATHER_PROVIDER=openmeteo    # free, keyless
```

Each real provider degrades gracefully to curated fallback content (marked in
`research.sources`) if a call fails, so a plan is always still produced.

## Running

### 1) HTTP API

```bash
uvicorn app.main:app --reload --port 8000
```

Interactive docs open at <http://127.0.0.1:8000/docs> (OpenAPI).

### 2) CLI demo (no server)

```bash
python -m app.cli          # or: travel-planner  (after `pip install -e .`)
```

Runs a sample Paris trip through revise → modify → approve and prints the final
plan.

### 3) Tests

```bash
pytest -v
```

## API

All example calls use the default **mock** configuration (no keys needed).

### `POST /plan` — submit a travel request

```bash
curl -X POST http://127.0.0.1:8000/plan \
  -H 'Content-Type: application/json' \
  -d '{
    "destination": "Paris",
    "start_date": "2026-10-11",
    "end_date": "2026-10-15",
    "budget": {"min_amount": 1800, "max_amount": 3500, "currency": "USD"},
    "interests": ["art", "food", "culture"],
    "travelers": 2,
    "travel_style": "cultural"
  }'
```

```json
{
  "plan_id": "07df8e2f929d4012a1bf0ebdeef03170",
  "phase": "review",
  "message": "Draft itinerary ready for review."
}
```

### `GET /plan/{id}` — current status + draft

```bash
curl http://127.0.0.1:8000/plan/07df8e2f929d4012a1bf0ebdeef03170
```

```json
{
  "plan_id": "07df8e2f929d4012a1bf0ebdeef03170",
  "phase": "review",
  "message": "Draft itinerary is ready. Approve, revise, or modify.",
  "draft_plan": {
    "destination": "Paris",
    "start_date": "2026-10-11",
    "end_date": "2026-10-15",
    "budget_min": 1800.0,
    "budget_max": 3500.0,
    "days": [
      {
        "day": 1,
        "title": "Arrival & Orientation",
        "activities": [
          {"title": "Eiffel Tower", "time": "morning", "area": "Champ de Mars", "tip": "Pre-book elevator tickets."}
        ]
      }
    ],
    "hotels": [{"name": "Comfort Central Champ de Mars", "price_per_night": 294.0, "rating": 4.2}],
    "budget_allocation": {"housing": 1113.0, "food": 636.0, "transport": 477.0, "activities": 318.0, "misc": 6.0, "total": 2550.0}
  },
  "revisions": 0,
  "can_review": true,
  "created_at": "2026-09-20T14:20:00",
  "updated_at": "2026-09-20T14:20:01"
}
```

### `POST /plan/{id}/review` — human-in-the-loop feedback

**Approve:**

```bash
curl -X POST http://127.0.0.1:8000/plan/{id}/review \
  -H 'Content-Type: application/json' -d '{"action": "approve"}'
```

**Reject with comments** (routes back to the planner or the researcher):

```bash
curl -X POST http://127.0.0.1:8000/plan/{id}/review \
  -H 'Content-Type: application/json' \
  -d '{"action": "revise", "comments": "Swap day 2 lunch to seafood; add a quiet morning.", "target": "plan"}'
```

**Modify specific parts** (hotel, per-day activities, budget):

```bash
curl -X POST http://127.0.0.1:8000/plan/{id}/review \
  -H 'Content-Type: application/json' \
  -d '{
        "action": "modify",
        "modifications": {
          "hotel": "Boutique Le Marais",
          "budget": {"max": 4200},
          "days": {"1": {"title": "Seine & Old Town", "activities": [{"title": "Seine River cruise", "time": "afternoon"}]}}
        }
      }'
```

Each approved / revised / modified plan drops back into `review` so the user
sees the newest draft before the final approval. A revision cap
(`MAX_REVISIONS`, default 3) prevents infinite loops: at the cap the latest
draft is finalized (with a note) instead of revising again.

### `GET /plan/{id}/final` — finalized plan

Only available **after** approval (otherwise `409 Conflict`).

```bash
curl http://127.0.0.1:8000/plan/{id}/final
```

```json
{
  "plan_id": "07df8e2f929d4012a1bf0ebdeef03170",
  "final_plan": {
    "destination": "Paris",
    "days": [ /* full day-by-day itinerary */ ],
    "hotels": [ /* 1–2 options within budget */ ],
    "restaurants": [ /* curated picks */ ],
    "packing_list": [ /* season-aware */ ],
    "local_tips": ["Metro is best.", "Book dinners ahead."]
  }
}
```

### Status codes

| Code | Meaning |
| ---- | ------- |
| `201` | Plan created (`POST /plan`) |
| `200` | Success (`GET /plan/{id}`, `POST /plan/{id}/review`, `GET /plan/{id}/final`) |
| `404` | Unknown plan id |
| `409` | Review submitted when not paused, or `final` requested before approval |
| `422` | Request validation failure (README-visible error detail) |

## Design decisions & tradeoffs

- **State = the checkpoint.** The LangGraph state (request, research, draft,
  feedback, phase) is the single source of truth, written to SQLite. This gives
  us the HITL pause that survives process restarts for free, and kills the
  need for a parallel "plan store".
- **`interrupt()` instead of resume validation hacks.** The graph pauses inside
  the `review` node; `POST /review` resumes it with a `Command`. Routing back to
  `research` or `plan` on revise is just a conditional edge.
- **Custom ReAct loop vs `create_react_agent`.** A ~60 line runner is clear,
  provider-agnostic, easy to test, and keeps the tool surface explicit (2 tools
  per agent as specified). We trade the prebuilt agent's streaming/memory
  conveniences for transparency — acceptable for this scope.
- **Deterministic builders as safety net.** Real LLMs return JSON with a strict
  prompt contract; if it isn't parseable, the deterministic builder still
  produces a valid document from the tool outputs. Guarantees the API never
  returns a malformed plan.
- **Offline-first, mock everywhere.** `MockChatModel` runs the *same* tool-use
  sequence a real model would, so the workflow and tests run hermetic without
  keys, and each real provider falls back to curated data on failure.
- **Threading + SQLite.** The legacy `SqliteSaver` is not thread-safe, so a
  per-plan lock serializes access. Fine for a single-process API; see below for
  the multi-process answer.
- **Timeouts & refused requests.** Background threads + configurable timeouts
  keep `POST /plan` responsive even when external APIs are slow.

### Trade-offs you should know about

1. **Single-process only.** SQLite checkpointing doesn't scale to multiple
   `uvicorn` workers. For horizontal scaling we'd swap the saver for a Postgres
   checkpointer (LangGraph supports it natively).
2. **Blocking background threads.** Good enough for a local assignment; in
   production we'd run a worker pool or a job queue (Redis/celery) and poll.
3. **Curated places data.** The `places_database` covers a handful of cities;
   unknown destinations fall back to research-report attractions. In production
   this would be a real POI provider (Google Places / OSM).
4. **Mock weather** uses seasonal estimates, clearly labelled.
5. **No auth/rate-limiting/quotas** — intentionally out of scope.

## What I'd improve with more time

- **Contract-test the LLM JSON** with `with_structured_output()` / tool-calling
  schemas instead of prompt-only JSON (more reliable than the repair fallback).
- **Real streaming** progress (research → planning → awaiting review) via SSE or
  WebSocket, so long research calls feel interactive.
- **Revision diffing** in the review payload, so users see *what changed* after
  a revise/modify rather than a whole new draft.
- **More planner tools** (distance/travel-time calculator, budget optimizer,
  restaurant/events APIs) and deeper HITL (per-activity edits instead of
  whole-day swaps).
- **Observability**: LangSmith tracing, structured logging, and synthetic
  end-to-end tests against a stub LLM.
- **Provider-agnostic structured output** and a pluggable tool registry so new
  tools/agents are added declaratively.

## Production concerns

- **Persistence**: Postgres checkpointer for multi-instance HA; back up the DB.
- **Security**: validate/lint user input before it reaches any grounding service;
  maintain internal calls to the LLM provider behind a server-side gateway.
- **Reliability**: retries + exponential backoff for provider calls, circuit
  breakers on the search/weather tools, dead-letter handling for failed plans.
- **Cost**: request/cost quotas per user; cache research results by
  `(destination, dates, interests)`.
- **Observability**: trace `plan_id` across agents, tools and the DB.
- **SLA**: async job executor + webhooks so a slow provider never blocks the API.

## Assumptions made

- A **modify** may look like a staged JSON object for specific parts of the plan
  (hotel, per-day activities, budget). A richer "natural language edit" surface
  (prompt the model to emit the same structure) is listed as a future step.
- Budget is treated as total trip budget for the party (`travelers`).
- `end_date == start_date` means a valid 1-day trip (0 nights).
- Research reports are free-form but structured; the orchestrator schemas-validates
  everything before it is returned to the user.

## Project layout

```
ai-travel-planner/
├── app/
│   ├── main.py               # FastAPI factory
│   ├── config.py             # pydantic-settings (env/.env)
│   ├── models/schemas.py     # Pydantic API + plan-document models
│   ├── core/
│   │   ├── llm.py            # provider factory + MockChatModel
│   │   └── prompts.py        # agent system prompts (strict-JSON contracts)
│   ├── agents/
│   │   ├── agent.py          # ReAct runner
│   │   ├── research.py       # Agent 1
│   │   ├── itinerary.py      # Agent 2
│   │   └── tools/            # web_search, weather, places_db, local_guides
│   ├── planning/builders.py  # deterministic document builders (repair fallback)
│   ├── orchestrator/         # StateGraph, nodes, HITL interrupt, SQLite saver
│   ├── runtime/manager.py    # plan lifecycle + background execution
│   ├── api/routes.py         # HTTP endpoints
│   └── cli.py                # offline demo
├── tests/                    # pytest (builders, graph/HITL, API)
├── storage/                  # SQLite checkpoints (gitignored, created at runtime)
├── requirements.txt
├── pyproject.toml
└── .env.example
```

## License

MIT (this is a take-home assignment deliverable).