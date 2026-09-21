import unittest
from src.arbitrage import calculate_arbitrage_stakes, find_arbitrage_opportunities


class TestArbitrage(unittest.TestCase):
    def test_calculate_arbitrage_stakes(self):
        # Book A: 2.15, Book B: 2.05 -> Implied sum = 1/2.15 + 1/2.05 = 0.4651 + 0.4878 = 0.9529
        stakes = calculate_arbitrage_stakes(1000.0, 2.15, 2.05)
        self.assertGreater(stakes["guaranteed_profit"], 0.0)
        self.assertAlmostEqual(stakes["stake_a"] + stakes["stake_b"], 1000.0, delta=0.5)
        self.assertGreater(stakes["payout_a"], 1000.0)
        self.assertGreater(stakes["payout_b"], 1000.0)
        self.assertAlmostEqual(stakes["profit_pct"], 4.94, delta=0.2)

    def test_find_arbitrage_opportunities(self):
        events = [
            {
                "event_id": "test_evt_1",
                "sport": "tennis",
                "side_a": "Carlos Alcaraz",
                "side_b": "Jannik Sinner",
                "commence_time": "2026-09-21T18:00:00Z",
                "quotes": {
                    "pinnacle": {"decimal_a": 2.20, "decimal_b": 1.70, "american_a": 120, "american_b": -143},
                    "betonlineag": {"decimal_a": 1.80, "decimal_b": 2.10, "american_a": -125, "american_b": 110},
                }
            },
            {
                "event_id": "test_evt_2_no_arb",
                "sport": "soccer",
                "side_a": "Real Madrid",
                "side_b": "Barcelona",
                "commence_time": "2026-09-22T20:00:00Z",
                "quotes": {
                    "pinnacle": {"decimal_a": 1.85, "decimal_b": 1.95},
                    "bet365": {"decimal_a": 1.80, "decimal_b": 1.90},
                }
            }
        ]

        # In test_evt_1: best_a is pinnacle @ 2.20, best_b is betonlineag @ 2.10
        # Implied sum: 1/2.20 + 1/2.10 = 0.4545 + 0.4762 = 0.9307 < 1.0 -> Arb!
        arbs = find_arbitrage_opportunities(events)
        self.assertEqual(len(arbs), 1)
        self.assertEqual(arbs[0]["event_id"], "test_evt_1")
        self.assertEqual(arbs[0]["book_a"], "pinnacle")
        self.assertEqual(arbs[0]["odds_a"], 2.20)
        self.assertEqual(arbs[0]["book_b"], "betonlineag")
        self.assertEqual(arbs[0]["odds_b"], 2.10)
        self.assertGreater(arbs[0]["profit_pct"], 7.0)


if __name__ == '__main__':
    unittest.main()
