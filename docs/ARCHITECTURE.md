# Architecture

Digital Mate is a Telegram bot that acts as an AI-powered digital marketing assistant. It classifies user intent into one of four marketing pillars, dispatches to a specialized handler through an orchestrator layer, and returns structured, actionable responses. The bot supports multi-step workflows, goal decomposition with planning, self-reflection for output quality, proactive triggers, and cross-session long-term memory.

## Design Principles

- **Pillar-based routing** — A lightweight LLM call classifies messages before the "real" work happens. This keeps responses focused and lets each pillar have its own prompt, output format, and token budget.
- **Orchestrator dispatch** — The router classifies intent; the orchestrator decides *how* to execute it: single pillar call, multi-step workflow, or decomposed plan.
- **Graceful degradation** — Every external integration (Notion, Tavily, web search, vision) is optional. The bot works with just an LLM API key; everything else enhances the experience.
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
                 │                   │  • LLM routing classifier
                 └─────────┬─────────┘
                           │
                 ┌─────────▼─────────┐
                 │  orchestrator.py  │  Central dispatch
                 │                   │  • Route: workflow | plan | single
                 │                   │  • Delegates to WorkflowEngine,
                 │                   │    Planner+Executor, or direct pillar
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
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │  Reflection     │  (Content + Strategy pillars)
              │  Critic+Refiner │  • Quality scoring (1-10)
              │                 │  • Auto-iteration (max 2 rounds)
              └─────────────────┘
```

## Core Components

### Intent Router (`router.py`)

Classifies every user message into a **pillar** and **action** using an LLM-based routing classifier with JSON output.

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

The LLM routing classifier replaces the earlier keyword-matching fallback for primary classification.

### Agent Orchestrator (`agent/orchestrator.py`)

Central dispatch layer that receives the classified intent and decides the execution path:

| Condition | Execution Path |
|-----------|---------------|
| Multi-step detected (e.g., "based on trends") | Workflow Engine — chains pillars with data passing |
| Complex goal (e.g., "launch a product") | Planner → Executor — decomposes into 2–7 steps |
| Single request | Direct pillar call |

The orchestrator also handles:
- Reflection integration — automatically runs critic+refiner on Content/Strategy output
- Proactive trigger checks — evaluates if any scheduled triggers should fire
- Plan auto-resume — restarts any incomplete plans from the previous session

### Workflow Engine (`agent/workflow.py`)

Executes ordered sequences of pillar calls with data passing between steps.

**Built-in workflows:**

1. **Research → Content** — Search trends → generate caption referencing found trends
2. **Research → Strategy** — Competitor analysis → marketing plan addressing gaps
3. **Analytics → Strategy** — Interpret metrics → improvement recommendations
4. **Strategy → Content** — Marketing plan → content calendar from the plan

Each workflow step specifies: pillar, action, input mapping (from previous step's output). Progress is streamed to the user: "🔍 Searching trends... → ✍️ Writing caption..."

### Planner + Executor (`agent/planner.py`, `agent/executor.py`)

Breaks complex user goals into concrete, executable plans.

**Planner** — LLM-powered, takes a user goal and outputs an ordered list of 2–7 steps. Each step specifies:
- `pillar` — which marketing pillar to use
- `action` — specific action within that pillar
- `input_from` — which previous step's output to use (or `"user_request"`)
- `description` — what this step accomplishes

**Executor** — Runs plan steps sequentially, passing data between them. Handles:
- Step failure recovery — retries or skips with user notification
- Progress updates — streamed to Telegram as each step completes
- Plan cancellation — via `/cancelplan` command

### Plan Persistence (`agent/plan_store.py`)

Stores active plans in SQLite so they survive bot restarts. On startup, the orchestrator checks for any incomplete plans and resumes execution automatically.

### Self-Reflection (`agent/critic.py`, `agent/refiner.py`, `agent/reflection.py`)

Quality gate for Content and Strategy pillar output.

**Critic** — Evaluates output on defined criteria:
- Hook strength (1-10)
- Brand voice match (1-10)
- CTA clarity (1-10)
- Overall quality (1-10)

If any score < 7, the critic provides specific improvement suggestions.

**Refiner** — Takes critique feedback and regenerates improved output.

**Reflection Engine** — Orchestrates the critic+refiner loop (max 2 iterations). When output is improved, the user sees a `✨ Auto-optimized` indicator.

| Pillar | Reflection | Reason |
|--------|-----------|--------|
| Content | Always | Quality-sensitive, hook/CTA matters |
| Strategy | Always | High stakes, long output |
| Research | Conditional | Only if sources < 3 |
| Analytics | Skip | Factual, less subjective |
| General | Skip | Low stakes |

### Proactive Triggers (`agent/triggers.py`, `agent/scheduler.py`)

**Triggers** — Define conditions that should prompt the bot to reach out:

| Trigger | Action |
|---------|--------|
| Weekly trend check | Auto-search trends in user's industry |
| Content calendar reminder | Nudge when user hasn't posted recently |
| Campaign performance alert | Flag when campaign is ready for review |
| Competitor monitoring | Alert on competitor activity |

**Scheduler** — Cron-like runner that evaluates triggers on a schedule and executes the appropriate workflow when a trigger condition is met. The `/digest` command triggers an on-demand trend digest.

### Long-Term Memory (`memory/key_facts.py`)

Cross-session key fact storage that persists important user context:

- **Extraction** — Every 10 messages, an LLM call extracts 0–3 key facts from the conversation
- **Storage** — Facts stored in SQLite with `chat_id` association
- **Injection** — Stored facts injected into system prompts on future sessions
- **Clearing** — `/forget` command lets the user clear all stored facts

Example facts: "user focuses on IG Reels", "budget is small", "F&B industry in Jakarta"

### Feedback System (`memory/response_store.py`, `utils/keyboards.py`)

Inline feedback buttons (👍/👎/🔄) attached to every bot response:

- **👍/👎** — Stored in `response_store` for future analysis and training
- **🔄** — Regenerates the response (triggers a new LLM call with the same context)
- Feedback data is stored per-response with metadata for future fine-tuning

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
| `database.py` | SQLite schema (v7), async connection via `aiosqlite` |
| `session.py` | Per-chat conversation context (sliding window of last N turns) |
| `brand_profile.py` | Persistent brand profile per chat (UPSERT) |
| `key_facts.py` | Long-term cross-session key facts |
| `response_store.py` | Feedback storage (👍/👎/🔄) |
| `autocalendar.py` | Auto content calendar generator |

Sessions are automatically cleaned up every 24 hours (messages older than 7 days are purged).

### Integrations (`integrations/`)

| Service | Required | Purpose |
|---------|----------|---------|
| **LLM API** | Yes | OpenAI-compatible endpoint for all generation |
| **Notion** | No | Content calendar + campaign tracker read/write |
| **Tavily** | No | Primary web search provider |
| **DuckDuckGo** | No (fallback) | Free web search when Tavily is not configured |
| **Vision** | No | Image analysis for screenshots, ads, dashboards |

All integrations fail gracefully — a missing API key means that feature is simply disabled, not that the bot crashes.

## Data Flow Examples

### Single-Turn Request

User sends: *"Buatkan caption Instagram untuk skincare launch"*

1. **bot.py** — sanitizes input, runs `input_guard()` (safe), shows typing indicator
2. **router.py** — LLM classifies → `{pillar: "content", action: "caption", confidence: 0.95}`
3. **orchestrator.py** — single request, no multi-step detected → direct pillar call
4. **content.py** — builds prompt with brand context + user message, calls LLM with `max_tokens=2048`
5. **reflection.py** — critic evaluates output, score 8/10 → passes, no refinement needed
6. **bot.py** — runs `output_guard()` (safe), saves to session, splits if >4096 chars, sends reply

### Multi-Step Workflow

User sends: *"Buat caption berdasarkan tren skincare terbaru"*

1. **bot.py** — sanitizes input, runs `input_guard()` (safe)
2. **router.py** — LLM classifies → `{pillar: "content", action: "caption", confidence: 0.92}`
3. **orchestrator.py** — detects "berdasarkan tren" → triggers **Research → Content** workflow
4. **workflow.py** — Step 1: Research pillar searches web for skincare trends
5. **workflow.py** — Step 2: Content pillar generates caption using research results as context
6. **reflection.py** — critic evaluates output, score 7/10 → passes
7. **bot.py** — runs `output_guard()`, sends reply with progress indicators

### Goal Decomposition (Plan)

User sends: *"Bantu launching produk skincare baru"*

1. **bot.py** — sanitizes input, runs `input_guard()` (safe)
2. **router.py** — LLM classifies → `{pillar: "strategy", action: "plan", confidence: 0.88}`
3. **orchestrator.py** — detects complex goal → invokes Planner
4. **planner.py** — LLM decomposes into 6 steps:
   ```
   Step 1: Research tren skincare terbaru        → research:trends
   Step 2: Analisis 3 kompetitor utama           → research:competitors
   Step 3: Buat positioning & strategy           → strategy:plan
   Step 4: Generate content calendar (2 minggu)  → content:calendar
   Step 5: Draft 5 caption IG/TikTok             → content:caption
   Step 6: Buat metrics tracker                  → analytics:report
   ```
5. **plan_store.py** — persists plan to SQLite
6. **executor.py** — executes each step, streaming progress to user
7. **reflection.py** — runs on steps 3, 4, 5 (Content/Strategy outputs)
8. **bot.py** — delivers final summary with all outputs

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

- **510 tests** covering all modules
- All external APIs (LLM, Notion, Search) are mocked — no real calls in tests
- Security tests verify injection detection and blocking
- Router tests cover cache, cooldown, fallback, and throttle feedback
- LLM client tests verify jittered backoff, streaming, stale detection, and error handling
- Session tests verify atomic transactions and cleanup
- Feedback tests cover 👍/👎/🔄 buttons, response store, and regenerate flow
- Orchestrator tests cover workflow execution, plan decomposition, and reflection integration
- Planner tests cover goal decomposition, step sequencing, and error recovery
- Critic/refiner tests cover quality scoring, refinement loop, and iteration limits
- Trigger tests cover condition detection, scheduler execution, and `/digest` command
- Key facts tests cover extraction, injection, and `/forget` command
- Routing classifier tests cover LLM-based intent classification

## Project Structure

```
digital_mate/
├── __init__.py              # Version
├── __main__.py              # Entry point, CLI args, graceful shutdown
├── config.py                # Pydantic Settings from .env
├── bot.py                   # Telegram handlers, security guards
├── router.py                # Intent classification (LLM classifier)
├── llm/
│   ├── client.py            # Async OpenAI-compatible client
│   └── prompts.py           # System prompts per pillar
├── agent/
│   ├── orchestrator.py      # Central dispatch: workflow | plan | single
│   ├── workflow.py          # Workflow engine + 4 built-in workflows
│   ├── planner.py           # LLM goal decomposition (2-7 steps)
│   ├── executor.py          # Plan step execution + error recovery
│   ├── plan_store.py        # SQLite plan persistence (resume on restart)
│   ├── critic.py            # Output quality evaluator
│   ├── refiner.py           # Iterative output improvement
│   ├── reflection.py        # Reflection engine (critic + refiner loop)
│   ├── triggers.py          # Proactive trigger definitions + detection
│   └── scheduler.py         # Cron-like scheduled task runner
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
│   ├── database.py          # SQLite schema (v7) + async connection
│   ├── session.py           # Per-chat context + auto-cleanup
│   ├── brand_profile.py     # Persistent brand profiles
│   ├── key_facts.py         # Long-term memory (auto-extract every 10 msgs)
│   ├── response_store.py    # Feedback storage (👍/👎/🔄)
│   └── autocalendar.py      # Auto content calendar generator
├── prompts/
│   ├── router.md            # Intent classification rules
│   ├── content.md           # Content generation expertise
│   ├── strategy.md          # Strategic planning frameworks
│   ├── research.md          # Research methodology
│   ├── analytics.md         # Analytics interpretation
│   ├── planner.md           # Goal decomposition prompt
│   └── general.md           # Chitchat / help responses
└── utils/
    ├── formatting.py        # Telegram markdown helpers
    ├── security.py          # Input/output guards + rate limiting
    ├── validators.py        # Input validation
    ├── keyboards.py         # Inline feedback keyboards (👍/👎/🔄)
    └── image.py             # Vision / image processing
```

## Current Capabilities & Limitations

### What Digital Mate can do today (Agentic AI)

- **Intent routing** — LLM-based classifier routes messages into 4 marketing pillars + general
- **Single-turn generation** — one LLM call per user message, streaming to user
- **Multi-step workflows** — 4 built-in workflows (Research→Content, Research→Strategy, Analytics→Strategy, Strategy→Content)
- **Goal decomposition** — LLM planner breaks complex goals into 2–7 executable steps
- **Plan persistence** — Plans survive restarts, auto-resume on startup
- **Self-reflection** — Critic + refiner loop auto-optimizes Content/Strategy output (max 2 rounds)
- **Proactive triggers** — Trend digests, content reminders, campaign alerts via scheduler
- **Long-term memory** — Key facts extracted every 10 messages, injected into future prompts
- **Vision** — Image analysis for screenshots, ads, analytics dashboards
- **Multi-language** — EN, ID, ES, ZH, JA support
- **Brand personalization** — brand profile injected into prompts
- **Session memory** — sliding window of recent conversation per chat
- **Tool integration** — Notion (read/write), web search (DuckDuckGo/Tavily)
- **Feedback loop** — 👍/👎/🔄 buttons stored in DB for future training
- **Security** — input/output guards, rate limiting, injection detection

### Remaining limitations

- **No direct social posting** — generates content but cannot post to social platforms
- **No team collaboration** — brand profiles are per-chat, not shared across users
- **No image generation** — analyzes images but cannot generate them
- **No CRM integration** — no HubSpot, Salesforce, or similar connections

---

## Agentic Roadmap

All four agentic phases are **✅ COMPLETE**.

### ✅ Phase 1: Tool Chaining & Multi-Step Workflows — COMPLETE

**Goal:** Enable the bot to use multiple tools in sequence within a single user request.

**Delivered:**
- `agent/orchestrator.py` — receives classified intent, decides if multi-step is needed, chains pillars
- `agent/workflow.py` — workflow definitions with 4 built-in workflows
- Pillar `handle()` returns structured data — `{text, metadata, sources}` for downstream use
- Progress streaming to user during workflow execution

---

### ✅ Phase 2: Goal Decomposition & Planning — COMPLETE

**Goal:** Bot can break complex requests into a plan, execute it step by step, and report results.

**Delivered:**
- `agent/planner.py` — LLM-powered planner, takes user goal, outputs 2–7 ordered steps
- `agent/executor.py` — executes plan steps, handles failures and retries
- `agent/plan_store.py` — persists active plans to SQLite (resume after restart)
- `/plan` command — show current plan progress
- `/cancelplan` command — cancel running plan
- Plan auto-resume on bot startup

---

### ✅ Phase 3: Self-Reflection & Iterative Refinement — COMPLETE

**Goal:** Bot can evaluate its own output quality and iterate before showing the user.

**Delivered:**
- `agent/critic.py` — LLM-powered critic evaluates on hook strength, brand voice, CTA clarity, overall quality
- `agent/refiner.py` — takes critique feedback, regenerates improved output
- `agent/reflection.py` — orchestrates critic+refiner loop (max 2 iterations)
- `✨ Auto-optimized` indicator shown to user when reflection improved output
- Pillar-aware: always for Content/Strategy, conditional for Research, skip for Analytics/General

---

### ✅ Phase 4: Proactive Intelligence & Long-Term Memory — COMPLETE

**Goal:** Bot can initiate actions based on triggers, and remember key facts across sessions.

**Delivered:**
- `memory/key_facts.py` — stores extracted facts with chat_id association
- Fact extraction — LLM extracts 0–3 key facts every 10 messages
- Fact injection — key facts injected into system prompts on future sessions
- `/forget` command — clear stored facts
- `agent/triggers.py` — proactive trigger definitions (trend, content reminder, campaign alert)
- `agent/scheduler.py` — cron-like scheduled task runner
- `/digest` command — on-demand trend digest

---

### ✅ Gap Closures — COMPLETE

Three gaps identified during Phase 1–4 implementation, all resolved:

| Gap | Solution |
|-----|----------|
| Keyword-based routing was fragile | LLM-based routing classifier (replaces keyword matching) |
| Reflection was invisible to user | `✨ Auto-optimized` indicator shown when output improved |
| Plans lost on restart | Plan auto-resume on bot startup from SQLite persistence |

---

### Phase Summary

| Phase | Capability | Key Deliverable | Status |
|-------|-----------|-----------------|--------|
| **1** | Tool Chaining | `orchestrator.py` + workflow engine | ✅ Complete |
| **2** | Goal Decomposition | `planner.py` + `executor.py` + plan persistence | ✅ Complete |
| **3** | Self-Reflection | `critic.py` + `refiner.py` + reflection engine | ✅ Complete |
| **4** | Proactive Intelligence | `key_facts.py` + triggers + scheduler | ✅ Complete |
| **Gaps** | Routing, UX, Persistence | LLM classifier, auto-optimized indicator, plan resume | ✅ Complete |
