#!/usr/bin/env python3
"""
CLI runner and live demo for the Real-Time Multi-Book Odds Normalization & Anomaly Engine.
"""

import argparse
import asyncio
import os
import sys
import time

from src.models import Sport, AnomalyAlert
from src.feeds.mock_stream import MockStreamFeed
from src.feeds.api_feed import TheOddsAPIFeed
from src.pipeline import AnomalyPipeline


# ANSI Terminal Colors
BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
MAGENTA = "\033[95m"
RESET = "\033[0m"


def print_banner():
    print(f"{BOLD}{CYAN}========================================================================{RESET}")
    print(f"{BOLD}{CYAN}    REAL-TIME MULTI-BOOK ODDS NORMALIZATION & ANOMALY ENGINE (v1)      {RESET}")
    print(f"{BOLD}{CYAN}========================================================================{RESET}")
    print(f" {BOLD}Target Sports:{RESET}   UFC, Tennis (ATP/WTA), NBA, Cricket (T20), Soccer (DNB)")
    print(f" {BOLD}Sharp Reference:{RESET} Pinnacle (stripped of vig via proportional devigging)")
    print(f" {BOLD}Retail Targets:{RESET}  DraftKings, FanDuel, BetMGM")
    print(f"{CYAN}------------------------------------------------------------------------{RESET}\n")


def alert_handler(alert: AnomalyAlert):
    """Render formatted alert box in the terminal."""
    sport_tag = f"[{alert.sport.value.upper()}]"
    print(f"\n{BOLD}{RED}🚨 [ANOMALY DETECTED] {sport_tag} Mispriced Retail Line!{RESET}")
    print(f"  {BOLD}Event:{RESET}           {alert.event_id}")
    print(f"  {BOLD}Selection:{RESET}       {GREEN}{alert.selection_name}{RESET}")
    print(f"  {BOLD}Soft Book:{RESET}       {YELLOW}{alert.target_book.upper()}{RESET} offering {BOLD}{alert.soft_american:+d}{RESET} (Decimal: {alert.soft_decimal:.2f})")
    print(f"  {BOLD}Soft Implied P:{RESET}  {alert.soft_implied_prob * 100:.2f}%")
    print(f"  {BOLD}Pinnacle True P:{RESET} {CYAN}{alert.sharp_true_prob * 100:.2f}%{RESET} (Consensus Sharp Value)")
    print(f"  {BOLD}Discrepancy (Δ):{RESET} {MAGENTA}{alert.discrepancy_delta * 100:+.2f}%{RESET}")
    print(f"  {BOLD}Expected Value:{RESET}  {BOLD}{GREEN}{alert.expected_value * 100:+.2f}% (+EV EDGE){RESET}")
    print(f"  {BOLD}Latency Stamp:{RESET}   {time.strftime('%H:%M:%S', time.localtime(alert.timestamp))}")
    print(f"{RED}{'-' * 72}{RESET}")


async def main():
    parser = argparse.ArgumentParser(description="Multi-Book Odds Normalization & Anomaly Engine")
    parser.add_argument("--duration", type=float, default=8.0, help="Run duration in seconds")
    parser.add_argument("--ticks", type=int, default=60, help="Number of ticks for mock stream")
    parser.add_argument("--threshold", type=float, default=0.03, help="Discrepancy Delta threshold (default: 0.03 for 3%)")
    parser.add_argument("--ev", type=float, default=0.02, help="EV edge threshold (default: 0.02 for +2%)")
    parser.add_argument("--speed", type=float, default=0.12, help="Delay between ticks in seconds")
    parser.add_argument("--live", action="store_true", help="Use live The-Odds-API (requires ODDS_API_KEY env var)")

    args = parser.parse_args()

    print_banner()

    if args.live:
        api_key = os.environ.get("ODDS_API_KEY")
        if not api_key:
            print(f"{RED}Error: --live requires the ODDS_API_KEY environment variable to be set.{RESET}")
            sys.exit(1)
        print(f"{YELLOW}Connecting to live The-Odds-API stream...{RESET}\n")
        feed = TheOddsAPIFeed(api_key=api_key)
    else:
        print(f"{CYAN}Starting realistic multi-book synthetic market stream...{RESET}")
        print(f"Config: duration={args.duration}s | tick_delay={args.speed}s | delta_threshold={args.threshold*100:.1f}% | ev_threshold={args.ev*100:.1f}%\n")
        feed = MockStreamFeed(
            tick_delay_sec=args.speed,
            anomaly_chance=0.35,
            total_ticks=args.ticks,
        )

    pipeline = AnomalyPipeline(
        feed=feed,
        sharp_bookmaker="pinnacle",
        delta_threshold=args.threshold,
        ev_threshold=args.ev,
        alert_callback=alert_handler,
    )

    start_t = time.time()
    try:
        await pipeline.start(max_duration_sec=args.duration)
    except KeyboardInterrupt:
        pipeline.stop()

    elapsed = time.time() - start_t
    print(f"\n{BOLD}{CYAN}========================= ENGINE RUN SUMMARY ========================={RESET}")
    print(f"  {BOLD}Runtime Duration:{RESET}        {elapsed:.2f} seconds")
    print(f"  {BOLD}Total Quotes Ingested:{RESET}   {pipeline.total_processed}")
    print(f"  {BOLD}Sharp Consensus Updates:{RESET} {pipeline.orderbook.total_consensus_updates}")
    print(f"  {BOLD}Anomalies Flagged:{RESET}       {BOLD}{GREEN}{pipeline.total_alerts}{RESET}")
    print(f"  {BOLD}Throughput:{RESET}              {pipeline.throughput_quotes_per_sec:.1f} quotes/second")
    print(f"{BOLD}{CYAN}======================================================================{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
