"""
Comprehensive unit test suite for the Odds Normalization & Anomaly Engine.
Tests math conversions, proportional devigging, entity normalization, orderbook caching,
and anomaly detection thresholds.
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import Sport, MarketType, OddsFormat, OddsQuote, NormalizedQuote
from src.math_engine import (
    american_to_decimal,
    decimal_to_american,
    american_to_implied_prob,
    decimal_to_implied_prob,
    implied_prob_to_american,
    proportional_devig,
    calculate_discrepancy,
    calculate_ev,
    calculate_kelly_stake,
)
from src.normalizer import resolve_entity, generate_canonical_event_id, normalize_quote
from src.orderbook import OrderBook
from src.detector import AnomalyDetector


class TestMathEngine(unittest.TestCase):
    """Test all quantitative betting math functions."""

    def test_american_to_decimal(self):
        self.assertAlmostEqual(american_to_decimal(+100), 2.0, places=4)
        self.assertAlmostEqual(american_to_decimal(+150), 2.5, places=4)
        self.assertAlmostEqual(american_to_decimal(-110), 1.9091, places=4)
        self.assertAlmostEqual(american_to_decimal(-200), 1.5, places=4)
        with self.assertRaises(ValueError):
            american_to_decimal(0)

    def test_decimal_to_american(self):
        self.assertEqual(decimal_to_american(2.0), 100)
        self.assertEqual(decimal_to_american(2.5), 150)
        self.assertEqual(decimal_to_american(1.5), -200)
        self.assertEqual(decimal_to_american(1.9091), -110)

    def test_american_to_implied_prob(self):
        # Favorite: -110 is 110 / 210 = 0.5238
        self.assertAlmostEqual(american_to_implied_prob(-110), 0.52381, places=4)
        # Underdog: +110 is 100 / 210 = 0.4762
        self.assertAlmostEqual(american_to_implied_prob(+110), 0.47619, places=4)
        # Even money: +100 is 100 / 200 = 0.50
        self.assertAlmostEqual(american_to_implied_prob(+100), 0.50000, places=4)

    def test_proportional_devig_symmetric(self):
        # -110 / -110 market
        p_raw_a = american_to_implied_prob(-110)
        p_raw_b = american_to_implied_prob(-110)
        p_true_a, p_true_b, overround = proportional_devig(p_raw_a, p_raw_b)

        # In a symmetric line, both true probabilities must be exactly 50%
        self.assertAlmostEqual(p_true_a, 0.50, places=4)
        self.assertAlmostEqual(p_true_b, 0.50, places=4)
        self.assertAlmostEqual(p_true_a + p_true_b, 1.0, places=6)
        self.assertAlmostEqual(overround, 1.04762, places=4)

    def test_proportional_devig_asymmetric(self):
        # -200 favorite, +170 underdog
        p_raw_a = american_to_implied_prob(-200)  # 200/300 = 0.66667
        p_raw_b = american_to_implied_prob(+170)  # 100/270 = 0.37037
        p_true_a, p_true_b, overround = proportional_devig(p_raw_a, p_raw_b)

        self.assertAlmostEqual(p_true_a + p_true_b, 1.0, places=6)
        self.assertAlmostEqual(p_true_a, 0.64286, places=4)
        self.assertAlmostEqual(p_true_b, 0.35714, places=4)

    def test_calculate_ev(self):
        # If true prob is 60% and soft book pays +110 (2.10 decimal)
        ev = calculate_ev(0.60, 2.10)
        # EV = (0.60 * 2.10) - 1.0 = 1.26 - 1.0 = +0.26 (+26% ROI)
        self.assertAlmostEqual(ev, 0.26, places=4)

    def test_calculate_kelly_stake(self):
        # True prob = 60%, Decimal = 2.10 (net odds b = 1.10), EV = +26%
        # Full Kelly = 0.26 / 1.10 = 0.23636 (23.64% of bankroll)
        # Quarter Kelly (0.25x) = 0.05909 (5.91% of bankroll)
        # On $1,000 bankroll -> Stake = $59.09
        stake, pct, exp_profit = calculate_kelly_stake(0.60, 2.10, 1000.0, 0.25)
        self.assertAlmostEqual(stake, 59.09, places=2)
        self.assertAlmostEqual(pct, 5.91, places=2)
        self.assertAlmostEqual(exp_profit, 15.36, places=2)

        # Half Kelly (0.50x)
        stake_half, _, _ = calculate_kelly_stake(0.60, 2.10, 1000.0, 0.50)
        self.assertAlmostEqual(stake_half, 118.18, places=2)

        # Negative EV: true prob 40%, decimal 2.0 -> stake must be 0
        stake_neg, pct_neg, _ = calculate_kelly_stake(0.40, 2.0, 1000.0, 0.25)
        self.assertEqual(stake_neg, 0.0)
        self.assertEqual(pct_neg, 0.0)



class TestNormalizer(unittest.TestCase):
    """Test participant resolution and quote normalization."""

    def test_entity_aliases(self):
        self.assertEqual(resolve_entity("J. Jones"), "Jon Jones")
        self.assertEqual(resolve_entity("C. Alcaraz"), "Carlos Alcaraz")
        self.assertEqual(resolve_entity("Lakers"), "LA Lakers")
        self.assertEqual(resolve_entity("CSK"), "Chennai Super Kings")
        self.assertEqual(resolve_entity("Man City"), "Manchester City")

    def test_canonical_event_id_symmetry(self):
        id_1 = generate_canonical_event_id(Sport.UFC, "Jon Jones", "Alex Pereira")
        id_2 = generate_canonical_event_id(Sport.UFC, "Alex Pereira", "J. Jones")
        self.assertEqual(id_1, id_2)

    def test_normalize_quote(self):
        raw = OddsQuote(
            event_id="",
            sport=Sport.TENNIS,
            market_type=MarketType.HEAD_TO_HEAD,
            bookmaker="DraftKings",
            side_a="C. Alcaraz",
            side_b="J. Sinner",
            side_a_odds=-125,
            side_b_odds=+105,
            odds_format=OddsFormat.AMERICAN,
            timestamp=1000.0,
        )
        norm = normalize_quote(raw)
        self.assertEqual(norm.bookmaker, "draftkings")
        self.assertEqual(norm.side_a, "Carlos Alcaraz")
        self.assertEqual(norm.side_b, "Jannik Sinner")
        self.assertAlmostEqual(norm.decimal_a, 1.8, places=2)
        self.assertAlmostEqual(norm.decimal_b, 2.05, places=2)


class TestOrderBookAndDetector(unittest.TestCase):
    """Test orderbook caching and anomaly alerting logic."""

    def setUp(self):
        self.orderbook = OrderBook(sharp_bookmaker="pinnacle")
        self.detector = AnomalyDetector(
            orderbook=self.orderbook,
            delta_threshold=0.03,  # 3%
            ev_threshold=0.02,     # 2%
            dedup_cooldown_sec=10.0,
        )

    def test_orderbook_consensus_creation(self):
        event_id = "ufc:Alex Pereira_vs_Jon Jones"
        # 1. First feed Pinnacle quote (-150 / +130)
        pinnacle_raw = OddsQuote(
            event_id=event_id,
            sport=Sport.UFC,
            market_type=MarketType.HEAD_TO_HEAD,
            bookmaker="pinnacle",
            side_a="Jon Jones",
            side_b="Alex Pereira",
            side_a_odds=-150,
            side_b_odds=+130,
            timestamp=100.0,
        )
        norm_pin = normalize_quote(pinnacle_raw)
        consensus = self.orderbook.update_quote(norm_pin)

        self.assertIsNotNone(consensus)
        self.assertAlmostEqual(consensus.p_true_a + consensus.p_true_b, 1.0, places=5)
        # Check consensus was cached
        self.assertEqual(self.orderbook.get_consensus(event_id), consensus)

    def test_anomaly_detection_trigger(self):
        event_id = "cricket_t20:Chennai Super Kings_vs_Mumbai Indians"
        # 1. Establish Sharp Consensus on Pinnacle:
        # Pinnacle: CSK is heavy favorite -180 (implied ~64.3%), MI is +155 (implied ~39.2%)
        # Devigged true prob for CSK is ~62.1%
        pin_raw = OddsQuote(
            event_id=event_id,
            sport=Sport.CRICKET_T20,
            market_type=MarketType.HEAD_TO_HEAD,
            bookmaker="pinnacle",
            side_a="Chennai Super Kings",
            side_b="Mumbai Indians",
            side_a_odds=-180,
            side_b_odds=+155,
            timestamp=100.0,
        )
        self.orderbook.update_quote(normalize_quote(pin_raw))

        # 2. DraftKings is sleeping! They still offer CSK at -120 (paying 1.833, implied prob 54.5%)
        # True prob = ~62.1%, Soft implied prob = 54.5% -> Discrepancy Delta = +7.6%!
        # EV = (0.621 * 1.833) - 1.0 = +13.8% (+EV!)
        dk_raw = OddsQuote(
            event_id=event_id,
            sport=Sport.CRICKET_T20,
            market_type=MarketType.HEAD_TO_HEAD,
            bookmaker="draftkings",
            side_a="CSK",
            side_b="MI",
            side_a_odds=-120,
            side_b_odds=+100,
            timestamp=101.0,
        )
        dk_norm = normalize_quote(dk_raw)
        self.orderbook.update_quote(dk_norm)
        alerts = self.detector.evaluate_quote(dk_norm)

        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.target_book, "draftkings")
        self.assertEqual(alert.selection_name, "Chennai Super Kings")
        self.assertGreater(alert.discrepancy_delta, 0.05)  # Greater than 5% discrepancy
        self.assertGreater(alert.expected_value, 0.05)     # Greater than 5% EV


class TestDiscordNotifier(unittest.TestCase):
    """Test Discord webhook settings persistence and validation."""

    def test_settings_load_and_save(self):
        from src.notifier import load_settings, save_settings
        orig = load_settings()
        saved = save_settings({"bankroll": 5000.0, "kelly_multiplier": 0.5})
        self.assertEqual(saved["bankroll"], 5000.0)
        self.assertEqual(saved["kelly_multiplier"], 0.5)

        loaded = load_settings()
        self.assertEqual(loaded["bankroll"], 5000.0)
        self.assertEqual(loaded["kelly_multiplier"], 0.5)

        # Restore original settings
        save_settings(orig)

    def test_send_discord_test_invalid_url(self):
        from src.notifier import send_discord_test
        ok, msg = send_discord_test("https://not-discord.com/webhook")
        self.assertFalse(ok)
        self.assertIn("Invalid Discord webhook URL", msg)


if __name__ == "__main__":
    unittest.main()

