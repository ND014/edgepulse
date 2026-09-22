"""
In-memory orderbook and multi-book market state manager.
Maintains thread-safe / async state of all active 2-way events and their sharp consensus.
"""

import time
from typing import Dict, List, Optional
from .models import NormalizedQuote, DeviggedConsensus
from .math_engine import proportional_devig


class OrderBook:
    """
    In-memory state cache indexing live odds quotes by event and bookmaker.
    Automatically maintains devigged consensus when sharp book quotes arrive.
    """

    def __init__(self, sharp_bookmaker: str = "pinnacle", sharp_hierarchy: Optional[List[str]] = None):
        if sharp_hierarchy:
            self.sharp_hierarchy = [b.lower() for b in sharp_hierarchy]
        elif sharp_bookmaker:
            self.sharp_hierarchy = [sharp_bookmaker.lower(), "betonlineag", "betfair_ex_eu"]
        else:
            self.sharp_hierarchy = ["pinnacle", "betonlineag", "betfair_ex_eu"]
        self.sharp_bookmaker = self.sharp_hierarchy[0]
        # Structure: {event_id: {bookmaker: NormalizedQuote}}
        self._quotes: Dict[str, Dict[str, NormalizedQuote]] = {}
        # Structure: {event_id: DeviggedConsensus}
        self._consensus: Dict[str, DeviggedConsensus] = {}
        # Metrics
        self.total_quotes_ingested: int = 0
        self.total_consensus_updates: int = 0

    def update_quote(self, quote: NormalizedQuote) -> Optional[DeviggedConsensus]:
        """
        Store the normalized quote. If the quote is from the sharp reference book (or fallback sharp),
        recompute and update the event's DeviggedConsensus.
        
        Returns:
            The newly updated DeviggedConsensus if sharp quote, else None.
        """
        event_id = quote.event_id
        if event_id not in self._quotes:
            self._quotes[event_id] = {}

        self._quotes[event_id][quote.bookmaker] = quote
        self.total_quotes_ingested += 1

        # Check if this update came from our sharp reference hierarchy
        if quote.bookmaker in self.sharp_hierarchy:
            curr = self._consensus.get(event_id)
            curr_rank = self.sharp_hierarchy.index(curr.sharp_bookmaker) if (curr and curr.sharp_bookmaker in self.sharp_hierarchy) else 999
            new_rank = self.sharp_hierarchy.index(quote.bookmaker)

            # Update consensus if:
            # 1. No consensus yet, OR
            # 2. Update from same book, OR
            # 3. New book is strictly higher priority in sharp hierarchy (new_rank < curr_rank)
            if curr is None or quote.bookmaker == curr.sharp_bookmaker or new_rank < curr_rank:
                p_true_a, p_true_b, overround_sum = proportional_devig(quote.p_raw_a, quote.p_raw_b)
                fair_dec_a = round(1.0 / p_true_a, 4)
                fair_dec_b = round(1.0 / p_true_b, 4)

                consensus = DeviggedConsensus(
                    event_id=event_id,
                    sport=quote.sport,
                    sharp_bookmaker=quote.bookmaker,
                    side_a=quote.side_a,
                    side_b=quote.side_b,
                    p_true_a=round(p_true_a, 5),
                    p_true_b=round(p_true_b, 5),
                    sharp_overround=round(overround_sum - 1.0, 5),
                    fair_decimal_a=fair_dec_a,
                    fair_decimal_b=fair_dec_b,
                    timestamp=quote.timestamp or time.time(),
                    commence_time=quote.commence_time,
                    format_title=quote.format_title,
                )
                self._consensus[event_id] = consensus
                self.total_consensus_updates += 1
                return consensus

        return None

    def get_consensus(self, event_id: str) -> Optional[DeviggedConsensus]:
        """Get latest devigged sharp consensus for an event."""
        return self._consensus.get(event_id)

    def get_quotes(self, event_id: str) -> Dict[str, NormalizedQuote]:
        """Get all bookmaker quotes for an event."""
        return self._quotes.get(event_id, {}).copy()

    def get_quote(self, event_id: str, bookmaker: str) -> Optional[NormalizedQuote]:
        """Get specific bookmaker quote for an event."""
        return self._quotes.get(event_id, {}).get(bookmaker.lower())

    def get_all_active_event_ids(self) -> List[str]:
        """Return list of all registered event IDs."""
        return list(self._quotes.keys())
