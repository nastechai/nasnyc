"""
Scheduled runner — keeps NasTech-Agent continuously in sync with hermes-agent.

Usage:
  python run.py                  # check every 30 minutes (default)
  python run.py --interval 60    # check every 60 minutes
  python run.py --once           # run once and exit
  GITHUB_TOKEN=xxx python run.py # with auth token in env
"""

import sys
import time
import argparse
import logging
from datetime import datetime

import schedule

from nastech_sync.cli import setup_logging
from nastech_sync.config import load_config
from nastech_sync.syncer import Syncer

logger = logging.getLogger("nastech_sync.runner")


def run_sync(config) -> None:
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running sync...")
    syncer = Syncer(config)
    result = syncer.run()
    if result.errors:
        logger.error("Sync finished with errors: %s", result.errors)
    else:
        logger.info("Sync finished: %s", result)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="NasTech Sync — continuous sync daemon"
    )
    parser.add_argument("-c", "--config", default=None, help="Path to config.yaml")
    parser.add_argument("--interval", type=int, default=30,
                        help="Sync interval in minutes (default: 30)")
    parser.add_argument("--once", action="store_true",
                        help="Run once and exit instead of looping")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(verbose=args.verbose, log_file=config.log_file)

    if args.once:
        run_sync(config)
        return 0

    print(f"NasTech Sync daemon started — checking every {args.interval} min")
    print(f"  Upstream   : {config.upstream.url}")
    print(f"  Downstream : {config.downstream.url}")
    print(f"  Log file   : {config.log_file}")
    print("  Press Ctrl+C to stop\n")

    # Run immediately on start
    run_sync(config)

    schedule.every(args.interval).minutes.do(run_sync, config=config)

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
