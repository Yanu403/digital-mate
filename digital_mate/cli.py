"""CLI entry point for Digital Mate.

Provides `digital-mate serve` to launch the web dashboard
and `digital-mate run` to start the bot headless.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="digital-mate",
        description="Digital Mate — AI Marketing Assistant",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )
    subparsers = parser.add_subparsers(dest="command")

    # serve command — start web dashboard
    serve_parser = subparsers.add_parser("serve", help="Start web dashboard")
    serve_parser.add_argument("--port", type=int, default=7749, help="Port (default: 7749)")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    serve_parser.add_argument(
        "--no-browser", action="store_true", help="Don't auto-open browser"
    )

    # run command — headless bot (delegates to __main__)
    subparsers.add_parser("run", help="Start bot without dashboard")

    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn
        from digital_mate.web.app import create_app

        app = create_app()
        if not args.no_browser:
            try:
                import webbrowser

                webbrowser.open(f"http://{args.host}:{args.port}")
            except Exception:
                pass
        uvicorn.run(app, host=args.host, port=args.port)

    elif args.command == "run":
        from digital_mate.__main__ import main as bot_main

        bot_main()

    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
