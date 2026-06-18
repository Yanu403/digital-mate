# Digital Mate — Implementation Plan

> **For Hermes:** Use coding-delegation skill pipeline to implement this plan phase-by-phase.

**Goal:** Build "Digital Mate" — a standalone Telegram bot that serves as a bilingual (EN/ID) AI Digital Marketing Assistant with 4 pillars: Content & Copywriting, Strategy & Planning, Research & Insight, Analytics & Reporting. Integrates with Notion for content calendar and campaign tracking. Showcase-quality project for GitHub.

**Architecture:** Layered modular Python project. Telegram bot (python-telegram-bot 20.x async) → Intent Router → Pillar Handlers → LLM Service + Notion Service + Search Service. SQLite for session context + brand profiles. OpenAI-compatible LLM (pluggable via .env).

**Tech Stack:** Python 3.11+, python-telegram-bot 20.x, aiosqlite, openai (SDK), notion-client, tavily-python (or duckduckgo-search fallback), pydantic, python-dotenv, rich (CLI formatting).

---

## Phase 0: Project Skeleton & Foundation

### Task 0.1: Create project directory and boilerplate files

**Objective:** Set up the repo structure with all config/meta files.

**Files:**
- Create: `/root/projects/digital-mate/.gitignore`
- Create: `/root/projects/digital-mate/.env.example`
- Create: `/root/projects/digital-mate/requirements.txt`
- Create: `/root/projects/digital-mate/LICENSE`
- Create: `/root/projects/digital-mate/pyproject.toml`

**Steps:**
1. `mkdir -p /root/projects/digital-mate && cd /root/projects/digital-mate && git init -q`
2. Write `.gitignore` (Python + .env + .venv + data/ + *.db + __pycache__)
3. Write `.env.example` with all config vars documented:
   ```
   # === LLM Configuration ===
   LLM_BASE_URL=https://api.openai.com/v1
   LLM_API_KEY=sk-...
   LLM_MODEL=gpt-4o
   LLM_ROUTER_MODEL=          # optional: cheaper model for intent routing (defaults to LLM_MODEL)

   # === Telegram ===
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF

   # === Notion (optional) ===
   NOTION_API_KEY=ntn_...
   NOTION_CONTENT_CALENDAR_DB=   # database ID for content calendar
   NOTION_CAMPAIGN_TRACKER_DB=   # database ID for campaign tracker

   # === Search (optional) ===
   TAVILY_API_KEY=tvly-...       # if empty, falls back to DuckDuckGo

   # === Bot Settings ===
   BOT_LANGUAGE=bilingual        # bilingual | en | id
   BOT_NAME=Digital Mate
   MAX_CONVERSATION_TURNS=10     # session context window
   ```
4. Write `requirements.txt` with pinned ranges
5. Write MIT LICENSE (Yanu403)
6. Write minimal `pyproject.toml`

**Verify:** `ls -la` shows all files, `git status` clean after `git add -A && git commit -m "chore: project skeleton"`

---

### Task 0.2: Create directory structure

**Objective:** Scaffold the full module layout.

**Files — Create all:**
```
digital_mate/
├── __init__.py
├── __main__.py              # entry point: python -m digital_mate
├── config.py                # pydantic Settings from .env
├── bot.py                   # telegram bot setup, handlers registration
├── router.py                # intent classification → pillar dispatch
├── llm/
│   ├── __init__.py
│   ├── client.py            # async OpenAI-compatible client wrapper
│   └── prompts.py           # system prompts per pillar + router prompt
├── pillars/
│   ├── __init__.py
│   ├── base.py              # BasePillar abstract class
│   ├── content.py           # Pillar 1: Content & Copywriting
│   ├── strategy.py          # Pillar 2: Strategy & Planning
│   ├── research.py          # Pillar 3: Research & Insight
│   └── analytics.py         # Pillar 4: Analytics & Reporting
├── integrations/
│   ├── __init__.py
│   ├── notion_client.py     # Notion API wrapper (content calendar + campaign tracker)
│   └── search.py            # Web search (Tavily primary, DDG fallback)
├── memory/
│   ├── __init__.py
│   ├── database.py          # SQLite schema + migrations via aiosqlite
│   ├── session.py           # Per-chat session context (recent N turns)
│   └── brand_profile.py     # Persistent brand profile per chat
├── utils/
│   ├── __init__.py
│   ├── formatting.py        # Telegram markdown formatting helpers
│   └── validators.py        # Input validation, URL checks, etc.
tests/
├── __init__.py
├── conftest.py              # fixtures: mock LLM, mock Notion, test DB
├── test_router.py
├── test_pillars/
│   ├── test_content.py
│   ├── test_strategy.py
│   ├── test_research.py
│   └── test_analytics.py
├── test_memory.py
└── test_integrations.py
```

**Verify:** `find digital_mate tests -type f | wc -l` returns expected count, all `__init__.py` exist.

---

## Phase 1: Core Infrastructure

### Task 1.1: Config module

**Objective:** Pydantic Settings class that reads `.env` with validation.

**File:** `digital_mate/config.py`

**Details:**
- Use `pydantic-settings` BaseSettings
- All fields from `.env.example` as typed attributes
- Validators: LLM_BASE_URL must be valid URL, TELEGRAM_BOT_TOKEN must match pattern
- `BOT_LANGUAGE` enum: `bilingual | en | id`
- Optional fields (Notion, Tavily) default to None
- Singleton pattern: `get_settings()` cached

**Test:** `tests/test_config.py` — valid config loads, missing required field raises, optional fields default None.

---

### Task 1.2: LLM Client

**Objective:** Async wrapper around any OpenAI-compatible API.

**File:** `digital_mate/llm/client.py`

**Details:**
- Class `LLMClient` with `__init__(base_url, api_key, model)`
- Method `async chat(messages: list[dict], temperature=0.7, max_tokens=2048) -> str`
- Method `async chat_structured(messages, response_format) -> dict` (for router JSON output)
- Retry with exponential backoff (3 attempts)
- Graceful error messages (not raw tracebacks)
- Token counting estimate (rough, for context management)

**Test:** Mock httpx responses, verify retry, verify error handling.

---

### Task 1.3: SQLite Database & Session Memory

**Objective:** aiosqlite database with session context and brand profiles.

**Files:**
- `digital_mate/memory/database.py` — schema, init, migrations
- `digital_mate/memory/session.py` — session CRUD
- `digital_mate/memory/brand_profile.py` — brand profile CRUD

**Schema:**
```sql
-- sessions: per-chat conversation context
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL,        -- 'user' | 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sessions_chat ON sessions(chat_id, created_at);

-- brand_profiles: persistent per-chat brand config
CREATE TABLE brand_profiles (
    chat_id INTEGER PRIMARY KEY,
    brand_name TEXT,
    industry TEXT,
    target_audience TEXT,
    tone_of_voice TEXT,        -- e.g. "professional yet friendly"
    key_products TEXT,          -- JSON array
    hashtags TEXT,              -- JSON array of preferred hashtags
    competitors TEXT,           -- JSON array
    extra_context TEXT,         -- free-form notes
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Session behavior:**
- `get_context(chat_id, limit=MAX_CONVERSATION_TURNS)` → last N messages
- `add_message(chat_id, role, content)` → append
- `clear_session(chat_id)` → wipe context
- Auto-prune: messages older than 24h cleaned on startup

**Brand profile behavior:**
- `get_profile(chat_id)` → BrandProfile or None
- `set_profile(chat_id, **fields)` → upsert
- Profile injected into system prompt for every LLM call

**Test:** In-memory SQLite, verify CRUD, verify context window limit.

---

### Task 1.4: System Prompts

**Objective:** Define all prompts — router, per-pillar system prompts, brand injection template.

**File:** `digital_mate/llm/prompts.py`

**Details:**
- `ROUTER_PROMPT` — classifies user intent into one of: `content`, `strategy`, `research`, `analytics`, `general`, `brand_setup`
- `PILLAR_PROMPTS` dict with per-pillar system prompt:
  - `content`: expert copywriter, outputs formatted caption/newsletter/hooks
  - `strategy`: marketing strategist, outputs plans/calendars/funnels
  - `research`: market researcher, uses search results as context
  - `analytics`: data analyst, interprets metrics and generates insights
- `BRAND_CONTEXT_TEMPLATE` — template string that injects brand profile into any pillar prompt
- `GENERAL_PROMPT` — friendly fallback for chit-chat / unclear intent
- All prompts bilingual-aware: "Respond in the same language the user writes in. Default to English if unclear."
- Output format rules embedded: captions always include hashtags + CTA, strategies include timeline, etc.

**Test:** Verify all prompt constants are non-empty, verify brand injection template renders correctly with sample data.

---

## Phase 2: Intent Router

### Task 2.1: Router implementation

**Objective:** Classify user messages into pillar + action.

**File:** `digital_mate/router.py`

**Details:**
- Class `IntentRouter`
- Method `async classify(message: str, context: list[dict]) -> RouterResult`
- `RouterResult`: `pillar` (enum), `action` (str), `confidence` (float), `params` (dict)
- Uses `LLM_ROUTER_MODEL` if set (cheaper model), else falls back to `LLM_MODEL`
- Router prompt asks LLM to return JSON: `{"pillar": "content", "action": "write_caption", "confidence": 0.9}`
- Confidence threshold: < 0.5 → ask clarifying question
- Special intents: `/start`, `/help`, `/brand`, `/calendar`, `/report` → direct dispatch (no LLM routing)

**Test:** Mock LLM responses, verify routing for sample messages:
- "Buatkan caption Instagram untuk produk skincare" → content, write_caption
- "Buat content calendar minggu ini" → strategy, content_calendar
- "Riset tren TikTok 2025" → research, trend_research
- "Rangkum performa campaign bulan lalu" → analytics, campaign_summary

---

## Phase 3: Pillar Implementations

### Task 3.1: Base Pillar

**Objective:** Abstract base class all pillars inherit from.

**File:** `digital_mate/pillars/base.py`

**Details:**
- Abstract class `BasePillar`
- Constructor receives: `llm_client`, `notion_client` (optional), `search_client` (optional)
- Abstract method `async handle(message, context, brand_profile, action) -> str`
- Shared method `build_messages(system_prompt, context, brand_profile, user_message) -> list[dict]`
- Shared method `format_response(raw_output) -> str` (Telegram markdown cleanup)

---

### Task 3.2: Content & Copywriting Pillar

**Objective:** Generate captions, hooks, newsletters, content ideas.

**File:** `digital_mate/pillars/content.py`

**Actions:**
- `write_caption` — IG/TikTok/X caption with hashtags + CTA
- `write_newsletter` — email newsletter draft
- `generate_hooks` — 5-10 hook variations for a topic
- `content_ideas` — brainstorm content ideas for a topic/product
- `rewrite` — improve/adapt existing copy

**Output rules (embedded in prompt):**
- Captions: max 2200 chars, 3-5 hashtags, clear CTA at end
- Hooks: numbered list, each ≤15 words
- Newsletter: subject line + preview text + body sections

---

### Task 3.3: Strategy & Planning Pillar

**Objective:** Campaign planning, content calendars, funnel breakdowns.

**File:** `digital_mate/pillars/strategy.py`

**Actions:**
- `content_calendar` — weekly/monthly content calendar (saves to Notion if connected)
- `campaign_plan` — full campaign brief (objective, audience, channels, timeline, KPIs)
- `funnel_breakdown` — awareness → consideration → conversion strategy
- `channel_strategy` — per-platform posting strategy

**Notion integration:**
- If `NOTION_CONTENT_CALENDAR_DB` configured → auto-save calendar entries
- Calendar entry schema: Date, Channel (multi-select), Content Type, Copy Draft, Status, Assets Needed

---

### Task 3.4: Research & Insight Pillar

**Objective:** Real-time trend research, competitor analysis, keyword research, audience insights.

**File:** `digital_mate/pillars/research.py`

**Actions:**
- `trend_research` — search web for current trends in a topic/industry
- `competitor_analysis` — analyze competitor's online presence
- `keyword_research` — suggest keywords/hashtags for a topic
- `audience_research` — audience persona development

**Search integration:**
- Uses `SearchClient` (Tavily primary, DDG fallback)
- Formats search results as context for LLM synthesis
- Always cites sources with URLs

---

### Task 3.5: Analytics & Reporting Pillar

**Objective:** Summarize campaign performance, generate report templates, extract insights.

**File:** `digital_mate/pillars/analytics.py`

**Actions:**
- `campaign_summary` — summarize performance data (user provides metrics)
- `weekly_report` — generate formatted weekly report template
- `monthly_report` — generate formatted monthly report with Notion data
- `extract_insights` — analyze metrics and provide actionable recommendations
- `compare_campaigns` — compare two campaigns side by side

**Notion integration:**
- If `NOTION_CAMPAIGN_TRACKER_DB` configured → pull campaign data for reports
- Campaign tracker schema: Campaign Name, Start Date, End Date, Channel, Budget, Impressions, Clicks, Conversions, Revenue, Status, Notes

---

## Phase 4: Integrations

### Task 4.1: Notion Client

**Objective:** Async wrapper for Notion API — content calendar + campaign tracker CRUD.

**File:** `digital_mate/integrations/notion_client.py`

**Details:**
- Class `NotionClient` with optional init (graceful when NOTION_API_KEY not set)
- Content Calendar methods:
  - `create_calendar_entry(date, channel, content_type, copy_draft, status)`
  - `get_calendar_entries(start_date, end_date)`
  - `update_entry_status(page_id, status)`
- Campaign Tracker methods:
  - `create_campaign(name, channel, budget, start_date, end_date)`
  - `get_campaigns(status_filter=None)`
  - `update_campaign_metrics(page_id, impressions, clicks, conversions, revenue)`
  - `get_campaign_summary(campaign_name)` → dict of all metrics
- All methods return structured dicts, not raw Notion API responses
- Graceful degradation: if Notion not configured, methods return None with info message

**Test:** Mock Notion API responses, verify CRUD operations, verify graceful fallback.

---

### Task 4.2: Search Client

**Objective:** Web search abstraction with Tavily primary + DuckDuckGo fallback.

**File:** `digital_mate/integrations/search.py`

**Details:**
- Class `SearchClient`
- Method `async search(query, num_results=5) -> list[SearchResult]`
- `SearchResult`: title, url, snippet, content (if available)
- If TAVILY_API_KEY set → use Tavily (better quality, includes page content)
- Else → DuckDuckGo (free, snippet-only)
- Result formatting helper for LLM context injection

**Test:** Mock both backends, verify fallback behavior.

---

## Phase 5: Telegram Bot

### Task 5.1: Bot setup and handler registration

**Objective:** Telegram bot with command handlers + message handler.

**File:** `digital_mate/bot.py`

**Details:**
- Uses `python-telegram-bot` 20.x async (Application builder pattern)
- Commands:
  - `/start` — welcome message + quick guide
  - `/help` — list capabilities per pillar
  - `/brand` — interactive brand profile setup (conversational)
  - `/brand_view` — show current brand profile
  - `/calendar` — show this week's content calendar (from Notion)
  - `/report` — generate quick weekly report
  - `/clear` — clear conversation context
  - `/language [en|id|bilingual]` — set response language
- Message handler: routes through IntentRouter → Pillar → Response
- Error handler: user-friendly error messages, log full traceback
- Typing indicator while processing (ChatAction.TYPING)
- Long response splitting (Telegram 4096 char limit)

---

### Task 5.2: Brand Profile Setup Flow

**Objective:** Conversational flow to set up brand profile via `/brand` command.

**File:** `digital_mate/bot.py` (ConversationHandler)

**Details:**
- Uses `ConversationHandler` with states:
  1. Ask brand name
  2. Ask industry
  3. Ask target audience
  4. Ask tone of voice (with examples)
  5. Ask key products/services
  6. Ask preferred hashtags
  7. Ask competitors (optional)
  8. Confirm & save
- Can be re-run to update
- `/brand_view` shows current profile formatted nicely

---

### Task 5.3: Entry point

**Objective:** `__main__.py` that boots the bot.

**File:** `digital_mate/__main__.py`

**Details:**
- Load config → Init DB → Init services → Register handlers → Start polling
- Startup banner with bot name + configured integrations
- Graceful shutdown on SIGINT/SIGTERM
- CLI flag: `--init-db` to create/migrate database without starting bot

---

## Phase 6: Utilities & Polish

### Task 6.1: Telegram formatting helpers

**File:** `digital_mate/utils/formatting.py`

- Escape Telegram MarkdownV2 special chars
- Split long messages at paragraph boundaries
- Format tables as aligned text (Telegram has no table support)
- Format lists with emoji bullets
- Calendar view formatter (week grid)

---

### Task 6.2: Notion template databases

**Objective:** Create documentation for users to set up their own Notion databases.

**File:** `docs/notion-setup.md`

**Details:**
- Step-by-step with screenshots placeholder descriptions
- Content Calendar template properties
- Campaign Tracker template properties
- How to get database IDs
- How to create Notion integration + get API key

---

### Task 6.3: README

**File:** `README.md`

**Sections:**
- Hero: name, tagline, badges (Python, License, Stars)
- Features: 4 pillars with emoji
- Quick Start: clone → .env → pip install → run
- Commands reference table
- Configuration guide
- Notion Setup link
- Architecture overview (simple diagram in text)
- Contributing guide
- Roadmap (WhatsApp Phase 2, auto-scheduling, analytics dashboard)
- License

---

## Phase 7: Testing & Verification

### Task 7.1: Test suite

- `tests/conftest.py` — shared fixtures (mock LLM, mock Notion, temp SQLite)
- `tests/test_config.py` — config loading
- `tests/test_router.py` — intent classification
- `tests/test_pillars/` — each pillar's output format
- `tests/test_memory.py` — session + brand profile CRUD
- `tests/test_integrations.py` — Notion + Search mocks

### Task 7.2: End-to-end verification

```bash
# Fresh venv install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Tests pass
pytest tests/ -v --timeout=20

# CLI works
python -m digital_mate --help

# No Hermes references
grep -ri "hermes\|/root/.hermes" digital_mate/ tests/ | grep -v .pyc || echo "✅ clean"

# Bot starts (with valid .env)
python -m digital_mate  # Ctrl+C after "Bot started"
```

---

## Execution Strategy

**Total estimated LoC:** ~2,000-2,500
**Recommended CLI:** Claude Code (`claude -p --permission-mode acceptEdits --max-turns 80`)
**Estimated build time:** 10-20 minutes delegation + 10 minutes verification

**Delegation approach:**
1. Write TASK_BRIEF.md (comprehensive, from this plan)
2. Create skeleton (Phase 0) manually
3. Delegate Phase 1-6 as single Claude Code session
4. Verify Phase 7 manually
5. Polish README + docs
6. Push to GitHub as `Yanu403/digital-mate`

**GitHub topics:** `telegram-bot digital-marketing ai-assistant content-creation notion-integration python openai marketing-automation copywriting`
