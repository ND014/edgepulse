"""
Unit tests for dynamic league discovery, match time filtering, and sport mapping.
"""

import unittest
from datetime import datetime, timezone, timedelta
import web_app


class TestSportsResolution(unittest.TestCase):
    """Test dynamic sports resolution and match filtering."""

    def test_is_match_active_or_upcoming_future(self):
        # A match starting in 2 hours should be active
        future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.assertTrue(web_app.is_match_active_or_upcoming(future_time))

    def test_is_match_active_or_upcoming_recent_past(self):
        # A match that started 2 hours ago is still in play
        recent_past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.assertTrue(web_app.is_match_active_or_upcoming(recent_past, max_hours_past=12.0))

    def test_is_match_active_or_upcoming_concluded_yesterday(self):
        # A match that started 24 hours ago (yesterday) must be filtered out
        yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        self.assertFalse(web_app.is_match_active_or_upcoming(yesterday, max_hours_past=12.0))

    def test_is_match_active_or_upcoming_invalid_string(self):
        # Empty or invalid string should gracefully return True without raising exception
        self.assertTrue(web_app.is_match_active_or_upcoming(""))
        self.assertTrue(web_app.is_match_active_or_upcoming("not-a-date"))

    def test_sport_api_map_entries(self):
        # Ensure cricket and tennis keys are mapped properly
        self.assertIn("cricket", web_app.SPORT_API_MAP)
        self.assertIn("cricket_t20", web_app.SPORT_API_MAP)
        self.assertIn("cricket_odi", web_app.SPORT_API_MAP)
        self.assertIn("tennis", web_app.SPORT_API_MAP)
        self.assertIn("tennis_wta_singapore_open", web_app.SPORT_API_MAP)

    def test_load_cached_tennis(self):
        # Loading tennis cache should populate detected anomalies with WTA Singapore Open data
        loaded = web_app.load_cached_odds("tennis")
        self.assertTrue(loaded)
        self.assertGreater(len(web_app.detected_anomalies), 0)
        self.assertEqual(web_app.current_active_sport_filter, "tennis")
        # Check that no Alcaraz/Sinner mock data exists
        for a in web_app.detected_anomalies:
            self.assertNotIn("Alcaraz", a.get("event_id", ""))
            self.assertNotIn("Sinner", a.get("event_id", ""))

    def test_load_cached_cricket(self):
        # Loading cricket cache should populate detected anomalies with real ODI/T20 data
        loaded = web_app.load_cached_odds("cricket_t20")
        self.assertTrue(loaded)
        self.assertGreater(len(web_app.detected_anomalies), 0)
        self.assertEqual(web_app.current_active_sport_filter, "cricket_t20")
        # Check that real matches are present
        events = {a.get("event_id") for a in web_app.detected_anomalies}
        self.assertTrue(any("Sri Lanka" in e or "West Indies" in e or "Bermuda" in e for e in events))


if __name__ == "__main__":
    unittest.main()
