<div align="center">

<img src="docs/screenshots/banner.png" alt="Digital Mate Banner" width="100%"/>

# 🤖 Digital Mate

### Your AI Digital Marketing Assistant

**An intelligent Telegram bot that plans, creates, and analyzes marketing activities — from content creation to performance reporting.**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-105%20Passing-brightgreen?style=for-the-badge)](#testing)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/digitalmate_marketing_bot)

[Features](#features) · [Demo](#demo) · [Quick Start](#quick-start) · [Architecture](#architecture) · [Security](#security) · [Roadmap](#roadmap)

</div>

---

## 🎯 What is Digital Mate?

Digital Mate is a **production-grade AI marketing assistant** built for Telegram. It understands natural language marketing requests, routes them to specialized AI pipelines, and delivers actionable outputs — captions, strategies, research reports, and analytics.

**No dashboard. No learning curve. Just chat.**

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
│  │  /help        │   │  /research   │   │  /report     │    │
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
│  │              🧠 Intent Router (LLM)                 │    │
│  │  classify → content | strategy | research | analytics│    │
│  │  confidence scoring + keyword fallback               │    │
│  └─────────────────────────┬───────────────────────────┘    │
│                            ▼                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Content  │  │ Strategy │  │ Research │  │Analytics │    │
│  │  Pillar  │  │  Pillar  │  │  Pillar  │  │  Pillar  │    │
│  │ (LLM)   │  │ (LLM)   │  │ (LLM+Web)│  │ (LLM)   │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│         │              │             │            │          │
│         └──────────────┼─────────────┼────────────┘          │
│                        ▼                                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              📦 Infrastructure Layer                 │    │
│  │  SQLite Session Memory │ Brand Profiles (per-chat)  │    │
│  │  Notion Integration    │ Tavily/DuckDuckGo Search   │    │
│  │  Conversation Context  │ Template Engine (.md)      │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| LLM backend | OpenAI-compatible API | Pluggable — works with OpenAI, Anthropic, local models, any compatible endpoint |
| Intent routing | LLM classification + keyword fallback | Accurate semantic routing without fine-tuning |
| Memory | SQLite + session context | Zero-dependency, no external DB needed |
| Prompts | `.md` template files | Easy to edit, version control, iterate without code changes |
| Security | Input/Output/Brand guards | Defense-in-depth against prompt injection, data leakage, role hijacking |
| Integrations | Notion + Web Search | Real data, not hallucinated marketing advice |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- OpenAI-compatible API key

### Installation

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

**105 automated tests** covering all security scenarios. See [`tests/test_security.py`](tests/test_security.py).

---

## 🧪 Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=digital_mate --cov-report=term-missing

# Run specific test suite
pytest tests/test_security.py -v    # Security tests
pytest tests/test_content.py -v    # Content pillar tests
pytest tests/test_router.py -v     # Intent routing tests
```

```
======================== 105 passed in 12.4s =========================
  80 functional tests — all pillars, routing, memory, integrations
  25 security tests — injection, exfiltration, hijacking, leakage
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
│   │   └── analytics.md      # Analytics interpretation
│   ├── integrations/
│   │   ├── notion_client.py  # Notion API integration
│   │   └── search.py         # Tavily / DuckDuckGo search
│   ├── memory/
│   │   ├── database.py       # SQLite async storage
│   │   ├── session.py        # Conversation context (last N turns)
│   │   └── brand_profile.py  # Per-chat brand profiles
│   └── utils/
│       ├── formatting.py     # Markdown formatting for Telegram
│       ├── validators.py     # Input validation
│       └── security.py       # Security guard layer
├── tests/                    # 105 automated tests
├── deploy/                   # Systemd service files
├── docs/
│   ├── SPEC.md               # Full technical specification
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
| `BOT_LANGUAGE` | `en` | Default language (`en` or `id`) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## 🗺️ Roadmap

### ✅ Phase 1 — Core (Current)
- [x] 4 marketing pillars (content, strategy, research, analytics)
- [x] LLM-powered intent routing
- [x] Bilingual support (English + Indonesian)
- [x] Per-chat brand profiles
- [x] Security guard layer
- [x] Notion integration
- [x] Web search integration
- [x] 105 automated tests

### 🔜 Phase 2 — Expansion
- [ ] WhatsApp Business API integration
- [ ] Auto-scheduled weekly content calendars
- [ ] Image generation for social posts
- [ ] Analytics dashboard (web UI)
- [ ] Multi-language support (ES, ZH, JA)

### 🚀 Phase 3 — Platform
- [ ] Team collaboration (shared brand profiles)
- [ ] A/B testing suggestions with prediction
- [ ] CRM integration (HubSpot, Salesforce)
- [ ] Social media scheduling (direct posting)
- [ ] Custom training on brand voice history

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

*If you find this useful, give it a ⭐ — it helps more than you think.*

</div>
