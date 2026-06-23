# Architecture

Digital Mate is a Telegram bot that acts as an AI-powered digital marketing assistant. It classifies user intent into one of four marketing pillars, dispatches to a specialized handler, and returns structured, actionable responses.

## Design Principles

- **Pillar-based routing** — A lightweight LLM call classifies messages before the "real" work happens. This keeps responses focused and lets each pillar have its own prompt, output format, and token budget.
- **Graceful degradation** — Every external integration (Notion, Tavily, web search) is optional. The bot works with just an LLM API key; everything else enhances the experience.
- **Security-first** — Input/output guards block prompt injection, role hijacking, and data exfiltration attempts before they reach the LLM.
- **Standalone** — No platform-specific dependencies. Runs anywhere Python 3.11+ is available.

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Telegram Bot API                      │
└──────────────────────────┬──────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   bot.py    │  Message handler
                    │             │  • Input guard (injection check)
                    │             │  • Typing indicator
                    │             │  • Output guard (leak check)
                    └──────┬──────┘
                           │
                 ┌─────────▼─────────┐
                 │    router.py      │  LLM-based intent classifier
                 │                   │  • TTL cache (avoid repeat calls)
                 │                   │  • Per-user cooldown
                 │                   │  • Keyword fallback on LLM error
                 └─────────┬─────────┘
                           │
        ┌──────────┬───────┼───────┬──────────┐
        ▼          ▼       ▼       ▼          ▼
   ┌─────────┐┌────────┐┌──────┐┌─────────┐┌───────┐
   │ Content ││Strategy││Research││Analytics││General│
   │ Pillar  ││ Pillar ││ Pillar ││ Pillar  ││       │
   └────┬────┘└───┬────┘└──┬───┘└────┬────┘└───────┘
        │         │        │         │
        └─────────┴────┬───┴─────────┘
                       │
              ┌────────▼────────┐
              │   LLM Client    │  OpenAI-compatible API
              │                 │  • Retry + exponential backoff
              │                 │  • Per-pillar max_tokens
              └─────────────────┘
```

## Core Components

### Intent Router (`router.py`)

Classifies every user message into a **pillar** and **action** using a cheap/fast LLM call with JSON output.

| Pillar | Actions |
|--------|---------|
| **Content** | caption, hooks, hashtags, cta, rewrite, ideas, calendar |
| **Strategy** | plan, funnel, budget, timeline, launch, audit |
| **Research** | trends, competitors, audience, keywords, benchmarks |
| **Analytics** | report, kpis, interpret, roi, improve |
| **General** | chitchat, help, brand, unclear |

The router has two cost-saving mechanisms:
- **TTL cache** — identical messages within 5 minutes return cached results
- **Per-user cooldown** — minimum 2 seconds between LLM calls per chat

If the LLM router fails, a keyword-based fallback attempts basic classification.

### Pillar Handlers (`pillars/`)

Each pillar extends `BasePillar` and implements `handle()`. The base class provides:
- Brand context injection into system prompts
- LLM response generation with configurable `MAX_RESPONSE_TOKENS`

Token budgets per pillar:
- Content: 2,048 (captions are short)
- Strategy: 4,096 (marketing plans are long)
- Research: 3,072 (analysis reports)
- Analytics: 3,072 (reports with breakdowns)

### Security Layer (`utils/security.py`)

Two-stage guard:

```
User Input ──► input_guard() ──► Router/Pillar ──► LLM ──► output_guard() ──► User
```

**Input guard** detects:
- System prompt extraction attempts
- Role/persona hijacking
- Data exfiltration / config leaks
- Harmful content generation
- Brand context field poisoning

**Output guard** checks for system prompt leaks in LLM responses.

Repeated offenders are tracked per-chat. After 3+ injection attempts, messages are silently dropped.

### Memory (`memory/`)

| Component | Purpose |
|-----------|---------|
| `database.py` | SQLite schema, async connection via `aiosqlite` |
| `session.py` | Per-chat conversation context (sliding window of last N turns) |
| `brand_profile.py` | Persistent brand profile per chat (UPSERT) |

Sessions are automatically cleaned up every 24 hours (messages older than 7 days are purged).

### Integrations (`integrations/`)

| Service | Required | Purpose |
|---------|----------|---------|
| **LLM API** | Yes | OpenAI-compatible endpoint for all generation |
| **Notion** | No | Content calendar + campaign tracker read/write |
| **Tavily** | No | Primary web search provider |
| **DuckDuckGo** | No (fallback) | Free web search when Tavily is not configured |

All integrations fail gracefully — a missing API key means that feature is simply disabled, not that the bot crashes.

## Data Flow Example

User sends: *"Buatkan caption Instagram untuk skincare launch"*

1. **bot.py** — sanitizes input, runs `input_guard()` (safe), shows typing indicator
2. **router.py** — LLM classifies → `{pillar: "content", action: "caption", confidence: 0.95}`
3. **content.py** — builds prompt with brand context + user message, calls LLM with `max_tokens=2048`
4. **LLM** — generates caption with hashtags and CTA
5. **bot.py** — runs `output_guard()` (safe), saves to session, splits if >4096 chars, sends reply

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Bot framework | `python-telegram-bot` v21+ (async) |
| LLM client | `openai` SDK (async, any OpenAI-compatible endpoint) |
| Database | `aiosqlite` (SQLite, zero-config) |
| Search | `tavily-python` / `duckduckgo-search` |
| Config | `pydantic-settings` (`.env` file) |
| Caching | `cachetools` (TTL cache for router + rate limits) |
| Testing | `pytest` + `pytest-asyncio` |

## Testing Strategy

- **240 tests** covering all modules
- All external APIs (LLM, Notion, Search) are mocked — no real calls in tests
- Security tests verify injection detection and blocking
- Router tests cover cache, cooldown, fallback, and throttle feedback
- LLM client tests verify jittered backoff, streaming, stale detection, and error handling
- Session tests verify atomic transactions and cleanup
- Feedback tests cover 👍/👎/🔄 buttons, response store, and regenerate flow

## Project Structure

```
digital_mate/
├── __init__.py              # Version
├── __main__.py              # Entry point, CLI args, graceful shutdown
├── config.py                # Pydantic Settings from .env
├── bot.py                   # Telegram handlers, security guards
├── router.py                # Intent classification (LLM + fallback)
├── llm/
│   ├── client.py            # Async OpenAI-compatible client
│   └── prompts.py           # System prompts per pillar
├── pillars/
│   ├── base.py              # Abstract base with shared LLM call
│   ├── content.py           # Captions, hooks, CTAs, ideas
│   ├── strategy.py          # Plans, funnels, budgets
│   ├── research.py          # Trends, competitors, audience
│   └── analytics.py         # Reports, KPIs, insights
├── integrations/
│   ├── notion_client.py     # Content calendar + campaign tracker
│   └── search.py            # Tavily + DuckDuckGo fallback
├── memory/
│   ├── database.py          # SQLite schema + async connection
│   ├── session.py           # Per-chat context + auto-cleanup
│   └── brand_profile.py     # Persistent brand profiles
└── utils/
    ├── formatting.py        # Telegram markdown helpers
    ├── security.py          # Input/output guards + rate limiting
    ├── validators.py        # Input validation
    └── keyboards.py          # Inline feedback keyboards (👍/👎/🔄)
```

## Current Capabilities & Limitations

### What Digital Mate can do today (AI Assistant level)

- **Intent routing** — classify user messages into 4 marketing pillars + general
- **Single-turn generation** — one LLM call per user message, streaming to user
- **Brand personalization** — brand profile injected into prompts
- **Session memory** — sliding window of recent conversation per chat
- **Tool integration** — Notion (read/write), web search (DuckDuckGo/Tavily)
- **Autonomous scheduling** — auto-calendar generator runs on a loop
- **Feedback loop** — 👍/👎/🔄 buttons stored in DB for future training
- **Security** — input/output guards, rate limiting, injection detection

### What Digital Mate cannot do yet (gap to Agentic)

- **Goal decomposition** — cannot break "launch a product" into sub-tasks
- **Tool chaining** — cannot use search results as input to content generation in one turn
- **Self-reflection** — cannot evaluate its own output and iterate without user prompt
- **Proactive actions** — cannot initiate conversations or notifications
- **Long-term memory** — no cross-session key facts (only brand profile + session window)
- **Multi-modal input** — cannot accept images, screenshots, or files

---

## Agentic Roadmap

The roadmap from AI Assistant to Agentic AI is divided into 4 phases. Each phase builds on the previous one and is independently deployable.

### Phase 1: Tool Chaining & Multi-Step Workflows

**Goal:** Enable the bot to use multiple tools in sequence within a single user request.

**Key capability:** Output from Tool A becomes input to Tool B — without user intervention.

```
User: "Buat caption berdasarkan tren skincare terbaru"

Current:  Router → Content Pillar → LLM → "Here's a generic caption"
Phase 1:  Router → Research Pillar (search) → Content Pillar (uses research) → LLM → "Caption based on real trends"
```

**Components to build:**

| Component | Description |
|-----------|-------------|
| `agent/orchestrator.py` | Receives classified intent, decides if multi-step is needed, chains pillars |
| `agent/workflow.py` | Workflow definitions — ordered sequences of pillar calls with data passing |
| Pillar `handle()` returns structured data | Not just text — return `{text, metadata, sources}` so downstream pillars can use it |

**Example workflows:**

1. **Research → Content:** Search trends → generate caption referencing found trends
2. **Research → Strategy:** Competitor analysis → marketing plan addressing gaps
3. **Analytics → Strategy:** Interpret metrics → improvement recommendations
4. **Strategy → Content:** Marketing plan → content calendar from the plan

**Implementation approach:**

- Add a `WorkflowEngine` that accepts a workflow definition (list of steps)
- Each step specifies: pillar, action, input mapping (from previous step's output)
- The engine executes steps sequentially, passing data between them
- The router can detect when a message needs multi-step (e.g., "based on trends" → trigger research→content)
- Progress is streamed to user: "🔍 Searching trends... → ✍️ Writing caption..."

**Estimated effort:** 2-3 implementation sessions

---

### Phase 2: Goal Decomposition & Planning

**Goal:** Bot can break complex requests into a plan, execute it step by step, and report results.

**Key capability:** User gives a high-level goal → bot creates a plan → executes → delivers.

```
User: "Bantu launching produk skincare baru"

Bot internal plan:
  1. Research tren skincare terbaru        → Research pillar + search
  2. Analisis 3 kompetitor utama           → Research pillar + search
  3. Buat positioning & strategy           → Strategy pillar
  4. Generate content calendar (2 minggu)  → Content pillar + Notion
  5. Draft 5 caption IG/TikTok             → Content pillar
  6. Buat metrics tracker                  → Analytics pillar + Notion
  → Deliver: summary + links to Notion + sample captions
```

**Components to build:**

| Component | Description |
|-----------|-------------|
| `agent/planner.py` | LLM-powered planner — takes user goal, outputs ordered step list |
| `agent/executor.py` | Executes plan steps, handles failures, retries, and re-planning |
| `agent/plan_store.py` | Persist active plans to SQLite (resume after bot restart) |
| `/plan` command | Show current plan progress, allow cancel |

**Planner prompt structure:**

```
Given a user goal, break it into 2-7 concrete steps.
Each step must specify:
  - pillar: which marketing pillar to use
  - action: specific action within that pillar
  - input_from: which previous step's output to use (or "user_request")
  - description: what this step accomplishes

Output as JSON array.
```

**Progress UX in Telegram:**

```
🚀 Launch Plan: "Launching produk skincare baru"

✅ Step 1/6: Research tren skincare          [done]
✅ Step 2/6: Analisis kompetitor              [done]  
⏳ Step 3/6: Buat positioning strategy        [running...]
⬜ Step 4/6: Generate content calendar
⬜ Step 5/6: Draft 5 captions
⬜ Step 6/6: Setup metrics tracker

[Cancel] [View Details]
```

**Estimated effort:** 3-4 implementation sessions

---

### Phase 3: Self-Reflection & Iterative Refinement

**Goal:** Bot can evaluate its own output quality and iterate before showing the user.

**Key capability:** Generate → self-evaluate → refine → deliver (internal loop).

```
User: "Buat caption IG untuk skincare launch"

Bot internal:
  Draft 1: "Skincare baru! Beli sekarang! #skincare #beauty"
  Self-eval: "Too generic, no hook, weak CTA, no brand voice. Score: 3/10"
  Draft 2: "Glow up kamu dimulai dari sini ✨ [Brand] skincare series..."
  Self-eval: "Better hook, clear CTA, matches brand tone. Score: 8/10"
  → Deliver Draft 2 to user
```

**Components to build:**

| Component | Description |
|-----------|-------------|
| `agent/critic.py` | LLM-powered critic — evaluates output on defined criteria |
| `agent/refiner.py` | Takes critique feedback, regenerates improved output |
| Quality rubrics per pillar | Content: hook strength, CTA clarity, brand voice match. Strategy: completeness, feasibility. Research: source quality, relevance. |
| `MAX_ITERATIONS` config | Prevent infinite loops (default: 2 refinement rounds) |

**Critic prompt structure:**

```
You are a marketing content critic. Evaluate this output on:
  1. Hook strength (1-10)
  2. Brand voice match (1-10)
  3. CTA clarity (1-10)
  4. Overall quality (1-10)

If any score < 7, provide specific improvement suggestions.
Output as JSON: {scores: {..., suggestions: "...", pass: bool}
```

**When to trigger self-reflection:**

- Always for Strategy pillar (high stakes, long output)
- Always for Content pillar (quality-sensitive)
- Optional for Research (if sources < 3, retry with broader query)
- Skip for Analytics (factual, less subjective)
- Skip for General/chitchat (low stakes)

**Estimated effort:** 2 implementation sessions

---

### Phase 4: Proactive Intelligence & Long-Term Memory

**Goal:** Bot can initiate actions based on triggers, and remember key facts across sessions.

**Key capability:** Bot proactively suggests, reminds, and learns — not just responds.

**4A: Long-Term Memory (cross-session key facts)**

| Component | Description |
|-----------|-------------|
| `memory/key_facts.py` | Store extracted facts: "user focuses on IG Reels", "budget is small", "F&B industry" |
| Fact extraction | After each conversation, LLM extracts 0-3 key facts → stored with chat_id |
| Fact injection | Key facts injected into system prompts on future sessions |
| `/forget` command | Let user clear stored facts |

**4B: Proactive Triggers**

| Trigger | Action |
|---------|--------|
| Weekly trend check | Auto-search trends in user's industry → "🔥 Trending this week: [X]. Want a caption?" |
| Content calendar reminder | "📅 You haven't posted in 3 days. Want me to draft something?" |
| Campaign performance alert | "📊 Your campaign has been running for 7 days. Want a performance summary?" |
| Competitor monitoring | "👀 [Competitor] just launched a new product. Want me to analyze?" |

**4C: Scheduled autonomous workflows**

```
Every Monday 8 AM:
  1. Search trends in user's industry
  2. Generate 5 content ideas based on trends + brand profile
  3. Create Notion calendar entries
  4. Send Telegram message: "🌅 5 content ideas for this week based on trending topics"
```

**Estimated effort:** 3-4 implementation sessions

---

### Phase Summary

| Phase | Capability | Key Deliverable | Effort |
|-------|-----------|-----------------|--------|
| **1** | Tool Chaining | `orchestrator.py` + workflow engine | 2-3 sessions |
| **2** | Goal Decomposition | `planner.py` + `executor.py` + plan persistence | 3-4 sessions |
| **3** | Self-Reflection | `critic.py` + `refiner.py` + quality rubrics | 2 sessions |
| **4** | Proactive Intelligence | `key_facts.py` + proactive triggers + scheduled workflows | 3-4 sessions |
| | | **Total** | **10-13 sessions** |

### Pre-Requisites (before starting Phase 1)

These are the existing Priority items that should be completed first:

- [ ] **Priority 2: Enriched brand profile** — add platform, budget_range, business_stage (enables better workflow decisions)
- [ ] **Priority 3: Long-term memory** — overlaps with Phase 4A, but basic version needed earlier for workflow context
- [ ] **Priority 4: Image/media input** — vision capability for analytics screenshots, competitor ads

### Architecture Evolution

```
Current (AI Assistant):
┌──────────┐     ┌────────┐     ┌─────────┐
│  Router  │────▶│ Pillar │────▶│   LLM   │
└──────────┘     └────────┘     └─────────┘

Phase 1 (Tool Chaining):
┌──────────┐     ┌──────────────┐     ┌────────┐     ┌─────────┐
│  Router  │────▶│ Orchestrator │────▶│ Pillar │────▶│   LLM   │
└──────────┘     │  + Workflow  │     └────────┘     └─────────┘
                 └──────┬───────┘          │
                        │                  ▼
                        │           ┌─────────┐
                        └──────────▶│  Tools  │ (search, Notion)
                                    └─────────┘

Phase 2 (Goal Decomposition):
┌──────────┐     ┌──────────┐     ┌──────────────┐     ┌────────┐
│  Router  │────▶│ Planner  │────▶│  Executor    │────▶│ Pillar │
└──────────┘     │ (LLM)    │     │  + Plan Store│     └────────┘
                 └──────────┘     └──────────────┘

Phase 3 (Self-Reflection):
┌────────┐     ┌────────┐     ┌────────┐     ┌────────┐
│ Pillar │────▶│  LLM   │────▶│ Critic │────▶│Refiner │
└────────┘     └────────┘     └────┬───┘     └───┬────┘
                                  │ pass?        │
                                  ▼ no           │ yes
                              back to LLM ◀──────┘
                              
Phase 4 (Proactive):
┌─────────────┐     ┌────────────┐     ┌────────────┐
│  Scheduler  │────▶│  Trigger   │────▶│  Workflow  │
│  (cron)     │     │  Engine    │     │  Engine    │
└─────────────┘     └────────────┘     └────────────┘
       │
       ▼
┌─────────────┐
│ Key Facts   │ ◀── extracted from every conversation
│ (SQLite)    │ ──▶ injected into future prompts
└─────────────┘
```
