# 🤖 Digital Mate

**AI-powered Digital Marketing Assistant** — a bilingual (English + Indonesian) Telegram bot that helps you plan, create, and analyze marketing activities.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Alpha-orange)

---

## 🎯 Features

Digital Mate organizes marketing assistance into **4 pillars**:

### ✍️ Content & Copywriting
- Generate engaging social media captions with relevant hashtags
- Create attention-grabbing hooks for videos and reels
- Craft effective calls-to-action (CTAs)
- Brainstorm content ideas and themes
- Rewrite and improve existing copy
- Plan content calendars

### 📋 Strategy & Planning
- Create comprehensive marketing plans with SMART goals
- Design marketing funnels (Awareness → Consideration → Conversion)
- Budget allocation recommendations with ROI estimates
- Campaign timelines and scheduling
- Product launch strategies
- Marketing audits and performance reviews

### 🔍 Research & Insight
- Market trend analysis with real-time web search
- Competitor analysis and benchmarking
- Audience research and persona development
- Keyword research and SEO insights
- Industry benchmark data and comparisons

### 📊 Analytics & Reporting
- Generate performance reports from campaign data
- Define and track meaningful KPIs
- Interpret marketing metrics with context
- ROI calculations and analysis
- Data-driven improvement recommendations

### 🔗 Integrations
- **Notion** — Content calendar and campaign tracker synchronization
- **Web Search** — Real-time research via Tavily (primary) or DuckDuckGo (fallback)
- **Bilingual** — Responds in English or Bahasa Indonesia based on user's language

---

## ⚡ Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/Yanu403/digital-mate.git
cd digital-mate

# 2. Create and configure environment
cp .env.example .env
# Edit .env with your credentials (see Configuration below)

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the bot
python -m digital_mate
```

### CLI Options

```bash
python -m digital_mate --help          # Show usage info
python -m digital_mate --version       # Show version
python -m digital_mate --init-db       # Initialize database only
python -m digital_mate --log-level DEBUG  # Enable debug logging
```

---

## 📋 Commands Reference

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and introduction |
| `/help` | Show available commands and usage tips |
| `/brand` | Set up your brand profile for personalized responses |
| `/calendar` | View this week's content calendar (requires Notion) |
| `/report` | Generate a quick performance report (requires Notion) |
| `/clear` | Clear conversation context for this chat |
| `/language en\|id\|bilingual` | Set response language preference |
| `/cancel` | Cancel the current operation |

---

## ⚙️ Configuration

All settings are configured via environment variables or a `.env` file:

### Required

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) | — |
| `LLM_API_KEY` | API key for your LLM provider | — |

### LLM Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_BASE_URL` | OpenAI-compatible API base URL | `https://api.openai.com/v1` |
| `LLM_MODEL` | Model for generating responses | `gpt-4o` |
| `LLM_ROUTER_MODEL` | Model for intent classification (cheaper) | Falls back to `LLM_MODEL` |

### Notion (Optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `NOTION_API_KEY` | Notion integration API key | — |
| `NOTION_CONTENT_CALENDAR_DB` | Content calendar database ID | — |
| `NOTION_CAMPAIGN_TRACKER_DB` | Campaign tracker database ID | — |

See [Notion Setup Guide](docs/notion-setup.md) for detailed instructions.

### Search (Optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `TAVILY_API_KEY` | Tavily API key for better search results | Falls back to DuckDuckGo |

### Bot Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `BOT_LANGUAGE` | Language mode: `bilingual`, `en`, or `id` | `bilingual` |
| `BOT_NAME` | Bot display name | `Digital Mate` |
| `MAX_CONVERSATION_TURNS` | Max conversation turns to remember | `10` |

---

## 📅 Notion Setup

For content calendar and campaign tracker features, you'll need to set up Notion databases.

👉 See [docs/notion-setup.md](docs/notion-setup.md) for step-by-step instructions.

---

## 🏗️ Architecture

```
User Message (Telegram)
    │
    ▼
bot.py ──── Message handler + typing indicator
    │
    ▼
router.py ── LLM-based intent classification → pillar + action
    │
    ├──── content.py     (Captions, hooks, hashtags, CTAs)
    ├──── strategy.py    (Plans, funnels, budgets)
    ├──── research.py    (Trends, competitors, search)
    └──── analytics.py   (Reports, KPIs, ROI)
         │
         ▼
    llm/client.py ─── OpenAI-compatible API
    integrations/ ──── Notion API + Web Search
    memory/ ────────── SQLite (session + brand profiles)
         │
         ▼
bot.py ──── Send formatted response (split if >4096 chars)
```

### Key Design Decisions

- **Async-first**: All I/O operations use async/await
- **Pillar pattern**: Each marketing domain is an independent module
- **LLM-agnostic**: Works with any OpenAI-compatible API (OpenAI, Ollama, etc.)
- **Graceful degradation**: Optional integrations fail silently with helpful messages
- **Keyword fallback**: Router falls back to keyword matching if LLM is unavailable
- **No external dependencies** for Notion/Search — uses httpx directly

---

## 🛣️ Roadmap

### Phase 2 (Planned)
- [ ] **WhatsApp support** via WhatsApp Business API
- [ ] **Auto-scheduling** — schedule posts directly to social platforms
- [ ] **Analytics dashboard** — web-based performance visualization
- [ ] **Multi-language expansion** — add Spanish, Portuguese, Japanese

### Phase 3 (Future)
- [ ] Team collaboration features
- [ ] AI image generation for social posts
- [ ] CRM integration (HubSpot, Salesforce)
- [ ] A/B testing framework for content

---

## 🧪 Development

```bash
# Run tests
pytest tests/ -v

# Run with debug logging
python -m digital_mate --log-level DEBUG
```

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Built with [python-telegram-bot](https://python-telegram-bot.org/)
- LLM integration via [OpenAI SDK](https://github.com/openai/openai-python)
- Powered by your favorite LLM provider

---

*Made with ❤️ for digital marketers everywhere.*
