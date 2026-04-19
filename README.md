# GEX Levels

Pulls live options chains from Yahoo Finance (no API key required) and computes **Gamma Exposure (GEX)** key levels for any list of tickers. Output goes to the terminal and a timestamped `.txt` file.

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
python gex_levels.py
```

Output is saved to `levels_YYYY-MM-DD_HHMMSS.txt` in the same folder.

## Configure tickers

Edit the `TICKERS` list near the top of `gex_levels.py`:

```python
TICKERS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
```

Works with any equity or ETF that has an options chain on Yahoo Finance. Futures must be accessed via their ETF proxy (e.g. `/ES` → `SPY`, `/NQ` → `QQQ`, `/GC` → `GLD`).

## Key levels explained

| Level | What it means |
|-------|---------------|
| **Call Wall** | Strike with the highest positive GEX. Dealers are short calls here and hedge by selling into rallies — acts as overhead resistance / price magnet. |
| **Put Wall** | Strike with the highest negative GEX. Dealers are short puts here and hedge by buying dips — tends to act as support. |
| **Gamma Flip** | Strike where cumulative GEX crosses zero. Price **above** = positive gamma regime (low vol, range-bound). Price **below** = negative gamma regime (trending, volatile). |
| **Top OI Strikes** | Three strikes with the most open interest across calls and puts. High crowd positioning → expect reactions at these levels. |

## How GEX is calculated

Yahoo Finance does not expose option greeks, so gamma is derived from implied volatility using the Black-Scholes formula:

```
Γ = N'(d1) / (S × σ × √T)
```

GEX per contract:

```
GEX = Γ × Open Interest × 100 × Spot² × 0.01
```

Calls are positive (dealers long gamma), puts are negative (dealers short gamma). Net GEX is summed across all contracts at each strike for the two nearest expiration dates.

## Notes

- `RISK_FREE_RATE` in the script is hardcoded to the approximate 3-month T-bill yield. Update it occasionally.
- GEX levels shift throughout the trading day as spot, IV, and open interest change. Re-run as needed.
- Output files (`levels_*.txt`) are excluded from version control via `.gitignore`.