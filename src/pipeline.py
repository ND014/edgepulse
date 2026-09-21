"""
Main asynchronous orchestrator connecting Ingestion, Normalization,
Devigging, OrderBook caching, and Anomaly Detection.
"""

import asyncio
import time
from typing import Callable, List, Optional
from .models import OddsQuote, NormalizedQuote, AnomalyAlert
from .normalizer import normalize_quote
from .orderbook import OrderBook
from .detector import AnomalyDetector
from .feeds.base import BaseFeed


class AnomalyPipeline:
    """
    High-reliability data pipeline processing concurrent odds streams.
    """

    def __init__(
        self,
        feed,
        sharp_bookmaker: str = "pinnacle",
        delta_threshold: float = 0.03,
        ev_threshold: float = 0.02,
        alert_callback: Optional[Callable[[AnomalyAlert], None]] = None,
    ):
        self.feed = feed
        self.orderbook = OrderBook(sharp_bookmaker=sharp_bookmaker)
        self.detector = AnomalyDetector(
            orderbook=self.orderbook,
            delta_threshold=delta_threshold,
            ev_threshold=ev_threshold,
        )
        self.alert_callback = alert_callback
        self.is_running = False
        self.start_time: float = 0.0
        self.total_processed: int = 0
        self.total_alerts: int = 0

    async def start(self, max_duration_sec: Optional[float] = None):
        """Run the ingestion and anomaly scanning loop."""
        self.is_running = True
        self.start_time = time.time()

        try:
            async for raw_quote in self.feed.stream_quotes():
                if not self.is_running:
                    break

                if max_duration_sec and (time.time() - self.start_time) >= max_duration_sec:
                    break

                # 1. Normalize Quote & Participant Resolution
                norm_quote = normalize_quote(raw_quote)
                self.total_processed += 1

                # 2. Update OrderBook State (auto-updates devigged consensus if sharp)
                self.orderbook.update_quote(norm_quote)

                # 3. Detect Anomalies & Discrepancies
                alerts = self.detector.evaluate_quote(norm_quote)

                # 4. Dispatch Alerts
                for alert in alerts:
                    self.total_alerts += 1
                    if self.alert_callback:
                        self.alert_callback(alert)

        finally:
            self.is_running = False

    def stop(self):
        """Gracefully stop the pipeline."""
        self.is_running = False

    @property
    def throughput_quotes_per_sec(self) -> float:
        elapsed = time.time() - self.start_time
        if elapsed <= 0:
            return 0.0
        return self.total_processed / elapsed
