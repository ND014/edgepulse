"""
Anomaly & +EV detection engine.
Compares retail soft book odds against devigged sharp consensus and triggers alerts.
"""

import time
from typing import List, Optional, Set
from .models import NormalizedQuote, DeviggedConsensus, AnomalyAlert
from .orderbook import OrderBook
from .math_engine import calculate_discrepancy, calculate_ev


class AnomalyDetector:
    """
    Evaluates incoming odds against the devigged sharp consensus.
    Triggers anomaly alerts when market discrepancy Delta or Expected Value exceeds thresholds.
    """

    def __init__(
        self,
        orderbook: OrderBook,
        delta_threshold: float = 0.01,  # e.g., 1.0% discrepancy
        ev_threshold: float = 0.01,     # e.g., +1.0% EV (+1% profit)
        dedup_cooldown_sec: float = 30.0,
    ):
        self.orderbook = orderbook
        self.delta_threshold = delta_threshold
        self.ev_threshold = ev_threshold
        self.dedup_cooldown_sec = dedup_cooldown_sec
        # Cache for deduplication: {alert_signature: last_alert_time}
        self._seen_alerts: dict[str, float] = {}
        self.total_anomalies_detected: int = 0

    def evaluate_quote(self, quote: NormalizedQuote) -> List[AnomalyAlert]:
        """
        Evaluate a soft book quote against the current devigged consensus.
        """
        consensus = self.orderbook.get_consensus(quote.event_id)
        if not consensus:
            return []

        # If the quote is from the sharp bookmaker establishing consensus, recheck existing soft quotes
        if quote.bookmaker == consensus.sharp_bookmaker:
            return self.recheck_event(quote.event_id, consensus)

        return self._check_discrepancies(quote, consensus)

    def recheck_event(self, event_id: str, consensus: DeviggedConsensus) -> List[AnomalyAlert]:
        """
        Called when the sharp book line moves: re-evaluates all existing soft books
        for that event to catch lagging books immediately.
        """
        alerts: List[AnomalyAlert] = []
        all_quotes = self.orderbook.get_quotes(event_id)
        for bookmaker, quote in all_quotes.items():
            if bookmaker == consensus.sharp_bookmaker:
                continue
            alerts.extend(self._check_discrepancies(quote, consensus))
        return alerts

    def _check_discrepancies(
        self, quote: NormalizedQuote, consensus: DeviggedConsensus
    ) -> List[AnomalyAlert]:
        """Check both Side A and Side B for discrepancies."""
        alerts: List[AnomalyAlert] = []
        now = quote.timestamp or time.time()

        # Side A evaluation
        delta_a = calculate_discrepancy(consensus.p_true_a, quote.p_raw_a)
        ev_a = calculate_ev(consensus.p_true_a, quote.decimal_a)

        if delta_a >= self.delta_threshold or ev_a >= self.ev_threshold:
            sig_a = f"{quote.event_id}:{quote.bookmaker}:{quote.side_a}:{quote.american_a}"
            if self._should_fire(sig_a, now):
                alert_a = AnomalyAlert(
                    event_id=quote.event_id,
                    sport=quote.sport,
                    target_book=quote.bookmaker,
                    sharp_book=consensus.sharp_bookmaker,
                    selection_name=quote.side_a,
                    soft_american=quote.american_a,
                    soft_decimal=quote.decimal_a,
                    soft_implied_prob=quote.p_raw_a,
                    sharp_true_prob=consensus.p_true_a,
                    discrepancy_delta=round(delta_a, 5),
                    expected_value=round(ev_a, 5),
                    timestamp=now,
                    commence_time=quote.commence_time or consensus.commence_time,
                )
                alerts.append(alert_a)
                self.total_anomalies_detected += 1

        # Side B evaluation
        delta_b = calculate_discrepancy(consensus.p_true_b, quote.p_raw_b)
        ev_b = calculate_ev(consensus.p_true_b, quote.decimal_b)

        if delta_b >= self.delta_threshold or ev_b >= self.ev_threshold:
            sig_b = f"{quote.event_id}:{quote.bookmaker}:{quote.side_b}:{quote.american_b}"
            if self._should_fire(sig_b, now):
                alert_b = AnomalyAlert(
                    event_id=quote.event_id,
                    sport=quote.sport,
                    target_book=quote.bookmaker,
                    sharp_book=consensus.sharp_bookmaker,
                    selection_name=quote.side_b,
                    soft_american=quote.american_b,
                    soft_decimal=quote.decimal_b,
                    soft_implied_prob=quote.p_raw_b,
                    sharp_true_prob=consensus.p_true_b,
                    discrepancy_delta=round(delta_b, 5),
                    expected_value=round(ev_b, 5),
                    timestamp=now,
                    commence_time=quote.commence_time or consensus.commence_time,
                )
                alerts.append(alert_b)
                self.total_anomalies_detected += 1

        return alerts

    def _should_fire(self, signature: str, current_time: float) -> bool:
        """Rate limit duplicate alerts for the exact same quote."""
        last_time = self._seen_alerts.get(signature, 0.0)
        if current_time - last_time > self.dedup_cooldown_sec:
            self._seen_alerts[signature] = current_time
            return True
        return False
