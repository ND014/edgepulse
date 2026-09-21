"""
Base abstract class for all real-time odds feeds.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator
from ..models import OddsQuote


class BaseFeed(ABC):
    """Abstract interface for odds ingestion feeds."""

    @abstractmethod
    async def stream_quotes(self) -> AsyncIterator[OddsQuote]:
        """Yield OddsQuote objects asynchronously."""
        pass
