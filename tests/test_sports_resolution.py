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

    def test_cricket_strictly_excludes_test_matches(self):
        # Test cricket matches MUST be filtered out per strict user rule
        web_app.load_cached_odds("cricket_t20")
        for a in web_app.detected_anomalies:
            self.assertNotIn("test", a.get("event_id", "").lower())
            self.assertNotIn("test", a.get("selection", "").lower())
        for eid in web_app.orderbook.get_all_active_event_ids():
            quotes = web_app.orderbook.get_quotes(eid)
            if quotes:
                first_quote = next(iter(quotes.values()))
                self.assertNotIn("test", first_quote.side_a.lower())
                self.assertNotIn("test", first_quote.side_b.lower())

    def test_load_cached_all_unified(self):
        # Loading 'all' loads all 9 sports into unified orderbook
        loaded = web_app.load_cached_odds("all")
        self.assertTrue(loaded)
        self.assertEqual(web_app.current_active_sport_filter, "all")
        self.assertGreater(len(web_app.detected_anomalies), 100)
        self.assertGreater(len(web_app.orderbook.get_all_active_event_ids()), 150)
        
        # Verify multiple sports are represented in active events
        sports_present = set()
        for eid in web_app.orderbook.get_all_active_event_ids():
            quotes = web_app.orderbook.get_quotes(eid)
            if quotes:
                first_quote = next(iter(quotes.values()))
                sports_present.add(first_quote.sport.value)

        self.assertIn("cricket_t20", sports_present)
        self.assertIn("tennis", sports_present)
        self.assertIn("americanfootball", sports_present)
        self.assertIn("icehockey", sports_present)
        self.assertIn("soccer_dnb", sports_present)
        self.assertIn("basketball_nba", sports_present)

    def test_sport_key_to_enum(self):
        self.assertEqual(web_app.sport_key_to_enum("americanfootball_nfl"), web_app.Sport.AMERICAN_FOOTBALL)
        self.assertEqual(web_app.sport_key_to_enum("icehockey_nhl"), web_app.Sport.ICE_HOCKEY)
        self.assertEqual(web_app.sport_key_to_enum("cricket_odi"), web_app.Sport.CRICKET_T20)
        self.assertEqual(web_app.sport_key_to_enum("cricket_international_t20"), web_app.Sport.CRICKET_T20)
        self.assertEqual(web_app.sport_key_to_enum("tennis_wta_singapore_open"), web_app.Sport.TENNIS)

    def test_resolve_format_title(self):
        # Cricket
        self.assertEqual(web_app.resolve_format_title("cricket_odi", "One Day Internationals"), "ODI")
        self.assertEqual(web_app.resolve_format_title("cricket_international_t20", "International Twenty20"), "T20")
        self.assertEqual(web_app.resolve_format_title("cricket_caribbean_premier_league", "CPL"), "CPL (T20)")
        self.assertEqual(web_app.resolve_format_title("cricket_ipl", "Indian Premier League"), "IPL (T20)")
        # Football
        self.assertEqual(web_app.resolve_format_title("americanfootball_nfl", "NFL"), "NFL")
        self.assertEqual(web_app.resolve_format_title("americanfootball_ncaaf", "NCAA Football"), "NCAAF")
        # Hockey & Basketball
        self.assertEqual(web_app.resolve_format_title("icehockey_nhl", "NHL"), "NHL")
        self.assertEqual(web_app.resolve_format_title("basketball_nba", "NBA"), "NBA")
        # Soccer
        self.assertEqual(web_app.resolve_format_title("soccer_epl", "Premier League"), "EPL")
        self.assertEqual(web_app.resolve_format_title("soccer_usa_mls", "MLS"), "MLS")
        self.assertEqual(web_app.resolve_format_title("soccer_spain_la_liga", "La Liga"), "La Liga")
        # Tennis
        self.assertEqual(web_app.resolve_format_title("tennis_wta_singapore_open", "WTA Singapore Open"), "WTA Singapore Open")

    def test_event_id_format_separation(self):
        from src.normalizer import generate_canonical_event_id
        from src.models import Sport
        odi_id = generate_canonical_event_id(Sport.CRICKET_T20, "India", "West Indies", "ODI")
        t20_id = generate_canonical_event_id(Sport.CRICKET_T20, "India", "West Indies", "T20")
        self.assertNotEqual(odi_id, t20_id)
        self.assertIn("odi", odi_id.lower())
        self.assertIn("t20", t20_id.lower())

    def test_cricket_coexistence_odi_and_t20(self):
        # Verify both India vs WI ODI and T20 exist simultaneously in cricket cache
        web_app.load_cached_odds("cricket_t20")
        eids = web_app.orderbook.get_all_active_event_ids()
        odi_events = [eid for eid in eids if "india" in eid.lower() and ":odi:" in eid.lower()]
        t20_events = [eid for eid in eids if "india" in eid.lower() and ":t20:" in eid.lower()]
        self.assertEqual(len(odi_events), 1)
        self.assertEqual(len(t20_events), 1)

        # Check format title on consensus and quotes
        odi_quotes = web_app.orderbook.get_quotes(odi_events[0])
        t20_quotes = web_app.orderbook.get_quotes(t20_events[0])
        first_odi = next(iter(odi_quotes.values()))
        first_t20 = next(iter(t20_quotes.values()))
        self.assertEqual(first_odi.format_title, "ODI")
        self.assertEqual(first_t20.format_title, "T20")

        # Verify alerts contain format_title
        alert_formats = {a.get("format_title") for a in web_app.detected_anomalies if "India" in a.get("event_id", "")}
        self.assertIn("ODI", alert_formats)


if __name__ == "__main__":
    unittest.main()
