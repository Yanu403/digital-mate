"""Telegram bot setup: Application, handlers, and command callbacks.

Registers all command handlers, the conversation handler for brand setup,
and the message handler that routes messages through the IntentRouter.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from digital_mate.config import Settings
from digital_mate.llm.client import LLMClient
from digital_mate.router import IntentRouter
from digital_mate.pillars.content import ContentPillar
from digital_mate.pillars.strategy import StrategyPillar
from digital_mate.pillars.research import ResearchPillar
from digital_mate.pillars.analytics import AnalyticsPillar
from digital_mate.memory.session import SessionManager
from digital_mate.memory.brand_profile import BrandProfileManager, BrandProfile
from digital_mate.memory.key_facts import KeyFactManager
from digital_mate.integrations.notion_client import NotionService
from digital_mate.integrations.search import SearchService
from digital_mate.utils.formatting import split_message, format_calendar_week, format_calendar_entry
from digital_mate.utils.validators import sanitize_input
from digital_mate.utils.security import input_guard, output_guard, sanitize_brand_field, GuardResult, RateLimitState
from digital_mate.llm.prompts import build_general_messages, build_brand_context
from digital_mate.memory.autocalendar import AutoCalendarManager, AutoCalendarSubscription
from digital_mate.memory.response_store import ResponseStore
from digital_mate.pillars.autocalendar import CalendarGenerator
from digital_mate.memory.autocalendar import AutoCalendarEntry as CalendarEntry
from digital_mate.utils.keyboards import feedback_keyboard
from digital_mate.utils.image import encode_image_file
from digital_mate.agent.orchestrator import Orchestrator
from digital_mate.agent.planner import Planner
from digital_mate.agent.plan_store import PlanStore
from digital_mate.agent.reflection import ReflectionEngine
from digital_mate.agent.triggers import TriggerEngine
from digital_mate.agent.scheduler import WorkflowScheduler
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# System prompt for image/vision analysis — used when a user sends a photo
# without a specific pillar routing keyword in the caption.
IMAGE_ANALYSIS_SYSTEM_PROMPT = (
    "You are Digital Mate, an AI digital marketing assistant. "
    "The user has shared an image. Analyze it from a marketing perspective:\n\n"
    "1. If it's an analytics dashboard/screenshot: identify key metrics, trends, "
    "and suggest improvements\n"
    "2. If it's a competitor's ad/creative: analyze the copy, visual strategy, "
    "target audience, and positioning\n"
    "3. If it's a design draft: evaluate visual hierarchy, brand consistency, "
    "and marketing effectiveness\n"
    "4. If it's a social media post: assess engagement potential, hook strength, "
    "and content quality\n"
    "5. Otherwise: describe what you see and relate it to marketing if possible\n\n"
    "Respond in the user's language (match their caption language or default to bilingual).\n"
    "Be specific and actionable. Don't just describe — provide marketing insights and recommendations."
)

# Brand setup conversation states
(
    ASK_NAME,
    ASK_INDUSTRY,
    ASK_AUDIENCE,
    ASK_TONE,
    ASK_PRODUCTS,
    ASK_HASHTAGS,
    ASK_COMPETITORS,
    ASK_PLATFORM,
    ASK_BUDGET,
    ASK_STAGE,
    CONFIRM,
) = range(11)


class DigitalMateBot:
    """Main bot class that wires all services together and handles Telegram events.

    Manages the lifecycle of the Telegram Application, registers handlers,
    and dispatches user messages through the router to appropriate pillars.
    """

    def __init__(
        self,
        settings: Settings,
        llm_client: LLMClient,
        router: IntentRouter,
        session_manager: SessionManager,
        brand_manager: BrandProfileManager,
        notion_service: NotionService | None = None,
        search_service: SearchService | None = None,
        autocalendar_manager: AutoCalendarManager | None = None,
        response_store: ResponseStore | None = None,
        key_fact_manager: KeyFactManager | None = None,
        plan_store: PlanStore | None = None,
        reflection_engine: ReflectionEngine | None = None,
        trigger_engine: TriggerEngine | None = None,
        scheduler: WorkflowScheduler | None = None,
    ) -> None:
        """Initialize the bot with all services.

        Args:
            settings: Application settings.
            llm_client: LLM client.
            router: Intent router.
            session_manager: Session context manager.
            brand_manager: Brand profile manager.
            notion_service: Optional Notion integration.
            search_service: Optional web search service.
            autocalendar_manager: Optional auto-calendar subscription manager.
            response_store: Optional response store for feedback buttons.
                When None, feedback buttons are not attached to responses.
            key_fact_manager: Optional key fact manager for long-term memory.
            plan_store: Optional plan store for multi-step plan persistence.
            reflection_engine: Optional reflection engine for self-reflection.
            trigger_engine: Optional trigger engine for proactive notifications.
            scheduler: Optional workflow scheduler for autonomous workflows.
        """
        self.settings = settings
        self.llm_client = llm_client
        self.router = router
        self.session_manager = session_manager
        self.brand_manager = brand_manager
        self.notion_service = notion_service
        self.search_service = search_service
        self.autocalendar_manager = autocalendar_manager
        self.response_store = response_store
        self.key_fact_manager = key_fact_manager
        self._calendar_generator: CalendarGenerator | None = None
        if autocalendar_manager is not None:
            self._calendar_generator = CalendarGenerator(
                llm_client, autocalendar_manager, notion_service,
            )

        # Initialize pillars
        self.content_pillar = ContentPillar(llm_client, settings.bot_language, settings.bot_name)
        self.strategy_pillar = StrategyPillar(llm_client, settings.bot_language, settings.bot_name)
        self.research_pillar = ResearchPillar(
            llm_client, search_service=search_service,
            language=settings.bot_language, bot_name=settings.bot_name,
        )
        self.analytics_pillar = AnalyticsPillar(
            llm_client, notion_service=notion_service,
            language=settings.bot_language, bot_name=settings.bot_name,
        )

        self._pillars = {
            "content": self.content_pillar,
            "strategy": self.strategy_pillar,
            "research": self.research_pillar,
            "analytics": self.analytics_pillar,
        }

        # Orchestrator for multi-step workflow chaining (Phase 1) and planning (Phase 2)
        self.plan_store = plan_store
        self.reflection_engine = reflection_engine
        self.trigger_engine = trigger_engine
        self.scheduler = scheduler
        self._planner: Planner | None = None
        if plan_store is not None:
            self._planner = Planner(llm_client)
        self._orchestrator = Orchestrator(
            self._pillars,
            planner=self._planner,
            plan_store=plan_store,
            llm_client=llm_client,
        )

        self._rate_limits: TTLCache[int, RateLimitState] = TTLCache(maxsize=1000, ttl=3600)
        self.app: Application | None = None

    async def _rate_limit_cleanup_loop(self, interval_hours: int = 1) -> None:
        """Periodically reset injection counters for all tracked users."""
        while True:
            await asyncio.sleep(interval_hours * 3600)
            for state in list(self._rate_limits.values()):
                state.reset()
            logger.debug("Rate limit counters reset for %d users", len(self._rate_limits))

    def build_application(self) -> Application:
        """Build and configure the Telegram Application with all handlers.

        Returns:
            Configured Telegram Application ready to run.
        """
        builder = Application.builder().token(self.settings.telegram_bot_token)
        self.app = builder.build()

        # Store services in bot_data for access in handlers
        self.app.bot_data["bot_instance"] = self

        # Register command handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("brand", self._cmd_brand_start))
        self.app.add_handler(CommandHandler("calendar", self._cmd_calendar))
        self.app.add_handler(CommandHandler("report", self._cmd_report))
        self.app.add_handler(CommandHandler("clear", self._cmd_clear))
        self.app.add_handler(CommandHandler("language", self._cmd_language))
        self.app.add_handler(CommandHandler("autocalendar", self._cmd_autocalendar))
        self.app.add_handler(CommandHandler("cancel", self._cmd_cancel))
        self.app.add_handler(CommandHandler("plan", self._cmd_plan))
        self.app.add_handler(CommandHandler("cancelplan", self._cmd_cancelplan))
        self.app.add_handler(CommandHandler("forget", self._cmd_forget))
        self.app.add_handler(CommandHandler("digest", self._cmd_digest))

        # Brand setup conversation handler
        brand_conv = ConversationHandler(
            entry_points=[CommandHandler("brand", self._cmd_brand_start)],
            states={
                ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_name)],
                ASK_INDUSTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_industry)],
                ASK_AUDIENCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_audience)],
                ASK_TONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_tone)],
                ASK_PRODUCTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_products)],
                ASK_HASHTAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_hashtags)],
                ASK_COMPETITORS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_competitors)],
                ASK_PLATFORM: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_platform)],
                ASK_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_budget)],
                ASK_STAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_stage)],
                CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._brand_confirm)],
            },
            fallbacks=[CommandHandler("cancel", self._cmd_cancel)],
            per_chat=True,
            per_user=False,
            per_message=False,
        )
        self.app.add_handler(brand_conv, group=1)

        # Message handler for all text messages (routes through intent router)
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message),
            group=2,
        )

        # Photo handler — images are analyzed via the vision LLM
        self.app.add_handler(
            MessageHandler(filters.PHOTO, self._handle_photo),
            group=2,
        )

        # Feedback button callback handler (👍/👎/🔄 on pillar responses)
        self.app.add_handler(
            CallbackQueryHandler(self._handle_feedback_callback, pattern=r"^fb:"),
            group=3,
        )

        return self.app

    # -----------------------------------------------------------------------
    # Command handlers
    # -----------------------------------------------------------------------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command — show welcome message."""
        name = self.settings.bot_name
        text = (
            f"👋 Welcome to *{name}*!\n\n"
            f"I'm your AI-powered Digital Marketing Assistant, here to help you with:\n\n"
            f"✍️ *Content & Copywriting* — Captions, hooks, hashtags, CTAs\n"
            f"📋 *Strategy & Planning* — Marketing plans, funnels, budgets\n"
            f"🔍 *Research & Insight* — Trends, competitors, audience analysis\n"
            f"📊 *Analytics & Reporting* — Reports, KPIs, ROI, improvements\n\n"
            f"Just type your question or request, and I'll help! "
            f"Use /help for more commands.\n\n"
            f"💡 Tip: Set up your brand profile with /brand for personalized responses!"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command — show available commands."""
        text = (
            f"📚 *{self.settings.bot_name} — Commands*\n\n"
            f"/start — Welcome message\n"
            f"/help — Show this help\n"
            f"/brand — Set up your brand profile\n"
            f"/calendar — View content calendar (Notion)\n"
            f"/report — Quick performance report (Notion)\n"
            f"/autocalendar — Auto weekly content calendar (opt-in)\n"
            f"/plan — Show active plan progress\n"
            f"/cancelplan — Cancel active plan\n"
            f"/digest — Generate weekly content digest\n"
            f"/forget — Clear stored key facts about you\n"
            f"/clear — Clear conversation context\n"
            f"/language en|id|bilingual — Set language\n"
            f"/cancel — Cancel current operation\n\n"
            f"*4 Marketing Pillars:*\n"
            f"✍️ Content — \"Write me a caption for...\"\n"
            f"📋 Strategy — \"Create a marketing plan for...\"\n"
            f"🔍 Research — \"What are the latest trends in...\"\n"
            f"📊 Analytics — \"How do I calculate ROI for...\"\n\n"
            f"Just ask naturally — I'll figure out what you need! 😊"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_calendar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /calendar command — show this week's content calendar."""
        if not self.notion_service or not self.notion_service.is_configured:
            await update.message.reply_text(
                "📅 Calendar feature requires Notion integration.\n"
                "Set up your Notion databases and add the IDs to your .env file.\n"
                "See: https://github.com/Yanu403/digital-mate/blob/main/docs/notion-setup.md"
            )
            return

        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            entries = await self.notion_service.get_content_calendar(days=7)
            text = format_calendar_week(entries)
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception as exc:
            logger.error("Calendar command failed: %s", exc)
            await update.message.reply_text("⚠️ Could not fetch calendar data. Please check your Notion configuration.")

    async def _cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /report command — generate quick performance report."""
        if not self.notion_service or not self.notion_service.is_configured:
            await update.message.reply_text(
                "📊 Report feature requires Notion integration.\n"
                "Set up your Notion databases and add the IDs to your .env file.\n"
                "See: https://github.com/Yanu403/digital-mate/blob/main/docs/notion-setup.md"
            )
            return

        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            campaigns = await self.notion_service.get_campaigns()
            # Use analytics pillar to generate report
            response = await self.analytics_pillar.handle(
                user_message="Generate a quick performance summary based on the available campaign data.",
                action="report",
                context=[],
            )
            for chunk in split_message(response):
                await update.message.reply_text(chunk)
        except Exception as exc:
            logger.error("Report command failed: %s", exc)
            await update.message.reply_text("⚠️ Could not generate report. Please check your Notion configuration.")

    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /clear command — clear conversation context."""
        chat_id = update.effective_chat.id
        count = await self.session_manager.clear(chat_id)
        await update.message.reply_text(
            f"🧹 Conversation context cleared! ({count} messages removed)\n"
            f"Starting fresh — ask me anything!"
        )

    async def _cmd_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /language command — set response language."""
        args = context.args
        if not args or args[0].lower() not in ("en", "id", "bilingual"):
            await update.message.reply_text(
                "🌐 *Language Settings*\n\n"
                "Usage: `/language <option>`\n\n"
                "Options:\n"
                "• `en` — Always respond in English\n"
                "• `id` — Always respond in Bahasa Indonesia\n"
                "• `bilingual` — Match the user's language (default)\n\n"
                "Example: `/language bilingual`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        lang = args[0].lower()
        # Update language in all services
        self.router.language = lang
        for pillar in self._pillars.values():
            pillar.language = lang

        chat_id = update.effective_chat.id
        profile = await self.brand_manager.get(chat_id)
        if profile:
            profile.language_pref = lang
            await self.brand_manager.update(profile)

        lang_names = {"en": "English 🇬🇧", "id": "Bahasa Indonesia 🇮🇩", "bilingual": "Bilingual 🌐"}
        await update.message.reply_text(f"✅ Language set to: *{lang_names.get(lang, lang)}*", parse_mode=ParseMode.MARKDOWN)

    async def _cmd_autocalendar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /autocalendar command — manage opt-in weekly auto-generated content calendars.

        Subcommands:
            /autocalendar              — show current status
            /autocalendar on [day] [h] — enable weekly calendar
            /autocalendar off          — disable weekly calendar
            /autocalendar now          — generate immediately
        """
        if self.autocalendar_manager is None:
            await update.message.reply_text(
                "⚠️ Auto-calendar feature is not available (database not configured)."
            )
            return

        chat_id = update.effective_chat.id
        args = context.args

        if not args:
            sub = "status"
        else:
            sub = args[0].lower()

        if sub == "on":
            await self._autocalendar_on(update, chat_id, args[1:])
        elif sub == "off":
            await self._autocalendar_off(update, chat_id)
        elif sub == "status":
            await self._autocalendar_status(update, chat_id)
        elif sub == "now":
            await self._autocalendar_now(update, chat_id)
        else:
            await update.message.reply_text(
                "📅 *Auto-Calendar*\\n\\n"
                "Usage:\\n"
                "• `/autocalendar` — Show current status\\n"
                "• `/autocalendar on [day] [hour]` — Enable weekly calendar\\n"
                "• `/autocalendar off` — Disable weekly calendar\\n"
                "• `/autocalendar now` — Generate immediately\\n\\n"
                "`day` is 0–6 (Mon=0 … Sun=6), `hour` is 0–23.\\n"
                "Default: Monday 09:00.\\n\\n"
                "Example: `/autocalendar on 1 9` → every Tuesday at 09:00",
                parse_mode=ParseMode.MARKDOWN,
            )

    async def _autocalendar_on(self, update: Update, chat_id: int, extra: list[str]) -> None:
        """Enable auto-calendar for a chat."""
        day_of_week = 0  # Monday
        hour = 9

        if len(extra) >= 1:
            try:
                d = int(extra[0])
                if not 0 <= d <= 6:
                    await update.message.reply_text("❌ Day must be 0–6 (Mon=0 … Sun=6).")
                    return
                day_of_week = d
            except ValueError:
                await update.message.reply_text("❌ Day must be a number 0–6 (Mon=0 … Sun=6).")
                return

        if len(extra) >= 2:
            try:
                h = int(extra[1])
                if not 0 <= h <= 23:
                    await update.message.reply_text("❌ Hour must be 0–23.")
                    return
                hour = h
            except ValueError:
                await update.message.reply_text("❌ Hour must be a number 0–23.")
                return

        sub = AutoCalendarSubscription(
            chat_id=chat_id,
            enabled=True,
            day_of_week=day_of_week,
            hour=hour,
        )
        await self.autocalendar_manager.set_subscription(sub)

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        await update.message.reply_text(
            f"✅ Auto-calendar *enabled*!\\n\\n"
            f"📅 Schedule: every *{day_names[day_of_week]}* at *{hour:02d}:00*\\n"
            f"I'll generate a fresh 7-day content calendar and push it to Notion each week.\\n\\n"
            f"Use `/autocalendar now` to generate immediately, or `/autocalendar off` to disable.",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _autocalendar_off(self, update: Update, chat_id: int) -> None:
        """Disable auto-calendar for a chat."""
        sub = await self.autocalendar_manager.get_subscription(chat_id)
        if sub is None or not sub.enabled:
            await update.message.reply_text("ℹ️ Auto-calendar is already disabled.")
            return

        sub.enabled = False
        await self.autocalendar_manager.set_subscription(sub)
        await update.message.reply_text("⏸️ Auto-calendar *disabled*. You can re-enable with `/autocalendar on`.", parse_mode=ParseMode.MARKDOWN)

    async def _autocalendar_status(self, update: Update, chat_id: int) -> None:
        """Show auto-calendar status for a chat."""
        sub = await self.autocalendar_manager.get_subscription(chat_id)
        if sub is None or not sub.enabled:
            await update.message.reply_text(
                "📅 Auto-calendar: *disabled*\\n\\n"
                "Enable with `/autocalendar on`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        last = sub.last_run_at.strftime("%Y-%m-%d %H:%M") if sub.last_run_at else "never"
        await update.message.reply_text(
            f"📅 Auto-calendar: *enabled*\\n\\n"
            f"Schedule: every *{day_names[sub.day_of_week]}* at *{sub.hour:02d}:00*\\n"
            f"Last run: {last}\\n\\n"
            f"Commands: `/autocalendar off`, `/autocalendar now`",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _autocalendar_now(self, update: Update, chat_id: int) -> None:
        """Generate an auto-calendar immediately for a chat."""
        await update.message.reply_text("🔄 Generating your content calendar now... this may take a moment.")

        summary = await self._run_autocalendar_for_chat(chat_id)
        await update.message.reply_text(summary)

    async def _run_autocalendar_for_chat(self, chat_id: int) -> str:
        """Generate and deliver a content calendar for a single chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Summary message text for the user.
        """
        if self.autocalendar_manager is None or self._calendar_generator is None:
            return "⚠️ Auto-calendar is not available."

        brand_profile = await self.brand_manager.get(chat_id)

        try:
            entries = await self._calendar_generator.generate_weekly_calendar(brand_profile)
        except Exception as exc:
            logger.error("Calendar generation failed for chat %d: %s", chat_id, exc, exc_info=True)
            return f"⚠️ Calendar generation failed: {exc}"

        # Push to Notion if configured
        notion_count = 0
        if self.notion_service and self.notion_service.is_configured:
            for entry in entries:
                page_id = await self.notion_service.create_content_entry(
                    date=entry.date,
                    platform=entry.platform,
                    content_type=entry.content_type,
                    topic=entry.topic,
                    caption=entry.caption,
                    hashtags=entry.hashtags,
                )
                if page_id:
                    entry.notion_page_id = page_id
                    notion_count += 1

        # Persist entries
        await self.autocalendar_manager.add_entries(chat_id, entries)
        await self.autocalendar_manager.update_last_run(chat_id)

        # Build summary
        lines = [f"📅 *Weekly Content Calendar* ({len(entries)} posts)\n"]
        for entry in entries:
            lines.append(format_calendar_entry(entry.to_dict()))
        lines.append(f"\n{'─' * 30}")
        if notion_count > 0:
            lines.append(f"✅ {notion_count}/{len(entries)} entries pushed to Notion")
        elif self.notion_service and self.notion_service.is_configured:
            lines.append("⚠️ Notion is configured but no entries were pushed")
        else:
            lines.append("💡 Connect Notion to sync entries automatically")
        return "\n".join(lines)

    async def autocalendar_loop(self) -> None:
        """Background loop that checks for due auto-calendars and generates them.

        Runs indefinitely until cancelled. Checks every minute for subscriptions
        whose scheduled day-of-week and hour match the current time and that
        haven't been run in the last 23 hours.
        """
        if self.autocalendar_manager is None:
            logger.warning("Auto-calendar loop disabled: manager not configured")
            return

        logger.info("Auto-calendar background loop started")
        while True:
            try:
                now = datetime.now()
                all_subs = await self.autocalendar_manager.get_enabled_subscriptions()
                # Filter to subscriptions due now (matching day + hour, not already run today)
                due_subs = [
                    sub for sub in all_subs
                    if sub.day_of_week == now.weekday()
                    and sub.hour == now.hour
                    and sub.last_run_at != now.strftime("%Y-%m-%d")
                ]
                for sub in due_subs:
                    logger.info("Auto-calendar: generating for chat %d", sub.chat_id)
                    try:
                        summary = await self._run_autocalendar_for_chat(sub.chat_id)
                        # Send via bot if app is available
                        if self.app and self.app.bot:
                            for chunk in split_message(summary):
                                await self.app.bot.send_message(chat_id=sub.chat_id, text=chunk)
                    except Exception as exc:
                        logger.error("Auto-calendar run failed for chat %d: %s", sub.chat_id, exc, exc_info=True)
            except asyncio.CancelledError:
                logger.info("Auto-calendar loop cancelled")
                raise
            except Exception as exc:
                logger.error("Auto-calendar loop error: %s", exc, exc_info=True)

            await asyncio.sleep(60)

    async def resume_interrupted_plans(self) -> None:
        """On startup, check for and resume any interrupted plans.

        An interrupted plan is one with status='active' that has at least
        one step with status='running' (the bot was killed mid-execution).
        Resets running steps to pending, notifies the user, and re-executes
        from the first non-completed step.

        This is fire-and-forget — errors are logged but never block startup.
        """
        if self.plan_store is None or self._orchestrator is None:
            return

        try:
            plans = await self.plan_store.get_interrupted_plans()
        except Exception as exc:
            logger.error("Failed to check for interrupted plans: %s", exc)
            return

        for plan in plans:
            chat_id = plan["chat_id"]
            plan_id = plan["plan_id"]
            goal = plan["goal"]

            logger.info("Resuming interrupted plan %s for chat %d: %s", plan_id, chat_id, goal[:60])

            # Notify user that we're resuming
            try:
                if self.app and self.app.bot:
                    goal_short = goal[:50] + "..." if len(goal) > 50 else goal
                    await self.app.bot.send_message(
                        chat_id=chat_id,
                        text=f"🔄 Resuming your plan: \"{goal_short}\"",
                    )
            except Exception as exc:
                logger.warning("Failed to notify chat %d about plan resume: %s", chat_id, exc)

            # Re-execute from first non-completed step
            try:
                pending_steps = [s for s in plan["steps"] if s["status"] != "completed"]
                if not pending_steps:
                    await self.plan_store.complete_plan(plan_id)
                    continue

                # Get brand profile for context
                brand_profile = await self.brand_manager.get(chat_id)
                ctx = await self.session_manager.get_context(chat_id)
                key_facts_text = ""
                if self.key_fact_manager:
                    key_facts_text = await self.key_fact_manager.get_facts_context(chat_id)

                # Use executor to run remaining steps
                if self._orchestrator._executor is not None:
                    result_text = await self._orchestrator._executor.execute(
                        plan_id=plan_id,
                        steps=plan["steps"],
                        user_message=goal,
                        context=ctx,
                        brand_profile=brand_profile,
                        key_facts=key_facts_text,
                    )

                    # Send result to user
                    if self.app and self.app.bot:
                        from digital_mate.utils.formatting import split_message
                        for chunk in split_message(result_text):
                            await self.app.bot.send_message(chat_id=chat_id, text=chunk)

                    logger.info("Resumed and completed plan %s for chat %d", plan_id, chat_id)
            except Exception as exc:
                logger.error("Failed to resume plan %s for chat %d: %s", plan_id, chat_id, exc)
                try:
                    await self.plan_store.fail_plan(plan_id, str(exc))
                except Exception:
                    pass

    async def _cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /cancel command — cancel current operation."""
        await update.message.reply_text("❌ Operation cancelled. You can start fresh anytime!")
        return ConversationHandler.END

    async def _cmd_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /plan command — show active plan progress."""
        if self.plan_store is None:
            await update.message.reply_text("📋 Plan feature is not available.")
            return

        chat_id = update.effective_chat.id
        plan = await self.plan_store.get_active_plan(chat_id)

        if plan is None:
            await update.message.reply_text(
                "📋 No active plan.\n\n"
                "Send me a complex marketing goal and I'll create a multi-step plan for you!\n"
                "Example: \"Help me launch a full Instagram campaign for my coffee brand\""
            )
            return

        steps = plan["steps"]
        goal = plan["goal"]
        goal_short = goal[:60] + "..." if len(goal) > 60 else goal

        lines = [f'📋 *Active Plan:* "{goal_short}"', ""]
        for step in steps:
            order = step["step_order"]
            desc = step["description"]
            status = step["status"]
            if status == "completed":
                lines.append(f"✅ {order}/{len(steps)}: {desc}")
            elif status == "running":
                lines.append(f"⏳ {order}/{len(steps)}: {desc} [running...]")
            elif status == "failed":
                err = step.get("error_message", "unknown error")
                lines.append(f"❌ {order}/{len(steps)}: {desc} ({err})")
            else:
                lines.append(f"⬜ {order}/{len(steps)}: {desc}")

        lines.append(f"\nStatus: _{plan['status']}_")
        lines.append("Use /cancelplan to cancel this plan.")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    async def _cmd_cancelplan(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cancelplan command — cancel active plan."""
        if self.plan_store is None:
            await update.message.reply_text("📋 Plan feature is not available.")
            return

        chat_id = update.effective_chat.id
        plan = await self.plan_store.get_active_plan(chat_id)

        if plan is None:
            await update.message.reply_text("📋 No active plan to cancel.")
            return

        await self.plan_store.cancel_plan(plan["plan_id"])
        goal = plan["goal"]
        goal_short = goal[:60] + "..." if len(goal) > 60 else goal
        await update.message.reply_text(
            f'❌ Plan cancelled: "{goal_short}"\n\n'
            "You can start a new plan anytime by sending me your marketing goal!"
        )

    async def _cmd_forget(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /forget command — clear user's stored key facts."""
        if self.key_fact_manager is None:
            await update.message.reply_text("🧠 Key facts feature is not available.")
            return

        chat_id = update.effective_chat.id
        count = await self.key_fact_manager.clear_all_facts(chat_id)

        if count > 0:
            await update.message.reply_text(
                f"🧹 Cleared {count} stored fact(s) about you.\n"
                "I'll start learning fresh from our conversations!"
            )
        else:
            await update.message.reply_text(
                "ℹ️ No stored facts to clear. I haven't learned anything about you yet!"
            )

    async def _cmd_digest(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /digest command — generate on-demand weekly content digest."""
        if self.scheduler is None:
            await update.message.reply_text("📅 Digest feature is not available.")
            return

        chat_id = update.effective_chat.id
        brand_profile = await self.brand_manager.get(chat_id)

        if brand_profile is None:
            await update.message.reply_text(
                "🏢 I need your brand profile to generate a digest.\n"
                "Use /brand to set up your profile first!"
            )
            return

        await update.message.reply_text("🔄 Generating your weekly content digest...")
        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            digest = await self.scheduler.run_weekly_digest(brand_profile)
            for chunk in split_message(digest):
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception as exc:
            logger.error("Digest generation failed for chat %d: %s", chat_id, exc)
            await update.message.reply_text("⚠️ Could not generate digest. Please try again later.")

    # -----------------------------------------------------------------------
    # Brand setup conversation
    # -----------------------------------------------------------------------

    async def _cmd_brand_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start brand setup conversation."""
        context.chat_data["brand"] = {}
        await update.message.reply_text(
            "🏢 *Brand Setup*\n\n"
            "Let's set up your brand profile for personalized responses!\n"
            "(You can /cancel anytime)\n\n"
            "What's your *brand name*?",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_NAME

    async def _brand_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collect brand name."""
        raw = update.message.text
        guard = input_guard(raw, field="brand_name")
        if guard.is_blocked:
            await update.message.reply_text(guard.content)
            return ASK_NAME
        context.chat_data["brand"]["name"] = sanitize_brand_field(guard.content, "name")
        await update.message.reply_text("Great! What *industry* are you in?", parse_mode=ParseMode.MARKDOWN)
        return ASK_INDUSTRY

    async def _brand_industry(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collect industry."""
        raw = update.message.text
        guard = input_guard(raw, field="brand_industry")
        if guard.is_blocked:
            await update.message.reply_text(guard.content)
            return ASK_INDUSTRY
        context.chat_data["brand"]["industry"] = sanitize_brand_field(guard.content, "industry")
        await update.message.reply_text("Who's your *target audience*?", parse_mode=ParseMode.MARKDOWN)
        return ASK_AUDIENCE

    async def _brand_audience(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collect target audience."""
        raw = update.message.text
        guard = input_guard(raw, field="brand_audience")
        if guard.is_blocked:
            await update.message.reply_text(guard.content)
            return ASK_AUDIENCE
        context.chat_data["brand"]["audience"] = sanitize_brand_field(guard.content, "audience")
        await update.message.reply_text(
            "What *tone of voice* do you prefer?\n"
            "(e.g., professional yet friendly, casual & fun)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_TONE

    async def _brand_tone(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collect tone of voice."""
        raw = update.message.text
        guard = input_guard(raw, field="brand_tone")
        if guard.is_blocked:
            await update.message.reply_text(guard.content)
            return ASK_TONE
        context.chat_data["brand"]["tone"] = sanitize_brand_field(guard.content, "tone")
        await update.message.reply_text("What are your *key products/services*? (comma-separated)", parse_mode=ParseMode.MARKDOWN)
        return ASK_PRODUCTS

    async def _brand_products(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collect products/services."""
        context.chat_data["brand"]["products"] = sanitize_input(update.message.text, max_len=500)
        await update.message.reply_text("Any *preferred hashtags*? (comma-separated)", parse_mode=ParseMode.MARKDOWN)
        return ASK_HASHTAGS

    async def _brand_hashtags(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collect preferred hashtags."""
        context.chat_data["brand"]["hashtags"] = sanitize_input(update.message.text, max_len=500)
        await update.message.reply_text(
            "Any *competitors* to keep an eye on? (comma-separated, or 'none')",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_COMPETITORS

    async def _brand_competitors(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collect competitors."""
        text = sanitize_input(update.message.text, max_len=500)
        if text.lower() in ("none", "tidak ada", "-"):
            text = ""
        context.chat_data["brand"]["competitors"] = text
        await update.message.reply_text(
            "Which *platforms* do you use? (e.g., Instagram, TikTok, YouTube, "
            "Email, Website — comma-separated, or 'none')",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_PLATFORM

    async def _brand_platform(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collect platform preference (social media platforms used)."""
        text = sanitize_input(update.message.text, max_len=500)
        if text.lower() in ("none", "tidak ada", "-"):
            text = ""
        context.chat_data["brand"]["platform_preference"] = text
        await update.message.reply_text(
            "What's your *monthly marketing budget*? 🤔\n"
            "• micro — under $100\n"
            "• small — $100-$500\n"
            "• medium — $500-$2,000\n"
            "• large — $2,000-$10,000\n"
            "• enterprise — $10,000+",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_BUDGET

    async def _brand_budget(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collect marketing budget range tier."""
        raw = update.message.text.strip().lower()
        valid_budgets = ("micro", "small", "medium", "large", "enterprise")
        # Allow free-form input; normalize to a known tier if possible.
        budget = next((b for b in valid_budgets if b in raw), "")
        if not budget:
            await update.message.reply_text(
                "Please pick one of: *micro, small, medium, large, enterprise*.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ASK_BUDGET
        context.chat_data["brand"]["budget_range"] = budget
        await update.message.reply_text(
            "What *stage* is your business at? 🚀\n"
            "• idea — Just an idea\n"
            "• launch — Just launched\n"
            "• growth — Growing steadily\n"
            "• scale — Scaling up\n"
            "• mature — Established",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_STAGE

    async def _brand_stage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Collect business stage and show the confirmation summary."""
        raw = update.message.text.strip().lower()
        valid_stages = ("idea", "launch", "growth", "scale", "mature")
        stage = next((s for s in valid_stages if s in raw), "")
        if not stage:
            await update.message.reply_text(
                "Please pick one of: *idea, launch, growth, scale, mature*.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ASK_STAGE
        context.chat_data["brand"]["business_stage"] = stage

        # Show summary for confirmation
        brand = context.chat_data["brand"]
        summary = (
            "📋 *Brand Profile Summary*\n\n"
            f"• *Name:* {brand.get('name', '—')}\n"
            f"• *Industry:* {brand.get('industry', '—')}\n"
            f"• *Platforms:* {brand.get('platform_preference', '—') or 'None'}\n"
            f"• *Budget:* {brand.get('budget_range', '—')}\n"
            f"• *Stage:* {brand.get('business_stage', '—')}\n"
            f"• *Audience:* {brand.get('audience', '—')}\n"
            f"• *Tone:* {brand.get('tone', '—')}\n"
            f"• *Products:* {brand.get('products', '—')}\n"
            f"• *Hashtags:* {brand.get('hashtags', '—')}\n"
            f"• *Competitors:* {brand.get('competitors', '—') or 'None'}\n\n"
            "Type *yes* to save or *redo* to start over."
        )
        await update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN)
        return CONFIRM

    async def _brand_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirm and save brand profile."""
        text = update.message.text.strip().lower()
        chat_id = update.effective_chat.id

        if text in ("yes", "ya", "y", "simpan", "save"):
            brand_data = context.chat_data.get("brand", {})
            profile = BrandProfile(
                chat_id=chat_id,
                name=brand_data.get("name", "Unknown"),
                industry=brand_data.get("industry", ""),
                audience=brand_data.get("audience", ""),
                tone=brand_data.get("tone", ""),
                products=brand_data.get("products", ""),
                hashtags=brand_data.get("hashtags", ""),
                competitors=brand_data.get("competitors", ""),
                language_pref=self.settings.bot_language,
                platform_preference=brand_data.get("platform_preference", ""),
                budget_range=brand_data.get("budget_range", ""),
                business_stage=brand_data.get("business_stage", ""),
            )

            try:
                await self.brand_manager.create_or_update(profile)
                await update.message.reply_text(
                    "✅ *Brand profile saved!*\n\n"
                    "Your responses will now be personalized with your brand context. "
                    "Use /brand again anytime to update your profile.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as exc:
                logger.error("Failed to save brand profile: %s", exc)
                await update.message.reply_text("⚠️ Failed to save brand profile. Please try again with /brand.")
        else:
            context.chat_data["brand"] = {}
            await update.message.reply_text(
                "🔄 Starting over!\n\nWhat's your *brand name*?",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ASK_NAME

        return ConversationHandler.END

    # -----------------------------------------------------------------------
    # Message handler (main router flow)
    # -----------------------------------------------------------------------

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages — route through intent classifier.

        Shows typing indicator, classifies intent, dispatches to pillar,
        saves context, and sends the response.
        """
        if not update.message or not update.message.text:
            return

        chat_id = update.effective_chat.id
        user_message = sanitize_input(update.message.text)

        if not user_message:
            return

        # Security: check for prompt injection attempts
        guard = input_guard(user_message, field="message")
        if guard.is_blocked:
            logger.warning("Blocked message from chat %d: threat=%s", chat_id, guard.threat_type)
            # Track injection attempts per chat and escalate if repeated
            if chat_id not in self._rate_limits:
                self._rate_limits[chat_id] = RateLimitState()
            should_block = self._rate_limits[chat_id].record_injection()
            if should_block:
                await update.message.reply_text(
                    "🚫 Repeated policy violations detected. Your messages are being ignored. "
                    "Take a break and try again later."
                )
            else:
                await update.message.reply_text(guard.content)
            return

        # Show typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            # Get conversation context
            ctx = await self.session_manager.get_context(chat_id)

            # Get brand profile
            brand_profile = await self.brand_manager.get(chat_id)

            # Get key facts for personalization
            key_facts_text = ""
            if self.key_fact_manager:
                key_facts_text = await self.key_fact_manager.get_facts_context(chat_id)

            # Classify intent
            result = await self.router.classify(user_message, ctx, chat_id=chat_id)
            logger.info(
                "Router: chat=%d pillar=%s action=%s conf=%.2f",
                chat_id, result.pillar, result.action, result.confidence,
            )

            # Throttle feedback — don't silently ignore rapid messages
            if result.is_throttled:
                await update.message.reply_text("⏳ Slow down a bit! Try again in a moment.")
                return

            # Send a placeholder that we'll progressively edit as tokens stream in.
            # For general (chitchat/help/brand) intents the response is short, so
            # we fall back to the non-streaming _handle_general path and do a
            # single edit. For pillar intents we stream via handle_stream().
            placeholder = await update.message.reply_text(
                "⏳ _Thinking..._", parse_mode=ParseMode.MARKDOWN
            )

            pillar = None
            sent_messages: list = [placeholder]  # track messages we may attach buttons to

            # --- Phase 1: Try orchestrator for multi-step workflows ---
            orchestrated = False
            response = ""  # Will be set by orchestrator or pillar dispatch
            if not result.is_general and self._orchestrator:
                try:
                    async def _workflow_progress(msg: str) -> None:
                        try:
                            await placeholder.edit_text(msg)
                        except Exception:
                            pass

                    response_text, was_workflow = await self._orchestrator.execute(
                        user_message=user_message,
                        pillar=result.pillar,
                        action=result.action,
                        context=ctx,
                        brand_profile=brand_profile,
                        key_facts=key_facts_text,
                        on_progress=_workflow_progress,
                        confidence=result.confidence,
                        chat_id=chat_id,
                    )
                    if was_workflow:
                        orchestrated = True
                        response = response_text
                        chunks = split_message(response)
                        if chunks:
                            try:
                                await placeholder.edit_text(chunks[0])
                            except Exception as exc:
                                logger.warning("edit_text failed for workflow response: %s", exc)
                            for extra in chunks[1:]:
                                sent_messages.append(await update.message.reply_text(extra))
                except Exception as exc:
                    logger.warning("Orchestrator failed, falling back to single pillar: %s", exc)

            # --- Normal dispatch (single pillar or general) ---
            if not orchestrated and result.is_general:
                response = await self._handle_general(
                    user_message, result, ctx, brand_profile,
                    key_facts=key_facts_text,
                )
                # Edit the placeholder with the final (possibly long) response.
                chunks = split_message(response)
                if chunks:
                    try:
                        await placeholder.edit_text(chunks[0])
                    except Exception as exc:
                        logger.warning("edit_text failed for general response: %s", exc)
                    for extra in chunks[1:]:
                        sent_messages.append(
                            await update.message.reply_text(extra)
                        )
            elif not orchestrated:
                # Dispatch to pillar — stream tokens into the placeholder.
                pillar = self._pillars.get(result.pillar)
                if pillar and hasattr(pillar, "handle_stream"):
                    response = await self._stream_pillar_response(
                        update, placeholder, sent_messages, pillar,
                        user_message=user_message,
                        action=result.action,
                        context=ctx,
                        brand_profile=brand_profile,
                        key_facts=key_facts_text,
                    )
                elif pillar:
                    # Fallback: pillar has no handle_stream — use non-streaming handle.
                    response = await pillar.handle(
                        user_message=user_message,
                        action=result.action,
                        context=ctx,
                        brand_profile=brand_profile,
                        key_facts=key_facts_text,
                    )
                    chunks = split_message(response)
                    if chunks:
                        try:
                            await placeholder.edit_text(chunks[0])
                        except Exception as exc:
                            logger.warning("edit_text failed for pillar response: %s", exc)
                        for extra in chunks[1:]:
                            sent_messages.append(
                                await update.message.reply_text(extra)
                            )
                else:
                    response = "🤔 I'm not sure how to help with that. Try asking about content, strategy, research, or analytics!"
                    try:
                        await placeholder.edit_text(response)
                    except Exception as exc:
                        logger.warning("edit_text failed for fallback response: %s", exc)

            # Security: check output for prompt leaks
            out_guard = output_guard(response)
            if not out_guard.is_safe:
                logger.warning("Output guard triggered for chat %d: %s", chat_id, out_guard.threat_type)
                response = out_guard.content
                # Overwrite the last sent message with the sanitized content.
                last_msg = sent_messages[-1] if sent_messages else placeholder
                try:
                    await last_msg.edit_text(response)
                except Exception as exc:
                    logger.warning("edit_text failed for output-guarded response: %s", exc)

            # Phase 3: Self-reflection for content/strategy pillars
            reflection_log: dict = {"iterations": 0, "skipped": True}
            if (
                not result.is_general
                and not orchestrated
                and self.reflection_engine is not None
                and pillar is not None
                and response
            ):
                try:
                    brand_ctx = ""
                    if brand_profile:
                        brand_ctx = build_brand_context(
                            name=brand_profile.name,
                            industry=brand_profile.industry,
                            audience=brand_profile.audience,
                            tone=brand_profile.tone,
                            products=brand_profile.products,
                            hashtags=brand_profile.hashtags,
                            competitors=brand_profile.competitors,
                            platform_preference=brand_profile.platform_preference,
                            budget_range=brand_profile.budget_range,
                            business_stage=brand_profile.business_stage,
                        )
                    refined, reflection_log = await self.reflection_engine.reflect_and_refine(
                        pillar=result.pillar,
                        user_message=user_message,
                        initial_output=response,
                        brand_context=brand_ctx,
                    )
                    if refined != response and reflection_log.get("improved"):
                        response = refined
                        # Append reflection quality indicator
                        initial = reflection_log.get("initial_score", 0)
                        final = reflection_log.get("final_score", 0)
                        if initial and final and final > initial:
                            response += f"\n\n_✨ Auto-optimized (quality: {initial:.1f} → {final:.1f})_"
                        # Update the displayed message with the refined output
                        chunks = split_message(response)
                        if chunks and sent_messages:
                            try:
                                await sent_messages[0].edit_text(chunks[0])
                            except Exception:
                                pass
                            # Update overflow messages if needed
                            for idx, extra in enumerate(chunks[1:]):
                                msg_idx = idx + 1
                                if msg_idx < len(sent_messages):
                                    try:
                                        await sent_messages[msg_idx].edit_text(extra)
                                    except Exception:
                                        pass
                                else:
                                    sent_messages.append(
                                        await update.message.reply_text(extra)
                                    )
                        logger.info(
                            "Reflection improved %s pillar for chat %d (score: %.1f -> %.1f)",
                            result.pillar, chat_id,
                            reflection_log.get("initial_score", 0),
                            reflection_log.get("final_score", 0),
                        )
                except Exception as exc:
                    logger.warning("Reflection engine failed for chat %d: %s", chat_id, exc)

            # Save to session context
            await self.session_manager.add_message(chat_id, "user", user_message)
            await self.session_manager.add_message(chat_id, "assistant", response)

            # Background key fact extraction every 10 messages
            if self.key_fact_manager and self.llm_client:
                try:
                    msg_count = await self.session_manager.get_message_count(chat_id)
                    if msg_count > 0 and msg_count % 10 == 0:
                        asyncio.create_task(
                            self.key_fact_manager.extract_facts_from_conversation(
                                chat_id, self.llm_client, ctx
                            )
                        )
                except Exception as exc:
                    logger.warning("Key fact extraction trigger failed for chat %d: %s", chat_id, exc)

            # Determine whether to attach feedback buttons.
            # Only pillar responses (content/strategy/research/analytics) get
            # feedback buttons — general chitchat/help/brand do not.
            rstore = self.response_store
            attach_feedback = (
                rstore is not None
                and not result.is_general
                and pillar is not None
            )

            # Store the response for feedback/regenerate, if enabled
            log_id: int | None = None
            if attach_feedback and rstore is not None:
                try:
                    log_id = await rstore.store(
                        chat_id=chat_id,
                        pillar=result.pillar,
                        action=result.action,
                        user_request=user_message,
                        response_text=response,
                    )
                except Exception as exc:
                    logger.warning("Failed to store response for feedback: %s", exc)
                    log_id = None

            # Attach the feedback keyboard to the LAST message we sent. During
            # streaming the last message is the final edited placeholder (or the
            # last overflow chunk); for the non-streaming path it's the last
            # split chunk. We edit it to attach the inline keyboard.
            if attach_feedback and log_id is not None and sent_messages:
                last_msg = sent_messages[-1]
                try:
                    await last_msg.edit_text(
                        split_message(response)[-1] if len(sent_messages) > 1 else response,
                        reply_markup=feedback_keyboard(log_id),
                    )
                except Exception as exc:
                    logger.warning("Failed to attach feedback keyboard: %s", exc)

        except Exception as exc:
            logger.error("Error handling message from chat %d: %s", chat_id, exc, exc_info=True)
            await update.message.reply_text(
                "⚠️ Sorry, something went wrong processing your message. Please try again!"
            )

    async def _stream_pillar_response(
        self,
        update: Update,
        placeholder: Any,
        sent_messages: list,
        pillar: Any,
        *,
        user_message: str,
        action: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None,
        key_facts: str = "",
    ) -> str:
        """Stream a pillar response into the placeholder message.

        Accumulates chunks from ``pillar.handle_stream()`` and progressively
        edits the placeholder. Throttles edits to roughly one per second (or
        every ~200 chars). If the buffer exceeds 4000 chars (Telegram's 4096
        limit), the current buffer is flushed as a new message and a fresh
        buffer starts. On completion the final buffer is edited into the last
        message. If an LLM error occurs mid-stream, the placeholder is edited
        with the error text.

        Args:
            update: The Telegram Update (used to send overflow messages).
            placeholder: The initial "⏳ Thinking..." message to edit.
            sent_messages: List tracking all messages sent (appended in place);
                the last entry is where the feedback keyboard will land.
            pillar: The pillar instance to stream from.
            user_message: The user's message text.
            action: The classified action.
            context: Conversation context.
            brand_profile: Optional brand profile.
            key_facts: Key facts context for personalization.

        Returns:
            The full accumulated response text.
        """
        buffer = ""
        last_edit = time.monotonic()
        current_msg = placeholder
        TELEGRAM_LIMIT = 4000
        EDIT_INTERVAL = 1.0
        EDIT_CHAR_INTERVAL = 200

        async for chunk in pillar.handle_stream(
            user_message=user_message,
            action=action,
            context=context,
            brand_profile=brand_profile,
            key_facts=key_facts,
        ):
            buffer += chunk
            now = time.monotonic()
            # Flush if we're about to exceed Telegram's message limit.
            if len(buffer) >= TELEGRAM_LIMIT:
                try:
                    await current_msg.edit_text(buffer[:TELEGRAM_LIMIT])
                except Exception as exc:
                    logger.warning("edit_text overflow flush failed: %s", exc)
                overflow = buffer[TELEGRAM_LIMIT:]
                current_msg = await update.message.reply_text(overflow)
                sent_messages.append(current_msg)
                buffer = overflow
                last_edit = now
                continue
            # Throttle edits: at most ~1/sec or every ~200 chars.
            if (now - last_edit >= EDIT_INTERVAL) or (len(buffer) % EDIT_CHAR_INTERVAL < len(chunk)):
                try:
                    await current_msg.edit_text(buffer)
                except Exception as exc:
                    # "message is not modified" is harmless during rapid edits.
                    logger.debug("progressive edit_text skipped: %s", exc)
                last_edit = now

        # Final edit with the complete buffer for the current message.
        if buffer:
            try:
                await current_msg.edit_text(buffer)
            except Exception as exc:
                logger.debug("final edit_text skipped: %s", exc)

        return buffer

    async def _handle_general(
        self,
        user_message: str,
        result: Any,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None,
        key_facts: str = "",
    ) -> str:
        """Handle general (non-pillar) intents.

        For chitchat and unclear messages, uses the LLM to generate a natural
        conversational response. For help and brand, returns static text.

        Args:
            user_message: User's message.
            result: Router result.
            context: Conversation context.
            brand_profile: Optional brand profile.
            key_facts: Key facts context for personalization.

        Returns:
            Response text.
        """
        action = result.action

        if action == "help":
            return (
                f"🤖 I'm *{self.settings.bot_name}* — your AI Digital Marketing Assistant!\n\n"
                f"I help with 4 pillars:\n"
                f"✍️ *Content* — Captions, hooks, hashtags, CTAs\n"
                f"📋 *Strategy* — Plans, funnels, budgets, launches\n"
                f"🔍 *Research* — Trends, competitors, audience, keywords\n"
                f"📊 *Analytics* — Reports, KPIs, ROI, improvements\n\n"
                f"Just ask naturally! For example:\n"
                f"• \"Write me an Instagram caption for a new product launch\"\n"
                f"• \"Create a 3-month marketing plan for my coffee shop\"\n"
                f"• \"What are the latest social media trends?\"\n"
                f"• \"How do I calculate marketing ROI?\"\n\n"
                f"Use /brand to personalize responses for your brand!"
            )
        elif action == "brand":
            return "Use the /brand command to set up or update your brand profile! Just type: /brand"
        elif action in ("chitchat", "unclear"):
            # Use LLM for natural conversation
            brand_ctx = ""
            if brand_profile:
                brand_ctx = build_brand_context(
                    name=brand_profile.name,
                    industry=brand_profile.industry,
                    audience=brand_profile.audience,
                    tone=brand_profile.tone,
                    products=brand_profile.products,
                    hashtags=brand_profile.hashtags,
                    competitors=brand_profile.competitors,
                    platform_preference=brand_profile.platform_preference,
                    budget_range=brand_profile.budget_range,
                    business_stage=brand_profile.business_stage,
                )

            messages = build_general_messages(
                user_message=user_message,
                context=context,
                language=self.settings.bot_language,
                bot_name=self.settings.bot_name,
                brand_context=brand_ctx or None,
                key_facts=key_facts,
            )

            try:
                response = await self.llm_client.chat(messages)
                return response.strip()
            except Exception as exc:
                logger.error("LLM error in general handler: %s", exc)
                return (
                    "👋 Hey! I'm here to help with your marketing — "
                    "content, strategy, research, and analytics. What would you like to work on?"
                )
        else:
            return (
                "🤔 I'm not quite sure what you're looking for. "
                "I can help with:\n"
                "• Writing content (captions, hooks, hashtags)\n"
                "• Marketing strategy and planning\n"
                "• Market research and trends\n"
                "• Analytics and performance reports\n\n"
                "Try rephrasing your question or ask me something specific!"
            )

    # -----------------------------------------------------------------------
    # Photo / image handler (vision capability)
    # -----------------------------------------------------------------------

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming photo messages — download, encode, and analyze via vision LLM.

        Downloads the largest available photo size from Telegram, encodes it
        as base64 (resizing to max 1024×1024 via PIL), then sends it to the
        vision-capable LLM with the image analysis system prompt.  If the
        user provides a caption, it is used as the user instruction; if the
        caption contains a pillar keyword (e.g. "analytics"), the image is
        routed to that pillar's ``handle_image()`` instead.

        The response is streamed into a placeholder message using the same
        progressive-edit pattern as text messages, and feedback buttons are
        attached if a response store is configured.
        """
        if not update.message or not update.message.photo:
            return

        chat_id = update.effective_chat.id
        caption = update.message.caption or ""
        user_message = sanitize_input(caption) if caption else ""

        # Show typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)

        import os
        import tempfile

        tmp_path: str | None = None
        try:
            # Pick the largest photo size (last in the list)
            photo = update.message.photo[-1]

            # Download the file
            file = await context.bot.get_file(photo.file_id)
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="dm_photo_")
            os.close(tmp_fd)
            await file.download_to_drive(tmp_path)

            # Encode image (resize + base64)
            image_base64, image_mime = encode_image_file(tmp_path)

            # Send placeholder that we'll progressively edit
            placeholder = await update.message.reply_text(
                "⏳ _Analyzing image..._", parse_mode=ParseMode.MARKDOWN
            )
            sent_messages: list = [placeholder]

            # Determine routing: if caption mentions a pillar keyword,
            # delegate to that pillar's handle_image(); otherwise use the
            # general image analysis prompt directly.
            pillar = self._match_pillar_from_caption(user_message)

            # Build conversation context and brand profile
            ctx = await self.session_manager.get_context(chat_id)
            brand_profile = await self.brand_manager.get(chat_id)

            # Determine the vision model to use
            vision_model = getattr(self.settings, "vision_model_effective", None)

            if pillar is not None:
                # Route to pillar's handle_image()
                response = await pillar.handle_image(
                    user_message=user_message or "Analyze this image from a marketing perspective.",
                    image_base64=image_base64,
                    image_mime_type=image_mime,
                    action="analyze",
                    context=ctx,
                    brand_profile=brand_profile,
                )
                # Edit placeholder with the response (may need splitting)
                chunks = split_message(response)
                if chunks:
                    try:
                        await placeholder.edit_text(chunks[0])
                    except Exception as exc:
                        logger.warning("edit_text failed for image response: %s", exc)
                    for extra in chunks[1:]:
                        sent_messages.append(
                            await update.message.reply_text(extra)
                        )
            else:
                # General image analysis — stream via chat_with_image_stream
                analysis_prompt = user_message or "Analyze this image from a marketing perspective."
                messages: list[dict[str, str]] = [
                    {"role": "system", "content": IMAGE_ANALYSIS_SYSTEM_PROMPT},
                ]
                # Include conversation context
                for msg in ctx[-8:]:
                    messages.append(msg)
                messages.append({"role": "user", "content": analysis_prompt})

                response = await self._stream_image_response(
                    update, placeholder, sent_messages,
                    messages=messages,
                    image_base64=image_base64,
                    image_mime=image_mime,
                    vision_model=vision_model,
                )

            # Security: check output for prompt leaks
            out_guard = output_guard(response)
            if not out_guard.is_safe:
                logger.warning("Output guard triggered for chat %d: %s", chat_id, out_guard.threat_type)
                response = out_guard.content
                last_msg = sent_messages[-1] if sent_messages else placeholder
                try:
                    await last_msg.edit_text(response)
                except Exception as exc:
                    logger.warning("edit_text failed for output-guarded image response: %s", exc)

            # Save to session context
            display_caption = user_message or "[Image shared for analysis]"
            await self.session_manager.add_message(chat_id, "user", display_caption)
            await self.session_manager.add_message(chat_id, "assistant", response)

            # Attach feedback buttons if response store is configured
            rstore = self.response_store
            if rstore is not None and sent_messages:
                try:
                    log_id = await rstore.store(
                        chat_id=chat_id,
                        pillar="image" if pillar is None else pillar.PILLAR_NAME,
                        action="analyze",
                        user_request=display_caption,
                        response_text=response,
                    )
                    if log_id is not None:
                        last_msg = sent_messages[-1]
                        await last_msg.edit_text(
                            split_message(response)[-1] if len(sent_messages) > 1 else response,
                            reply_markup=feedback_keyboard(log_id),
                        )
                except Exception as exc:
                    logger.warning("Failed to store/attach image feedback: %s", exc)

        except Exception as exc:
            logger.error("Error handling photo from chat %d: %s", chat_id, exc, exc_info=True)
            await update.message.reply_text(
                "⚠️ Sorry, I couldn't analyze that image. Please try again or send a different photo!"
            )
        finally:
            # Clean up temp file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    logger.debug("Failed to clean up temp file: %s", tmp_path)

    def _match_pillar_from_caption(self, caption: str) -> Any:
        """Check if a photo caption contains a pillar keyword for routing.

        Returns the matching pillar instance or None for general analysis.

        Args:
            caption: The user's photo caption (may be empty).

        Returns:
            A BasePillar instance if a keyword matches, else None.
        """
        if not caption:
            return None
        lower = caption.lower()
        # Keyword → pillar mapping
        keyword_map = {
            "analytics": self.analytics_pillar,
            "metrics": self.analytics_pillar,
            "dashboard": self.analytics_pillar,
            "report": self.analytics_pillar,
            "kpi": self.analytics_pillar,
            "research": self.research_pillar,
            "competitor": self.research_pillar,
            "compet": self.research_pillar,
            "content": self.content_pillar,
            "copy": self.content_pillar,
            "caption": self.content_pillar,
            "strategy": self.strategy_pillar,
            "plan": self.strategy_pillar,
        }
        for keyword, pillar in keyword_map.items():
            if keyword in lower:
                return pillar
        return None

    async def _stream_image_response(
        self,
        update: Update,
        placeholder: Any,
        sent_messages: list,
        *,
        messages: list[dict[str, str]],
        image_base64: str,
        image_mime: str,
        vision_model: str | None,
    ) -> str:
        """Stream a vision LLM response into the placeholder message.

        Uses :meth:`LLMClient.chat_with_image_stream` for real-time token
        delivery with the same progressive-edit pattern as
        :meth:`_stream_pillar_response`.

        Args:
            update: The Telegram Update.
            placeholder: The initial "⏳ Analyzing image..." message.
            sent_messages: List tracking all messages sent (appended in place).
            messages: The message list for the LLM call.
            image_base64: Base64-encoded image data.
            image_mime: MIME type of the image.
            vision_model: Model name for vision, or None to use default.

        Returns:
            The full accumulated response text.
        """
        buffer = ""
        last_edit = time.monotonic()
        current_msg = placeholder
        TELEGRAM_LIMIT = 4000
        EDIT_INTERVAL = 1.0
        EDIT_CHAR_INTERVAL = 200

        try:
            async for chunk in self.llm_client.chat_with_image_stream(
                messages,
                image_base64=image_base64,
                image_mime_type=image_mime,
                max_tokens=2048,
                model=vision_model,
            ):
                buffer += chunk
                now = time.monotonic()
                # Flush if we're about to exceed Telegram's message limit.
                if len(buffer) >= TELEGRAM_LIMIT:
                    try:
                        await current_msg.edit_text(buffer[:TELEGRAM_LIMIT])
                    except Exception as exc:
                        logger.warning("edit_text overflow flush failed: %s", exc)
                    overflow = buffer[TELEGRAM_LIMIT:]
                    current_msg = await update.message.reply_text(overflow)
                    sent_messages.append(current_msg)
                    buffer = overflow
                    last_edit = now
                    continue
                # Throttle edits: at most ~1/sec or every ~200 chars.
                if (now - last_edit >= EDIT_INTERVAL) or (len(buffer) % EDIT_CHAR_INTERVAL < len(chunk)):
                    try:
                        await current_msg.edit_text(buffer)
                    except Exception as exc:
                        logger.debug("progressive edit_text skipped: %s", exc)
                    last_edit = now
        except Exception as exc:
            logger.error("Vision stream error: %s", exc)
            if not buffer:
                buffer = (
                    "⚠️ Sorry, I encountered an error analyzing the image. "
                    "Please try again in a moment."
                )

        # Final edit with the complete buffer.
        if buffer:
            try:
                await current_msg.edit_text(buffer)
            except Exception as exc:
                logger.debug("final edit_text skipped: %s", exc)

        return buffer

    # -----------------------------------------------------------------------
    # Feedback button callback handler
    # -----------------------------------------------------------------------

    async def _handle_feedback_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline feedback button callbacks (👍/👎/🔄).

        Callback data formats (all prefixed with ``fb:``):

        * ``fb:up:{log_id}``    — positive feedback
        * ``fb:down:{log_id}``  — negative feedback
        * ``fb:regen:{log_id}`` — regenerate the response

        For 👍/👎 the feedback row is updated, the keyboard is removed, and a
        brief acknowledgement is shown. For 🔄 the original request is fetched
        from the store, the pillar is re-invoked, and the message is edited with
        a fresh response plus a brand-new feedback keyboard.
        """
        query = update.callback_query
        if query is None:
            # Defensive: CallbackQueryHandler guarantees a callback_query,
            # but guard regardless so we never raise AttributeError.
            return
        await query.answer()

        data = query.data or ""
        rstore = self.response_store
        if rstore is None:
            # Feedback store not configured — nothing we can do
            await query.edit_message_text(
                "⚠️ Feedback is not available right now.",
                reply_markup=None,
            )
            return

        # Parse callback data: fb:<action>:<log_id>
        parts = data.split(":")
        if len(parts) != 3:
            logger.warning("Malformed feedback callback data: %s", data)
            return
        action, log_id_str = parts[1], parts[2]
        try:
            log_id = int(log_id_str)
        except ValueError:
            logger.warning("Invalid log_id in feedback callback: %s", log_id_str)
            return

        if action in ("up", "down"):
            await self._handle_feedback_rating(query, rstore, log_id, action)
        elif action == "regen":
            await self._handle_feedback_regen(query, rstore, log_id)
        else:
            logger.warning("Unknown feedback action: %s", action)

    async def _handle_feedback_rating(
        self,
        query: Any,
        rstore: ResponseStore,
        log_id: int,
        action: str,
    ) -> None:
        """Process a 👍/👎 rating — update DB, remove keyboard, thank the user."""
        try:
            await rstore.update_feedback(log_id, action)
        except Exception as exc:
            logger.error("Failed to record feedback %s for log %d: %s", action, log_id, exc)

        # Remove the inline keyboard and show a brief thanks
        emoji = "👍" if action == "up" else "👎"
        thanks = "Thanks for the feedback! 👍" if action == "up" else "Thanks for the feedback — I'll do better next time. 👎"
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as exc:
            logger.debug("Could not remove feedback keyboard: %s", exc)
        try:
            await query.message.reply_text(thanks)
        except Exception as exc:
            logger.debug("Could not send feedback thanks: %s", exc)
        logger.info("Feedback %s recorded for log_id=%d", emoji, log_id)

    async def _handle_feedback_regen(
        self,
        query: Any,
        rstore: ResponseStore,
        log_id: int,
    ) -> None:
        """Process a 🔄 regenerate — re-run the pillar and edit the message."""
        record = await rstore.get(log_id)
        if record is None:
            await query.edit_message_text(
                "⚠️ Sorry, I couldn't find the original response to regenerate.",
                reply_markup=None,
            )
            return

        pillar = self._pillars.get(record.pillar)
        if pillar is None:
            await query.edit_message_text(
                "⚠️ Sorry, that pillar is no longer available.",
                reply_markup=None,
            )
            return

        # Show typing indicator while regenerating
        try:
            await query.message.chat.send_action(ChatAction.TYPING)
        except Exception:
            pass

        # Re-invoke the pillar with the original request.
        # Brand profile is fetched fresh so regen respects any profile updates.
        try:
            brand_profile = await self.brand_manager.get(record.chat_id)
            new_response = await pillar.handle(
                user_message=record.user_request,
                action=record.action,
                context=[],  # fresh context for a clean variation
                brand_profile=brand_profile,
            )
        except Exception as exc:
            logger.error("Regeneration failed for log %d: %s", log_id, exc)
            await query.message.reply_text(
                "⚠️ Sorry, I couldn't regenerate that response. Please try again."
            )
            return

        # Security: check output for prompt leaks
        out_guard = output_guard(new_response)
        if not out_guard.is_safe:
            logger.warning("Output guard triggered during regen for log %d: %s", log_id, out_guard.threat_type)
            new_response = out_guard.content

        # Persist the regenerated response and bump the regen counter
        try:
            new_log_id = await rstore.store(
                chat_id=record.chat_id,
                pillar=record.pillar,
                action=record.action,
                user_request=record.user_request,
                response_text=new_response,
                regen_count=record.regen_count + 1,
            )
        except Exception as exc:
            logger.warning("Failed to store regenerated response: %s", exc)
            new_log_id = log_id  # fall back to old keyboard

        # Edit the original message with the new response + fresh keyboard.
        # If the response is very long, edit_text may fail (Telegram limit),
        # so fall back to sending a new message.
        reply_markup = feedback_keyboard(new_log_id) if new_log_id else None
        prefix = "🔄 *Regenerated response:*\n\n"
        edited_text = prefix + new_response
        try:
            await query.edit_message_text(
                edited_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as exc:
            logger.warning("edit_message_text failed during regen, sending new message: %s", exc)
            # Fall back: send as a new message (split if needed)
            for idx, chunk in enumerate(split_message(edited_text)):
                is_last = idx == len(split_message(edited_text)) - 1
                await query.message.reply_text(
                    chunk,
                    reply_markup=reply_markup if is_last else None,
                )
        logger.info("Regenerated response for log_id=%d -> new_log_id=%s", log_id, new_log_id)
