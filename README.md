# GEX Levels

Pulls live options chains from Yahoo Finance (no API key or account required) and computes **Gamma Exposure (GEX)** key levels for any ticker with listed options. Output goes to the terminal and a timestamped `.txt` file that also contains a ready-to-paste TOS ThinkScript block.

## Setup

```bash
pip install -r requirements.txt
```

Dependencies: `yfinance`, `numpy`, `pandas`, `scipy`

## Run

```bash
python gex_levels.py
```

You will be prompted to enter one or more tickers:

```
Enter one or more ticker symbols separated by spaces or commas.
  Example:  SPY QQQ IWM   or   spy, qqq, iwm

Tickers: SPY QQQ
```

Input is case-insensitive. Symbols are validated in two stages before any data is fetched:
1. **Format check** — must be 1–6 letters (e.g. `SPY`, `BRK.B`); numbers and long strings are rejected immediately with a specific error message
2. **Live check** — each symbol is confirmed against Yahoo Finance; unresolvable or delisted tickers are skipped with a warning, valid ones proceed

## Output

Each run saves `levels_YYYY-MM-DD_HHMMSS.txt` in the same folder. The file has two sections:

**Section 1 — GEX summary** (one block per ticker):
```
============================================================
  SPY  —  Spot: $710.14  —  as of 2026-04-19 15:31:17
============================================================
  Call Wall    : $710.00
  Put Wall     : $693.00
  Gamma Flip   : $655.00
  Top OI Strikes: $690.00, $693.00, $700.00
============================================================
```

**Section 2 — TOS ThinkScript** (one block per ticker, appended at the end):
Paste directly into TOS: **Studies → Edit Studies → Create New Study → paste → Save**. Renders each level as a labeled horizontal dashed line on the chart.

| Level | Line color |
|-------|-----------|
| Call Wall | Green |
| Put Wall | Red |
| Gamma Flip | Yellow |
| Top OI #1–3 | Cyan |

Output files are excluded from version control via `.gitignore`.

## Supported tickers

Any equity or ETF with a listed options chain on Yahoo Finance. Futures must be accessed via their ETF proxy:

| Futures contract | ETF proxy |
|-----------------|-----------|
| /ES (S&P 500) | SPY |
| /NQ (Nasdaq 100) | QQQ |
| /RTY (Russell 2000) | IWM |
| /YM (Dow Jones) | DIA |
| /GC (Gold) | GLD |
| /CL (Crude Oil) | USO |
| /ZB (30yr Treasury) | TLT |

## Key levels explained

| Level | What it means for price behavior |
|-------|----------------------------------|
| **Call Wall** | Strike with the highest positive GEX. Dealers hedge short calls by selling into rallies — acts as overhead resistance and a price magnet into expiration. |
| **Put Wall** | Strike with the highest negative GEX. Dealers hedge short puts by buying dips — tends to act as a support floor. |
| **Gamma Flip** | Strike where cumulative GEX crosses zero. Price **above** = positive gamma regime (dealers are counter-trend, market self-stabilizes, low vol). Price **below** = negative gamma regime (dealers amplify moves, trending, volatile). |
| **Top OI Strikes** | Three strikes with the most total open interest. Heavy crowd positioning — expect reactions, potential pinning near expiration. |

## How GEX is calculated

Yahoo Finance does not expose option greeks. Gamma is derived from implied volatility using Black-Scholes:

```
Γ = N'(d1) / (S × σ × √T)

GEX per contract = Γ × Open Interest × 100 × Spot² × 0.01
```

Calls contribute positive GEX, puts negative. Net GEX is summed per strike across the **two nearest expiration dates**. Time to expiration uses sub-day precision (total seconds to 4pm ET on expiry day), which matters for 0DTE options where gamma spikes sharply in the final hours.

## When to run

| Time | Reason |
|------|--------|
| Pre-market (~8:30am ET) | Open interest has settled overnight — best signal for the day's key levels |
| Midday | Catch IV shifts that can move the Gamma Flip level |
| ~3pm ET | 0DTE gamma explodes in the last hour; levels tighten around spot |

Open interest only updates once daily, so the Call Wall, Put Wall, and Top OI strikes are effectively static intraday. The Gamma Flip is the level most sensitive to intraday IV changes and worth re-checking midday. Running continuously or per-second provides no additional value.

## Notes

- `RISK_FREE_RATE` near the top of `gex_levels.py` is set to the approximate 3-month T-bill yield. Update it periodically — a stale value slightly shifts the Gamma Flip but does not affect the OI-anchored levels.
- Each run timestamps all output from a single `datetime.now()` captured at startup, so every ticker in the same run shares an identical reference time regardless of fetch duration.