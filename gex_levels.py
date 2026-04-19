


#!/usr/bin/env python3
# =============================================================================
# GEX Levels — Gamma Exposure Analysis Tool
# =============================================================================
# SETUP (one-time):
#   pip install -r requirements.txt
#
# RUN:
#   python gex_levels.py
#   → You will be prompted to enter one or more ticker symbols (e.g. SPY QQQ IWM)
# =============================================================================

import re
import sys
import warnings
from datetime import date, datetime
from math import log, sqrt
from scipy.stats import norm

import numpy as np
import pandas as pd
import yfinance as yf

# Suppress only the noisy but harmless warnings yfinance and pandas emit
# (e.g. "no price data found", future-deprecation notices).
# Using a targeted filter rather than a blanket ignore so that genuine
# DeprecationWarning / SecurityWarning from any dependency still surfaces.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*no timezone.*")
warnings.filterwarnings("ignore", message=".*no price data.*")

# Approximate annualized risk-free rate (3-month T-bill yield).
# Update periodically — stale values shift gamma flip slightly but won't affect
# the call/put wall or OI levels, which dominate the output.
RISK_FREE_RATE = 0.045

CONTRACT_SIZE = 100  # standard equity options contract size

# Ticker symbols are 1–6 uppercase letters, optionally followed by a dot
# and one letter (e.g. BRK.B). Hyphens allowed for yfinance variants (BRK-B).
_TICKER_RE = re.compile(r'^[A-Z]{1,6}([.\-][A-Z])?$')


# =============================================================================
# Input: prompt the user for one or more ticker symbols and validate them
# =============================================================================
def prompt_tickers():
    """
    Ask the user for tickers, validate format, then confirm each resolves to
    a live price via yfinance. Returns a deduplicated list of valid symbols.
    """
    print("Enter one or more ticker symbols separated by spaces or commas.")
    print("  Example:  SPY QQQ IWM   or   spy, qqq, iwm")

    raw = input("\nTickers: ").strip()

    if not raw:
        print("\nERROR: No input received. Please enter at least one ticker symbol.")
        sys.exit(1)

    # split on any mix of commas and whitespace
    tokens = [t.upper() for t in re.split(r'[,\s]+', raw) if t.strip()]

    if not tokens:
        print("\nERROR: Could not parse any tokens from your input.")
        sys.exit(1)

    # deduplicate while preserving entry order
    seen, unique = set(), []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    # format check — catch obvious non-tickers before hitting the network
    bad_format = [t for t in unique if not _TICKER_RE.match(t)]
    if bad_format:
        print(f"\nERROR: The following do not look like valid ticker symbols: {', '.join(bad_format)}")
        print("  Tickers must be 1–6 letters, e.g. SPY, QQQ, BRK.B")
        sys.exit(1)

    # live check — verify each symbol returns a real price from Yahoo Finance
    print(f"\nValidating {', '.join(unique)} ...")
    valid = []
    for sym in unique:
        try:
            price = float(yf.Ticker(sym).fast_info.last_price)
            if price > 0:
                valid.append(sym)
            else:
                print(f"  WARNING: '{sym}' — no price data returned (may be delisted or unsupported), skipping.")
        except Exception:
            print(f"  WARNING: '{sym}' — could not be resolved by Yahoo Finance, skipping.")

    if not valid:
        print("\nERROR: No valid tickers remain after validation. Exiting.")
        sys.exit(1)

    skipped = [t for t in unique if t not in valid]
    if skipped:
        print(f"  Proceeding with valid tickers: {', '.join(valid)}")

    return valid


# =============================================================================
# Helper: compute Black-Scholes gamma from market observables
# yfinance does not provide greeks directly, so we derive gamma from IV.
# Gamma = N'(d1) / (S × σ × √T)
# =============================================================================
def bs_gamma(spot, strike, iv, t_years, r=RISK_FREE_RATE):
    """
    Return the Black-Scholes gamma for a European option.
    Returns 0 on any calculation error (e.g. zero IV, expired option).
    """
    try:
        if iv <= 0 or t_years <= 0 or spot <= 0 or strike <= 0:
            return 0.0
        d1 = (log(spot / strike) + (r + 0.5 * iv ** 2) * t_years) / (iv * sqrt(t_years))
        return norm.pdf(d1) / (spot * iv * sqrt(t_years))
    except Exception:
        return 0.0


# =============================================================================
# Helper: find the two nearest weekly expiration dates from an options ticker
# =============================================================================
def get_nearest_expirations(ticker_obj, run_date, n=2):
    """Return the n nearest expiration dates available on the ticker."""
    expirations = []
    for exp_str in ticker_obj.options:
        exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
        if exp >= run_date:
            expirations.append(exp_str)
    # options are already sorted ascending by yfinance
    return expirations[:n]


# =============================================================================
# Helper: fetch and merge calls + puts for one expiration date
# =============================================================================
def fetch_chain(ticker_obj, expiration, spot, run_dt):
    """
    Return a single DataFrame with calls and puts, tagged by type.
    Gamma is computed via Black-Scholes because yfinance does not supply it.
    run_dt is passed in (rather than calling datetime.now() here) so every
    ticker in the same run uses an identical timestamp for t_years.
    """
    try:
        chain = ticker_obj.option_chain(expiration)
    except Exception as exc:
        print(f"  WARNING: could not fetch chain for {expiration}: {exc}")
        return None

    # time to expiration in fractional years, measured from the exact run time.
    # Using total_seconds() gives sub-day precision, which matters for 0DTE options
    # where gamma is extremely sensitive to time remaining.
    exp_dt = datetime.strptime(expiration, "%Y-%m-%d").replace(hour=16, minute=0)
    seconds_left = (exp_dt - run_dt).total_seconds()
    t_years = max(seconds_left / (365.25 * 24 * 3600), 1 / (365.25 * 24))

    calls = chain.calls.copy()
    puts = chain.puts.copy()
    calls["option_type"] = "call"
    puts["option_type"] = "put"

    merged = pd.concat([calls, puts], ignore_index=True)

    merged["openInterest"] = pd.to_numeric(merged["openInterest"], errors="coerce").fillna(0)
    merged["impliedVolatility"] = pd.to_numeric(merged["impliedVolatility"], errors="coerce").fillna(0)
    merged["strike"] = pd.to_numeric(merged["strike"], errors="coerce")
    merged = merged.dropna(subset=["strike"])

    # compute gamma for each row using Black-Scholes
    merged["gamma"] = merged.apply(
        lambda row: bs_gamma(spot, row["strike"], row["impliedVolatility"], t_years),
        axis=1,
    )


    return merged[["strike", "gamma", "openInterest", "option_type"]].copy()


# =============================================================================
# Core: compute GEX per row, then aggregate to net GEX per strike
# =============================================================================
def compute_gex(chain_df, spot):
    """
    GEX formula per contract:
        GEX = Gamma × Open Interest × Contract Size × Spot² × 0.01

    Calls contribute positive GEX (market makers are long gamma → they sell
    into rallies, buy dips → dampens moves).
    Puts contribute negative GEX (market makers are short gamma → they sell
    dips, buy rallies → amplifies moves).
    """
    df = chain_df.copy()

    raw_gex = df["gamma"] * df["openInterest"] * CONTRACT_SIZE * (spot ** 2) * 0.01

    # sign: +1 for calls, -1 for puts
    df["gex"] = np.where(df["option_type"] == "call", raw_gex, -raw_gex)

    # sum net GEX at each strike across both expirations and both option types
    net = df.groupby("strike")["gex"].sum().reset_index()
    net.columns = ["strike", "net_gex"]
    net = net.sort_values("strike").reset_index(drop=True)
    return net


# =============================================================================
# Core: identify key levels from the net GEX series
# =============================================================================
def find_key_levels(net_gex_df, full_chain_df):
    """
    Returns a dict with:
        call_wall   — strike with highest positive net GEX
        put_wall    — strike with highest negative (most negative) net GEX
        gamma_flip  — strike where cumulative GEX first crosses zero
        top_oi      — top-3 strikes by total open interest
    """
    levels = {}

    # --- Call Wall: max positive GEX ---
    pos = net_gex_df[net_gex_df["net_gex"] > 0]
    if not pos.empty:
        levels["call_wall"] = pos.loc[pos["net_gex"].idxmax(), "strike"]
    else:
        levels["call_wall"] = None

    # --- Put Wall: most negative GEX ---
    neg = net_gex_df[net_gex_df["net_gex"] < 0]
    if not neg.empty:
        levels["put_wall"] = neg.loc[neg["net_gex"].idxmin(), "strike"]
    else:
        levels["put_wall"] = None

    # --- Gamma Flip: cumulative GEX (sorted by strike) crosses zero ---
    df = net_gex_df.sort_values("strike").copy()
    df["cumulative_gex"] = df["net_gex"].cumsum()

    # find first strike where cumulative GEX changes sign from negative to positive
    flip_strike = None
    for i in range(1, len(df)):
        prev = df.iloc[i - 1]["cumulative_gex"]
        curr = df.iloc[i]["cumulative_gex"]
        if prev < 0 <= curr or prev > 0 >= curr:
            # interpolate to the closer strike
            if abs(prev) < abs(curr):
                flip_strike = df.iloc[i - 1]["strike"]
            else:
                flip_strike = df.iloc[i]["strike"]
            break
    levels["gamma_flip"] = flip_strike

    # --- Top-3 OI strikes (across all calls + puts, both expirations) ---
    oi_by_strike = full_chain_df.groupby("strike")["openInterest"].sum()
    top3 = oi_by_strike.nlargest(3).index.tolist()
    levels["top_oi"] = sorted(top3)

    return levels


# =============================================================================
# Output: format and print the morning summary for one ticker
# =============================================================================
def format_summary(ticker, spot, levels, run_ts):
    """Return a multi-line string with the terminal/file summary."""
    lines = []
    sep = "=" * 60

    lines.append(sep)
    lines.append(f"  {ticker}  —  Spot: ${spot:.2f}  —  as of {run_ts}")
    lines.append(sep)

    def fmt_strike(val):
        return f"${val:.2f}" if val is not None else "N/A"

    call_wall = fmt_strike(levels.get("call_wall"))
    put_wall = fmt_strike(levels.get("put_wall"))
    gamma_flip = fmt_strike(levels.get("gamma_flip"))
    top_oi = [fmt_strike(s) for s in levels.get("top_oi", [])]

    lines.append(f"  Call Wall    : {call_wall}")
    lines.append(f"    → Highest positive GEX; acts as overhead resistance / price magnet")

    lines.append(f"  Put Wall     : {put_wall}")
    lines.append(f"    → Highest negative GEX; dealers buy here, tends to act as support")

    lines.append(f"  Gamma Flip   : {gamma_flip}")
    lines.append(f"    → Above = dealers hedge passively (low vol / range-bound)")
    lines.append(f"      Below = dealers amplify moves (trending / volatile regime)")

    lines.append(f"  Top OI Strikes: {', '.join(top_oi) if top_oi else 'N/A'}")
    lines.append(f"    → High open interest = crowd reference levels; expect reactions")

    lines.append(sep)
    return "\n".join(lines)


# =============================================================================
# Output: generate a TOS-ready ThinkScript block for one ticker
# =============================================================================
def format_thinkscript(ticker, spot, levels, run_ts):
    """
    Return a ThinkScript snippet the user can paste directly into TOS:
      Studies → Edit Studies → Create New Study → paste → Save

    Lines use only horizontal plot lines + AddLabel so there are no
    conflicts with existing chart studies.
    """
    cw = levels.get("call_wall")
    pw = levels.get("put_wall")
    gf = levels.get("gamma_flip")
    oi = levels.get("top_oi", [])

    L = []
    L.append(f"# {'─' * 56}")
    L.append(f"# TOS ThinkScript — GEX Levels — {ticker} — {run_ts}")
    L.append(f"# Spot at scan time: ${spot:.2f}")
    L.append(f"# Studies → Edit Studies → Create New Study → paste → Save")
    L.append(f"# {'─' * 56}")
    L.append("")

    def plot_level(name, value, color, label_text):
        L.append(f"plot {name} = {value:.2f};")
        L.append(f"{name}.SetDefaultColor(Color.{color});")
        L.append(f"{name}.SetLineWeight(2);")
        L.append(f"{name}.SetStyle(Curve.SHORT_DASH);")
        L.append(f"{name}.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);")
        L.append(f'AddLabel(yes, "{label_text}: {value:.2f}", Color.{color});')
        L.append("")

    if cw is not None:
        plot_level("CallWall", cw, "GREEN",  "Call Wall")
    if pw is not None:
        plot_level("PutWall",  pw, "RED",    "Put Wall")
    if gf is not None:
        plot_level("GammaFlip", gf, "YELLOW", "Gamma Flip")

    # Top OI strikes in cyan, numbered
    for i, strike in enumerate(oi[:3], 1):
        plot_level(f"TopOI{i}", strike, "CYAN", f"Top OI #{i}")

    return "\n".join(L)


# =============================================================================
# Main
# =============================================================================
def run():
    # Capture a single timestamp at startup so every ticker in this run is
    # stamped identically — avoids clock skew across slow network fetches.
    now = datetime.now()
    run_date = now.date()
    run_ts = now.strftime("%Y-%m-%d %H:%M:%S")       # human-readable label
    file_ts = now.strftime("%Y-%m-%d_%H%M%S")        # safe for filenames

    output_filename = f"levels_{file_ts}.txt"
    output_lines = [f"GEX Levels Report — {run_ts}\n"]
    thinkscript_blocks = []  # collected after all tickers, appended at end of file

    tickers = prompt_tickers()
    print(f"\nRun timestamp: {run_ts}")

    for ticker_symbol in tickers:
        print(f"\nFetching data for {ticker_symbol}...")

        try:
            ticker_obj = yf.Ticker(ticker_symbol)

            # --- get spot price ---
            info = ticker_obj.fast_info
            spot = float(info.last_price)
            if spot <= 0:
                raise ValueError(f"Invalid spot price: {spot}")

        except Exception as exc:
            print(f"  WARNING: skipping {ticker_symbol} — could not get spot price: {exc}")
            continue

        # --- get the two nearest expirations ---
        try:
            expirations = get_nearest_expirations(ticker_obj, run_date, n=2)
            if not expirations:
                print(f"  WARNING: skipping {ticker_symbol} — no expiration dates found")
                continue
        except Exception as exc:
            print(f"  WARNING: skipping {ticker_symbol} — could not fetch expirations: {exc}")
            continue

        print(f"  Using expirations: {', '.join(expirations)}")

        # --- fetch chains for each expiration and combine ---
        all_chains = []
        for exp in expirations:
            chain_df = fetch_chain(ticker_obj, exp, spot, now)
            if chain_df is not None and not chain_df.empty:
                all_chains.append(chain_df)

        if not all_chains:
            print(f"  WARNING: skipping {ticker_symbol} — no options chain data available")
            continue

        full_chain = pd.concat(all_chains, ignore_index=True)

        # --- compute GEX and find key levels ---
        try:
            net_gex = compute_gex(full_chain, spot)
            levels = find_key_levels(net_gex, full_chain)
        except Exception as exc:
            print(f"  WARNING: skipping {ticker_symbol} — GEX calculation failed: {exc}")
            continue

        # --- format and print ---
        summary = format_summary(ticker_symbol, spot, levels, run_ts)
        print(summary)
        output_lines.append(summary)
        output_lines.append("")

        thinkscript_blocks.append(format_thinkscript(ticker_symbol, spot, levels, run_ts))

    # --- append ThinkScript section to output ---
    if thinkscript_blocks:
        output_lines.append("=" * 60)
        output_lines.append("  TOS ThinkScript — copy the block(s) below into TOS")
        output_lines.append("  Studies → Edit Studies → Create New Study → paste → Save")
        output_lines.append("=" * 60)
        output_lines.append("")
        output_lines.extend(thinkscript_blocks)

    # --- save to file ---
    output_text = "\n".join(output_lines)
    try:
        with open(output_filename, "w") as f:
            f.write(output_text)
        print(f"\nOutput saved to: {output_filename}")
    except Exception as exc:
        print(f"\nWARNING: could not save output file: {exc}")


if __name__ == "__main__":
    run()