"""Entry point for Digital Mate: python -m digital_mate.

Initializes all services, builds the Telegram bot, and starts polling.
Supports --init-db flag for database-only initialization and --help.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from digital_mate import __version__


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        prog="digital-mate",
        description="Digital Mate — AI Digital Marketing Assistant Telegram Bot",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Initialize database tables and exit (don't start bot).",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO).",
    )
    return parser.parse_args()


def setup_logging(level: str = "INFO") -> None:
    """Configure application logging.

    Args:
        level: Logging level string (DEBUG, INFO, WARNING, ERROR).
    """
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


async def _init_database(db_path: str) -> None:
    """Initialize the database and print confirmation.

    Args:
        db_path: Path to the database file.
    """
    from digital_mate.memory.database import init_db
    conn = await init_db(db_path)
    await conn.close()
    print(f"✅ Database initialized at: {db_path}")


async def _run_bot() -> None:
    """Initialize all services and run the Telegram bot."""
    from digital_mate.config import get_settings
    from digital_mate.llm.client import LLMClient
    from digital_mate.router import IntentRouter
    from digital_mate.memory.database import init_db
    from digital_mate.memory.session import SessionManager
    from digital_mate.memory.brand_profile import BrandProfileManager
    from digital_mate.integrations.notion_client import NotionService
    from digital_mate.integrations.search import SearchService
    from digital_mate.bot import DigitalMateBot

    logger = logging.getLogger(__name__)

    # 1. Load config
    settings = get_settings()
    logger.info("Configuration loaded: bot=%s, model=%s", settings.bot_name, settings.llm_model)

    # 2. Init database
    db = await init_db(settings.db_path)
    logger.info("Database initialized")

    # 3. Init services
    llm_client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        router_model=settings.router_model_effective,
    )

    router = IntentRouter(
        llm_client=llm_client,
        language=settings.bot_language,
        bot_name=settings.bot_name,
    )

    session_manager = SessionManager(db, max_turns=settings.max_conversation_turns)
    brand_manager = BrandProfileManager(db)

    # Optional: Notion integration
    notion_service: NotionService | None = None
    if settings.notion_api_key:
        notion_service = NotionService(
            api_key=settings.notion_api_key,
            content_calendar_db=settings.notion_content_calendar_db,
            campaign_tracker_db=settings.notion_campaign_tracker_db,
        )
        logger.info("Notion integration configured")

    # Optional: Search service
    search_service = SearchService(tavily_api_key=settings.tavily_api_key)
    logger.info("Search service: %s", "Tavily" if settings.tavily_api_key else "DuckDuckGo (fallback)")

    # 4. Build bot
    bot = DigitalMateBot(
        settings=settings,
        llm_client=llm_client,
        router=router,
        session_manager=session_manager,
        brand_manager=brand_manager,
        notion_service=notion_service,
        search_service=search_service,
    )

    app = bot.build_application()

    # 5. Print startup banner
    integrations = []
    if notion_service and notion_service.is_configured:
        integrations.append("Notion ✅")
    else:
        integrations.append("Notion ❌")
    if settings.tavily_api_key:
        integrations.append("Tavily Search ✅")
    else:
        integrations.append("DuckDuckGo Search ✅")

    print(f"\n{'=' * 50}")
    print(f"  🤖 {settings.bot_name} v{__version__}")
    print(f"  📱 Telegram Bot is starting...")
    print(f"  🧠 Model: {settings.llm_model}")
    print(f"  🔗 Integrations: {', '.join(integrations)}")
    print(f"  🌐 Language: {settings.bot_language}")
    print(f"{'=' * 50}\n")

    # 6. Run polling with graceful shutdown
    loop = asyncio.get_running_loop()

    def _shutdown_handler(sig: signal.Signals) -> None:
        logger.info("Received signal %s, shutting down gracefully...", sig.name)
        # The polling will stop on next iteration

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _shutdown_handler(s))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("Bot is polling... Press Ctrl+C to stop.")

    # Keep running until interrupted
    stop_event = asyncio.Event()

    def _stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    await stop_event.wait()

    # Graceful shutdown
    logger.info("Stopping bot...")
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    await db.close()
    logger.info("Bot stopped.")


def main() -> None:
    """Main entry point for the Digital Mate bot."""
    args = parse_args()
    setup_logging(args.log_level)

    if args.init_db:
        from digital_mate.config import get_settings
        settings = get_settings()
        asyncio.run(_init_database(settings.db_path))
        return

    try:
        asyncio.run(_run_bot())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
