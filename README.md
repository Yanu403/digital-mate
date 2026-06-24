<div align="center">

<img src="docs/screenshots/banner.png" alt="Digital Mate Banner" width="100%"/>

# 🤖 Digital Mate

### Stop guessing. Start marketing like you have a full team.

**An AI marketing assistant in Telegram that plans, creates, and analyzes — from captions to campaign strategies to performance reports. 510 tests. Defense-in-depth security. Zero dashboard.**

> *Chat with it like a marketing colleague. It does the rest.*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-510%20Passing-brightgreen?style=for-the-badge)](#testing)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/digitalmate_marketing_bot)

**Tech Stack:** Python 3.11+ · python-telegram-bot · OpenAI-compatible LLM · SQLite · Notion API

[Why Digital Mate?](#-why-digital-mate) · [Who is this for?](#-who-is-this-for) · [Features](#features) · [Demo](#demo) · [Quick Start](#quick-start) · [Architecture](#architecture) · [Contributing](#-contributing) · [Roadmap](#roadmap)

</div>

---

## 🎯 What is Digital Mate?

Digital Mate is a **production-grade AI marketing assistant** built for Telegram. It understands natural language marketing requests, routes them to specialized AI pipelines, and delivers actionable outputs — captions, strategies, research reports, and analytics.

**No dashboard. No learning curve. Just chat.**

---

## 🔥 Why Digital Mate?

| Feature | ChatGPT | Generic AI Bots | **Digital Mate** |
|---------|---------|-----------------|------------------|
| Marketing-specific prompts | ❌ Generic | ⚠️ Basic | ✅ 4 specialized pillars |
| Multi-step workflows | ❌ Single turn | ❌ | ✅ Automatic tool chaining |
| Self-reflection & auto-optimization | ❌ | ❌ | ✅ Quality scoring + refinement |
| Proactive reminders | ❌ | ❌ | ✅ Weekly digests + nudges |
| Security hardening | ⚠️ Basic | ❌ | ✅ 510 tests, 3 guard layers |
| Brand voice memory | ❌ | ⚠️ Limited | ✅ Per-chat brand profiles |
| Open source | ❌ | ❌ | ✅ MIT License |
| Telegram native | ❌ | ⚠️ Some | ✅ Built for Telegram |

Most AI tools give you a blank chat box. Digital Mate gives you a **marketing team** — with memory, workflows, quality control, and security built in.

---

## 👋 Who is this for?

- **🧑‍💻 Solo founders** — *"I need marketing content but can't afford an agency."*
- **🏪 Small business owners** — *"I know I should post on social media but don't know what."*
- **🧑‍🎨 Marketing freelancers** — *"I need to scale my output without sacrificing quality."*
- **🚀 Startup teams** — *"We need a marketing strategy but our budget is $0."*

If you think in marketing terms but don't have a team to execute — **Digital Mate is your team.**

---

```
You: Write me 3 Instagram captions for a new coffee shop in Jakarta
Mate: 🚀 3 Caption Variations — Coffee Shop Launch
      ☕ Variation 1: Warm & Inviting — "first sip hits different..."
      🔥 Variation 2: Playful & Bold — "POV: You just found your new spot..."
      🤍 Variation 3: Minimal & Aesthetic — "Good coffee. Warm light..."
```

---

## ✨ Features

### 🖊️ Content & Copywriting
- **Multi-platform captions** — Instagram, TikTok, Twitter/X, LinkedIn, Facebook
- **Hook generator** — 8+ psychological hook frameworks (curiosity gap, pain point, bold claim...)
- **Content calendar** — Weekly content plans with channel-specific scheduling
- **Newsletter & email** — Subject lines, body copy, CTA optimization
- **Hashtag strategy** — Mix of reach, niche, and branded hashtags

### 📋 Strategy & Planning
- **Campaign blueprints** — Full funnel breakdown (awareness → conversion)
- **Launch playbooks** — Phase-by-phase launch strategies with timelines
- **Marketing audits** — Structured checklist-based analysis
- **Budget allocation** — Channel mix recommendations by goal

### 🔎 Research & Insight
- **Competitor analysis** — Real-time web research with structured reports
- **Audience personas** — Data-driven persona builder with demographics + psychographics
- **Keyword research** — Volume, difficulty, intent mapping
- **Trend monitoring** — Industry trend identification via live web search

### 📊 Analytics & Reporting
- **Performance reports** — Input raw metrics, get executive summaries
- **KPI frameworks** — Platform-specific benchmark comparisons
- **What→Why→Do** — Structured interpretation methodology
- **Action prioritization** — Impact vs. effort matrix for next steps

### 🔄 Tool Chaining — Multi-Step Workflows
- **Research → Content** — Search trends, then generate captions referencing real data
- **Research → Strategy** — Competitor analysis feeds into a marketing plan
- **Analytics → Strategy** — Interpret metrics, then recommend improvements
- **Strategy → Content** — Marketing plan drives a content calendar
- Progress streamed to user: "🔍 Searching trends... → ✍️ Writing caption..."

### 🎯 Goal Decomposition — Complex Plans
- **Automatic planning** — Break "launch a product" into 2–7 concrete steps
- **Step-by-step execution** — Each step runs the right pillar with the right data
- **Plan persistence** — Plans survive bot restarts, resume automatically on startup
- **`/plan` command** — View progress, cancel anytime with `/cancelplan`

### ✨ Self-Reflection — Auto-Optimized Output
- **Critic + Refiner loop** — Evaluates output on hook strength, brand voice, CTA clarity
- **Automatic iteration** — Scores < 7 trigger regeneration (up to 2 rounds)
- **`✨ Auto-optimized`** indicator shown when reflection improved the output
- **Pillar-aware** — Always runs for Content/Strategy, optional for Research, skips Analytics/General

### 🔔 Proactive Intelligence
- **Trend digests** — Weekly search for trending topics in the user's industry
- **Content reminders** — Nudge when the user hasn't posted recently
- **Campaign alerts** — Flag when a campaign has been running long enough to review
- **`/digest` command** — Trigger an on-demand trend digest

### 📸 Vision
- **Image analysis** — Send screenshots, ads, or analytics dashboards
- **Context-aware** — Vision results feed into the appropriate pillar for interpretation
- **Multi-format** — Supports photos, documents, and image replies

### 🧠 Long-Term Memory
- **Key facts extraction** — Auto-extracts 0–3 facts every 10 messages
- **Cross-session recall** — Facts injected into future prompts for continuity
- **`/forget` command** — Clear stored key facts on demand

---

## 📸 Demo

### Welcome & Onboarding
<div align="center">
<img src="docs/screenshots/01-welcome-start.png" alt="Digital Mate Welcome" width="400"/>
</div>

### AI-Powered Content Creation
<div align="center">
<img src="docs/screenshots/02-content-caption.png" alt="Content Creation Demo" width="400"/>
</div>

### Security Guard — Prompt Injection Protection
<div align="center">
<img src="docs/screenshots/03-security-guard.png" alt="Security Guard Demo" width="400"/>
</div>

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Telegram Bot                           │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐    │
│  │  /start       │   │  /brand      │   │  /calendar   │    │
│  │  /plan        │   │  /digest     │   │  /forget     │    │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘    │
│         └──────────────────┼──────────────────┘             │
│                            ▼                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              🛡️ Security Guard Layer                │    │
│  │  Input Guard:  injection | role hijack | exfil      │    │
│  │  Output Guard: leakage | hallucination markers      │    │
│  │  Brand Guard:  field sanitization | injection strip │    │
│  └─────────────────────────┬───────────────────────────┘    │
│                            ▼                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         🧠 Intent Router + Routing Classifier       │    │
│  │  LLM classify → pillar + action                      │    │
│  │  Route decision → workflow | plan | single           │    │
│  └─────────────────────────┬───────────────────────────┘    │
│                            ▼                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              🤖 Agent Orchestrator                  │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │    │
│  │  │ Workflow  │  │ Planner  │  │ Reflection       │  │    │
│  │  │ Engine    │  │ + Executor│  │ (Critic+Refiner) │  │    │
│  │  └──────────┘  └──────────┘  └──────────────────┘  │    │
│  └─────────────────────────┬───────────────────────────┘    │
│                            ▼                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Content  │  │ Strategy │  │ Research │  │Analytics │    │
│  │  Pillar  │  │  Pillar  │  │  Pillar  │  │  Pillar  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│         │              │             │            │          │
│         └──────────────┼─────────────┼────────────┘          │
│                        ▼                                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              📦 Infrastructure Layer                 │    │
│  │  SQLite (sessions, brand, plans, key_facts, triggers)│    │
│  │  Notion │ Tavily/DuckDuckGo │ Vision │ Scheduler    │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| LLM backend | OpenAI-compatible API | Pluggable — works with OpenAI, Anthropic, local models, any compatible endpoint |
| Intent routing | LLM classification + keyword fallback | Accurate semantic routing without fine-tuning |
| Route dispatch | Orchestrator decides: workflow, plan, or single | Same classifier output, three execution paths |
| Memory | SQLite + session context + key facts | Zero-dependency, no external DB needed |
| Prompts | `.md` template files | Easy to edit, version control, iterate without code changes |
| Security | Input/Output/Brand guards | Defense-in-depth against prompt injection, data leakage, role hijacking |
| Integrations | Notion + Web Search + Vision | Real data, not hallucinated marketing advice |
| Reflection | Critic + Refiner loop (max 2 rounds) | Quality gate without infinite loops |
| Planning | LLM planner + executor + SQLite plan store | Survives restarts, supports `/plan` and `/cancelplan` |

---

## 🚀 Quick Start

### One-Line Install

```bash
curl -sSL https://raw.githubusercontent.com/Yanu403/digital-mate/master/install.sh | bash
```

This installs Digital Mate to `~/.digital-mate/`, sets up Python venv, and creates the `.env` config file.

Then start the dashboard:

```bash
~/.digital-mate/bin/digital-mate serve
```

Opens `http://localhost:7749` — configure your Telegram token, LLM key, and brand profile from the web UI. No terminal editing needed.

> **Or auto-launch after install:**
> ```bash
> curl -sSL https://raw.githubusercontent.com/Yanu403/digital-mate/master/install.sh | bash -s -- --launch
> ```

### Manual Install

```bash
git clone https://github.com/Yanu403/digital-mate.git
cd digital-mate
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Configuration

Edit `.env` with your credentials:

```env
# Required
TELEGRAM_BOT_TOKEN=your_bot_token
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_api_key
LLM_MODEL=gpt-4o

# Optional
NOTION_API_KEY=your_notion_key
SEARCH_PROVIDER=duckduckgo
```

> **Works with any OpenAI-compatible endpoint:** OpenAI, Anthropic (via proxy), Groq, Together AI, local Ollama, LM Studio, vLLM, etc.

### Run

```bash
# Development
python -m digital_mate

# Production (systemd)
sudo cp deploy/digital-mate.service /etc/systemd/system/
sudo systemctl enable --now digital-mate
```

---

## 🤖 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message & quick tour |
| `/help` | Full command list with examples |
| `/brand` | Set up your brand profile (name, tone, audience, competitors) |
| `/calendar` | Generate a weekly content calendar |
| `/research` | Deep research on a topic, competitor, or trend |
| `/report` | Create a performance report from your metrics |
| `/plan` | View active plan progress or start a new goal plan |
| `/cancelplan` | Cancel the currently running plan |
| `/digest` | Trigger an on-demand trend digest |
| `/forget` | Clear stored key facts (long-term memory) |
| `/history` | View your recent conversations |
| `/clear` | Reset conversation context |

### Natural Language

Just talk to it naturally — no commands needed:

```
"Analyze my competitor @brandx on Instagram"
"Write a launch email for my SaaS product"
"What are the trending hashtags for fintech in Indonesia?"
"I got 15K impressions, 2.3% engagement, 45 clicks — analyze this"
```

---

## 🔒 Security

Digital Mate ships with a **defense-in-depth security layer** protecting against common LLM application attacks:

### Input Guard
Blocks malicious prompts before they reach the LLM:

| Attack Vector | Detection | Status |
|--------------|-----------|--------|
| Prompt extraction | "ignore instructions", "reveal system prompt" | 🛡️ Blocked |
| Role hijacking | "you are now DAN", "pretend you're..." | 🛡️ Blocked |
| Data exfiltration | "send data to URL", "exfiltrate API keys" | 🛡️ Blocked |
| Obfuscation | Base64-encoded injection, Unicode tricks | 🛡️ Blocked |
| Harmful content | Phishing, malware, social engineering | 🛡️ Blocked |

### Output Guard
Scans LLM responses for:
- System prompt leakage
- Internal configuration exposure
- API key / credential fragments

### Brand Profile Sanitizer
All user-provided brand fields are sanitized against:
- Code block injection
- XML/ChatML tag injection
- Markdown separator abuse

**510 automated tests** covering all security scenarios. See [`tests/test_security.py`](tests/test_security.py).

---

## 🧪 Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=digital_mate --cov-report=term-missing

# Run specific test suite
pytest tests/test_security.py -v        # Security tests
pytest tests/test_content.py -v         # Content pillar tests
pytest tests/test_router.py -v          # Intent routing tests
pytest tests/test_orchestrator.py -v    # Orchestrator + workflow tests
pytest tests/test_planner.py -v         # Goal decomposition tests
pytest tests/test_critic.py -v          # Self-reflection critic tests
pytest tests/test_refiner.py -v         # Self-reflection refiner tests
pytest tests/test_reflection.py -v      # Reflection engine tests
pytest tests/test_triggers.py -v        # Proactive trigger tests
pytest tests/test_scheduler.py -v       # Scheduler tests
pytest tests/test_key_facts.py -v       # Long-term memory tests
pytest tests/test_feedback.py -v        # Feedback button tests
```

```
======================== 510 passed =========================
  380+ functional tests — all pillars, routing, memory, integrations, agent
   25+ security tests — injection, exfiltration, hijacking, leakage
   40+ orchestrator tests — workflows, planning, execution, reflection
   20+ proactive tests — triggers, scheduler, key facts
   15+ feedback tests — 👍/👎/🔄 buttons, regenerate flow
```

---

## 📁 Project Structure

```
digital-mate/
├── digital_mate/
│   ├── AGENT.md              # Bot personality & marketing expertise
│   ├── bot.py                # Telegram handlers + security integration
│   ├── config.py             # Environment configuration
│   ├── router.py             # LLM-powered intent classification
│   ├── llm/
│   │   ├── client.py         # OpenAI-compatible async client
│   │   └── prompts.py        # Template engine (.md file loader)
│   ├── agent/
│   │   ├── orchestrator.py   # Central dispatch: workflow | plan | single
│   │   ├── workflow.py       # Workflow engine + 4 built-in workflows
│   │   ├── planner.py        # LLM goal decomposition (2–7 steps)
│   │   ├── executor.py       # Plan step execution + error recovery
│   │   ├── plan_store.py     # SQLite plan persistence (resume on restart)
│   │   ├── critic.py         # Output quality evaluator
│   │   ├── refiner.py        # Iterative output improvement
│   │   ├── reflection.py     # Reflection engine (critic + refiner loop)
│   │   ├── triggers.py       # Proactive trigger definitions + detection
│   │   └── scheduler.py      # Cron-like scheduled task runner
│   ├── pillars/
│   │   ├── base.py           # Base pillar with shared context
│   │   ├── content.py        # Content & copywriting pipeline
│   │   ├── strategy.py       # Strategy & planning pipeline
│   │   ├── research.py       # Research & insight pipeline
│   │   └── analytics.py      # Analytics & reporting pipeline
│   ├── prompts/              # Prompt templates (editable .md files)
│   │   ├── router.md         # Intent classification rules
│   │   ├── content.md        # Content generation expertise
│   │   ├── strategy.md       # Strategic planning frameworks
│   │   ├── research.md       # Research methodology
│   │   ├── analytics.md      # Analytics interpretation
│   │   ├── planner.md        # Goal decomposition prompt
│   │   └── general.md        # Chitchat / help responses
│   ├── integrations/
│   │   ├── notion_client.py  # Notion API integration
│   │   └── search.py         # Tavily / DuckDuckGo search
│   ├── memory/
│   │   ├── database.py       # SQLite async storage (schema v7)
│   │   ├── session.py        # Conversation context (last N turns)
│   │   ├── brand_profile.py  # Per-chat brand profiles
│   │   ├── key_facts.py      # Long-term memory (auto-extract every 10 msgs)
│   │   ├── response_store.py # Feedback storage (👍/👎/🔄)
│   │   └── autocalendar.py   # Auto content calendar generator
│   └── utils/
│       ├── formatting.py     # Markdown formatting for Telegram
│       ├── validators.py     # Input validation
│       ├── security.py       # Security guard layer
│       ├── keyboards.py      # Inline feedback keyboards (👍/👎/🔄)
│       └── image.py          # Vision / image processing
├── tests/                    # 510 automated tests
├── deploy/                   # Systemd service files
├── docs/
│   ├── ARCHITECTURE.md       # Architecture deep-dive
│   ├── notion-setup.md       # Notion database setup guide
│   └── screenshots/          # Demo screenshots
├── .env.example              # Configuration template
├── requirements.txt          # Python dependencies
└── LICENSE                   # MIT
```

---

## ⚙️ Configuration

### Required

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `LLM_BASE_URL` | OpenAI-compatible API endpoint |
| `LLM_API_KEY` | API key for your LLM provider |
| `LLM_MODEL` | Model name (e.g., `gpt-4o`, `mimo-v2.5-pro`) |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTION_API_KEY` | — | Notion integration token |
| `NOTION_CALENDAR_DB` | — | Content calendar database ID |
| `NOTION_CAMPAIGN_DB` | — | Campaign tracker database ID |
| `SEARCH_PROVIDER` | `duckduckgo` | Search backend (`tavily` or `duckduckgo`) |
| `TAVILY_API_KEY` | — | Required if using Tavily search |
| `MAX_HISTORY` | `10` | Conversation context window |
| `BOT_LANGUAGE` | `en` | Default language (`en`, `id`, `es`, `zh`, `ja`) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## 🗺️ Roadmap

### ✅ Phase 1 — Core
- [x] 4 marketing pillars (content, strategy, research, analytics)
- [x] LLM-powered intent routing
- [x] Bilingual support (English + Indonesian)
- [x] Per-chat brand profiles
- [x] Security guard layer
- [x] Notion integration
- [x] Web search integration
- [x] 105 automated tests (expanded to 510 in Phase 2)

### ✅ Phase 2 — Agentic Intelligence
- [x] Tool chaining & multi-step workflows (4 built-in workflows)
- [x] Goal decomposition & planning (LLM planner, 2–7 steps)
- [x] Plan persistence & auto-resume on restart
- [x] Self-reflection engine (critic + refiner, max 2 iterations)
- [x] Proactive triggers (trend digests, content reminders, campaign alerts)
- [x] Long-term memory (key facts extraction every 10 messages)
- [x] `/plan`, `/cancelplan`, `/forget`, `/digest` commands
- [x] Vision / image input support
- [x] Multi-language support (EN, ID, ES, ZH, JA)
- [x] Feedback buttons (👍/👎/🔄)
- [x] LLM-based routing classifier (replaces keyword matching)
- [x] Reflection feedback visible to user (✨ Auto-optimized indicator)
- [x] 510 automated tests

### 🔜 Phase 3 — Expansion
- [ ] WhatsApp Business API integration
- [ ] Auto-scheduled weekly content calendars
- [ ] Image generation for social posts
- [ ] Analytics dashboard (web UI)
- [ ] Custom training on brand voice history

### 🚀 Phase 4 — Platform
- [ ] Team collaboration (shared brand profiles)
- [ ] A/B testing suggestions with prediction
- [ ] CRM integration (HubSpot, Salesforce)
- [ ] Social media scheduling (direct posting)

---

## 🛠️ Development

```bash
# Install dev dependencies
pip install -r requirements.txt pytest pytest-asyncio pytest-cov

# Run with debug logging
LOG_LEVEL=DEBUG python -m digital_mate

# Format code
black digital_mate/ tests/
ruff check digital_mate/ tests/
```

### Adding a New Pillar

1. Create `digital_mate/pillars/yourpillar.py` extending `BasePillar`
2. Write prompt template at `digital_mate/prompts/yourpillar.md`
3. Register in router's pillar map
4. Add tests in `tests/test_yourpillar.py`

### Adding a New Workflow

1. Define the workflow in `digital_mate/agent/workflow.py`
2. Add detection logic in `digital_mate/agent/orchestrator.py`
3. Add tests in `tests/test_workflow.py`

---

## 🤝 Contributing

Contributions welcome! Here's how:

1. **Fork** the repo
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### Good first issues
- 🏷️ [`good-first-issue`](https://github.com/Yanu403/digital-mate/labels/good-first-issue) — Beginner-friendly tasks
- 🏷️ [`help-wanted`](https://github.com/Yanu403/digital-mate/labels/help-wanted) — Features we need help with
- 🏷️ [`documentation`](https://github.com/Yanu403/digital-mate/labels/documentation) — Docs improvements

### Development setup

```bash
git clone https://github.com/Yanu403/digital-mate.git
cd digital-mate
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov ruff black
pytest  # Should show 510 passing
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — Telegram Bot API wrapper
- [OpenAI Python SDK](https://github.com/openai/openai) — LLM client
- [Tavily](https://tavily.com) — AI-optimized web search
- [Notion API](https://developers.notion.com) — Workspace integration

---

<div align="center">

**Built with ❤️ by [Reazer](https://github.com/Yanu403)**

**⭐ Star this repo** if Digital Mate saved you time — it helps others discover the project and keeps development going.

[![Star History Chart](https://api.star-history.com/svg?repos=Yanu403/digital-mate&type=Date)](https://star-history.com/#Yanu403/digital-mate&Date)

[Share on Twitter](https://twitter.com/intent/tweet?text=Just%20found%20Digital%20Mate%20%E2%80%94%20an%20AI%20marketing%20assistant%20in%20Telegram%20with%20510%20tests%20and%20defense-in-depth%20security.%20Open%20source!%20https://github.com/Yanu403/digital-mate)

</div>
