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

- **172 tests** covering all modules
- All external APIs (LLM, Notion, Search) are mocked — no real calls in tests
- Security tests verify injection detection and blocking
- Router tests cover cache, cooldown, fallback, and throttle feedback
- LLM client tests verify retry logic, exponential backoff, and error handling
- Session tests verify atomic transactions and cleanup

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
    └── validators.py        # Input validation
```
