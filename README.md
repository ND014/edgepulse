# EdgePulse | Quantitative Sports Odds Anomaly & Arbitrage Engine

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?style=flat-square&logo=python)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/Dependencies-Zero%20(Stdlib%20Only)-success.svg?style=flat-square)]()
[![Tests](https://img.shields.io/badge/Tests-30%20Passed-brightgreen.svg?style=flat-square)]()
[![License](https://img.shields.io/badge/License-MIT-purple.svg?style=flat-square)]()
[![Architecture](https://img.shields.io/badge/Architecture-Low--Latency%20Event--Driven-orange.svg?style=flat-square)]()

A high-performance quantitative market microstructure platform that ingests multi-book live sports odds, devigs sharp benchmark books (such as Pinnacle) to compute synthetic "true" consensus probabilities, and detects soft retail books (DraftKings, FanDuel, BetMGM, etc.) with lagging prices, positive expected value (+EV), and guaranteed risk-free arbitrage opportunities.

Designed with **zero external pip dependencies** — powered entirely by the Python standard library.

---

## Key Features

- **Multi-Book Proportional Devigging**: Strips bookmaker overround (vig) from sharp benchmark market makers to compute pure consensus implied probabilities.
- **Real-Time +EV Anomaly Detection**: Identifies pricing inefficiencies where retail sportsbooks lag behind sharp market movement.
- **Automated Dutching Arbitrage Engine**: Solves optimal proportional capital allocation across multiple books to lock in guaranteed risk-free profit margins.
- **Fractional Kelly Criterion Staking**: Mathematically sizes positions to maximize log-wealth growth while minimizing bankroll drawdown risk.
- **Institutional Web Terminal**: Bloomberg/HFT-inspired dashboard featuring interactive SVG anomaly charts, real-time orderbooks, league hubs, and paper-trading portfolio analytics.
- **True Global Currency Engine**: Real-time cross-currency exchange rate multiplication engine, isolating USD backend persistence while seamlessly localizing the UI to INR, EUR, GBP, AUD, and more.
- **Smart API Key Rotation**: Bypasses strict vendor rate limits by seamlessly parsing and rotating through a comma-separated cluster of API keys upon HTTP 429 Quota Exceeded responses.
- **Global Bookmaker Expansion**: Deep enrichment engine categorizing and scanning over 90+ sportsbooks across US, UK, EU, AU, Canada, LATAM, and Africa.
- **Unified Master Hubs**: Aggregates disparate sports leagues (e.g., MLB, KBO, NPB) into single-click "All Active" master dashboards for instantaneous global market scanning.
- **Zero External Dependencies**: Zero `pip install` required. Built using Python's native `http.server`, `threading`, `sqlite3`, `json`, and `urllib`.
- **Automated Webhook Dispatch**: Configurable real-time notifications to Discord and Telegram for detected anomalies exceeding custom edge thresholds.
- **30/30 Automated Unit Tests**: Comprehensive test suite covering odds conversions, devigging mathematics, Dutching arbitrage models, entity resolution, and HTTP API endpoints.

---

## Quantitative Mathematical Specifications

### 1. Odds & Probability Normalization
For American Odds $O$:
* **Favorite ($O < 0$):**
  $$P_{\text{raw}} = \frac{|O|}{|O| + 100}, \quad D = 1 + \frac{100}{|O|}$$
* **Underdog ($O > 0$):**
  $$P_{\text{raw}} = \frac{100}{O + 100}, \quad D = 1 + \frac{O}{100}$$

### 2. Proportional Devigging (Stripping the Vig)
Given sharp benchmark (Pinnacle) probabilities $P_{\text{raw}, A}$ and $P_{\text{raw}, B}$ with overround $S = \sum P_{\text{raw}} > 1.0$:
$$P_{\text{true}, A} = \frac{P_{\text{raw}, A}}{S}, \quad P_{\text{true}, B} = \frac{P_{\text{raw}, B}}{S}$$

### 3. +EV Anomaly Detection
$$\text{Discrepancy } (\Delta) = P_{\text{true}, \text{sharp}} - P_{\text{implied}, \text{soft}}$$
$$\text{Expected Value (EV)} = (P_{\text{true}, \text{sharp}} \times D_{\text{soft}}) - 1.0$$
* **Signal:** Trigger an alert if $\text{EV} \ge \epsilon$ (e.g., $+2\%$) and $\Delta \ge \text{threshold}$.

### 4. Multi-Way Dutching Arbitrage & Stake Sizing
For a 2-way market with best available decimal odds $D_A$ on Book 1 and $D_B$ on Book 2:
$$\text{Implied Total Margin } I = \frac{1}{D_A} + \frac{1}{D_B}$$
* If $I < 1.0$, an **arbitrage opportunity** exists with guaranteed ROI:
  $$\text{ROI} = \left(\frac{1}{I} - 1\right) \times 100\%$$
* For total allocated stake $S_{\text{total}}$, individual position sizes are calculated as:
  $$S_A = S_{\text{total}} \times \frac{1 / D_A}{I}, \quad S_B = S_{\text{total}} \times \frac{1 / D_B}{I}$$

### 5. Fractional Kelly Criterion
$$f^* = \text{multiplier} \times \frac{(P_{\text{true}} \times D_{\text{soft}}) - 1}{D_{\text{soft}} - 1}$$

---

## Directory Architecture

```
odds-anomaly-engine/
├── .env.example             # Environment template
├── Dockerfile               # Production multi-stage container
├── requirements.txt         # Clean dependency documentation (Standard Library)
├── run.py                   # High-speed terminal CLI simulation runner
├── web_app.py               # Low-latency multi-threaded web & API server
├── src/
│   ├── arbitrage.py         # Dutching arbitrage detection and stake sizing
│   ├── db.py                # Concurrency-safe SQLite persistence layer
│   ├── detector.py          # +EV anomaly scanner and threshold engine
│   ├── math_engine.py       # Odds conversion, devigging, and Kelly math
│   ├── models.py            # Dataclasses, market quotes, and alert schemas
│   ├── normalizer.py        # Entity resolution and canonical alias matching
│   ├── notifier.py          # Discord webhook delivery engine
│   ├── orderbook.py         # Multi-book concurrency-safe in-memory cache
│   ├── pipeline.py          # Asynchronous stream orchestrator
│   ├── telegram.py          # Telegram alert dispatcher
│   └── feeds/
│       ├── base.py          # Abstract feed connector interface
│       ├── api_feed.py      # Live The-Odds-API HTTP feed connector
│       └── mock_stream.py   # Latency-lagged multi-book market simulator
├── static/
│   ├── index.html           # Institutional HFT terminal web interface
│   ├── js/                  # Interactive charts, real-time polling, and modals
│   └── css/                 # Modern dark terminal styling
├── data_cache/              # Cached historical orderbooks for offline/instant mode
└── tests/
    ├── test_suite.py        # Core mathematics, devig, and pipeline tests
    ├── test_arbitrage.py    # Dutching arbitrage & stake sizing unit tests
    └── test_auth_api.py     # Auth, session management, and API tests
```

---

## Quick Start

### 1. Run Automated Tests
```bash
python3 -m unittest discover tests
```
*Executes all 30 tests covering devigging precision, entity resolution, Kelly math, and HTTP handlers.*

### 2. Launch Terminal CLI Simulation
```bash
python3 run.py --duration 10 --threshold 0.03 --ev 0.02
```

### 3. Launch Web Terminal (Local Development)
```bash
python3 web_app.py
```
Open **[http://localhost:8080](http://localhost:8080)** in your browser.

*Tip: EdgePulse ships with pre-cached high-fidelity orderbooks in `data_cache/` so it starts immediately with live data even without an external API key.*

---

## Environment Configuration

To enable live odds updates from The-Odds-API or cloud authentication, copy the template:
```bash
cp .env.example .env
```
And set your configuration values:
```ini
ODDS_API_KEY=your_odds_api_key_here
PORT=8080
GOOGLE_CLIENT_ID=your_oauth_client_id
GOOGLE_CLIENT_SECRET=your_oauth_client_secret
```

---

## Deployment

### Docker Deployment
```bash
docker build -t edgepulse:latest .
docker run -d -p 8080:8080 -v $(pwd)/data:/app/data --name edgepulse edgepulse:latest
```

### Google Cloud Run (Production)
EdgePulse includes a fully automated deployment script for Google Cloud Run. It utilizes the included `Dockerfile` for containerization and seamlessly pushes to GCP.

```bash
# Deploy instantly to Google Cloud Run
./deploy.sh
```
*Note: Ensure you have the `gcloud` CLI installed and authenticated with your GCP project.*

---

## License

MIT License. Engineered for educational, quantitative research, and market microstructure analysis.
