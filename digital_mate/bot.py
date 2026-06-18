"""Telegram bot setup: Application, handlers, and command callbacks.

Registers all command handlers, the conversation handler for brand setup,
and the message handler that routes messages through the IntentRouter.
"""

from __future__ import annotations

import logging
from typing import Any

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from digital_mate.config import Settings
from digital_mate.llm.client import LLMClient
from digital_mate.router import IntentRouter
from digital_mate.pillars.content import ContentPillar
from digital_mate.pillars.strategy import StrategyPillar
from digital_mate.pillars.research import ResearchPillar
from digital_mate.pillars.analytics import AnalyticsPillar
from digital_mate.memory.session import SessionManager
from digital_mate.memory.brand_profile import BrandProfileManager, BrandProfile
from digital_mate.integrations.notion_client import NotionService
from digital_mate.integrations.search import SearchService
from digital_mate.utils.formatting import split_message, format_calendar_week
from digital_mate.utils.validators import sanitize_input
from digital_mate.utils.security import input_guard, output_guard, sanitize_brand_field, GuardResult

logger = logging.getLogger(__name__)

# Brand setup conversation states
ASK_NAME, ASK_INDUSTRY, ASK_AUDIENCE, ASK_TONE, ASK_PRODUCTS, ASK_HASHTAGS, ASK_COMPETITORS, CONFIRM = range(8)


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
        """
        self.settings = settings
        self.llm_client = llm_client
        self.router = router
        self.session_manager = session_manager
        self.brand_manager = brand_manager
        self.notion_service = notion_service
        self.search_service = search_service

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

        self.app: Application | None = None

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
        self.app.add_handler(CommandHandler("cancel", self._cmd_cancel))

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

    async def _cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /cancel command — cancel current operation."""
        await update.message.reply_text("❌ Operation cancelled. You can start fresh anytime!")
        return ConversationHandler.END

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

        # Show summary for confirmation
        brand = context.chat_data["brand"]
        summary = (
            "📋 *Brand Profile Summary*\n\n"
            f"• *Name:* {brand.get('name', '—')}\n"
            f"• *Industry:* {brand.get('industry', '—')}\n"
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
            await update.message.reply_text(guard.content)
            return

        # Show typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            # Get conversation context
            ctx = await self.session_manager.get_context(chat_id)

            # Get brand profile
            brand_profile = await self.brand_manager.get(chat_id)

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

            # Handle general intents directly
            if result.is_general:
                response = await self._handle_general(user_message, result, ctx, brand_profile)
            else:
                # Dispatch to pillar
                pillar = self._pillars.get(result.pillar)
                if pillar:
                    response = await pillar.handle(
                        user_message=user_message,
                        action=result.action,
                        context=ctx,
                        brand_profile=brand_profile,
                    )
                else:
                    response = "🤔 I'm not sure how to help with that. Try asking about content, strategy, research, or analytics!"

            # Security: check output for prompt leaks
            out_guard = output_guard(response)
            if not out_guard.is_safe:
                logger.warning("Output guard triggered for chat %d: %s", chat_id, out_guard.threat_type)
                response = out_guard.content

            # Save to session context
            await self.session_manager.add_message(chat_id, "user", user_message)
            await self.session_manager.add_message(chat_id, "assistant", response)

            # Send response (split if too long)
            for chunk in split_message(response):
                await update.message.reply_text(chunk)

        except Exception as exc:
            logger.error("Error handling message from chat %d: %s", chat_id, exc, exc_info=True)
            await update.message.reply_text(
                "⚠️ Sorry, something went wrong processing your message. Please try again!"
            )

    async def _handle_general(
        self,
        user_message: str,
        result: Any,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None,
    ) -> str:
        """Handle general (non-pillar) intents.

        Args:
            user_message: User's message.
            result: Router result.
            context: Conversation context.
            brand_profile: Optional brand profile.

        Returns:
            Response text.
        """
        action = result.action

        if action == "chitchat":
            return (
                f"👋 Hey there! I'm {self.settings.bot_name}, your AI Digital Marketing Assistant.\n\n"
                f"I can help with content creation, marketing strategy, research, and analytics. "
                f"What would you like to work on?"
            )
        elif action == "help":
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
