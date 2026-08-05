"""
NasTech Sync — main entry point.

Usage:
  python main.py                          # full daemon (web + telegram + sync)
  python main.py --no-telegram            # skip Telegram bot
  python main.py --no-web                 # skip web dashboard
  python main.py --interval 60            # sync every 60 min
  python main.py --port 8080              # web dashboard port
  python main.py --once                   # single sync and exit
  GITHUB_TOKEN=xxx python main.py         # with GitHub auth
"""

import asyncio
import argparse
import logging
import os
import sys

from nastech_sync.config import load_config
from nastech_sync.scheduler import NasTechScheduler
from nastech_sync.syncer import Syncer


def setup_logging(verbose: bool, log_file: str) -> None:
    from pathlib import Path
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)]
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers)


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║          ⚡  N a s T e c h   S y n c                    ║
║  nastechai/NasTech-Agent ← NousResearch/hermes-agent    ║
║  Branded · Synced · 24/7                                ║
╚══════════════════════════════════════════════════════════╝
""")


def main():
    parser = argparse.ArgumentParser(
        prog="nastech-sync",
        description="NasTech Sync — 24/7 daemon keeping NasTech-Agent in sync",
    )
    parser.add_argument("-c", "--config", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--interval", type=int, default=30, help="Sync interval (minutes)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--once", action="store_true", help="Run one sync and exit")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(args.verbose, config.log_file)
    print_banner()

    if args.once:
        syncer = Syncer(config)
        result = syncer.run()
        print(f"\n✅  {result}")
        return 0

    scheduler = NasTechScheduler(config, interval_minutes=args.interval)

    try:
        asyncio.run(scheduler.run_forever(
            web_host=args.host,
            web_port=args.port,
            enable_telegram=not args.no_telegram,
            enable_web=not args.no_web,
        ))
    except KeyboardInterrupt:
        print("\n👋 NasTech Sync stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
