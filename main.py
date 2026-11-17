"""Forecast GTA VI's launch-day Twitch viewers hour by hour (gta6-twitch-ccu-forecast-01).

Model (my own design, standard library only):
  For every comparable past launch, take its release-day hourly series and
  normalise it by its own hour-1 print: lr_h = ln(viewers_h / viewers_1).
  For the target case, weight each comparable by how close its hour-1 print
  is to the target's (Gaussian kernel on log viewers, bandwidth 1.5), and
  downweight by 0.15 when its platform mix differs from the target's on PC
  (a PC launch usually unlocked globally at one time, so its hour 1 already
  holds most of the world; a console-only rolling-midnight launch like GTA VI
  keeps growing as the Americas unlock later in the day). The target's own
  platform mix is read from the comparable carrying the target game's name
  (the GTA VI category's own history entry).
  Per hour, the median is the 10%-trimmed weighted mean of the log-ratios,
  the interquartile range comes from weighted empirical quantiles, and the
  5%/95% tails are median +/- 1.645 * IQR/1.349 (a normal tail on a robust
  spread). The 23 hourly rows are smoothed with a centred 3-hour moving
  average in log space. Quantiles are q = p1 * exp(lr), rounded half-up to
  2 decimals, clamped to (0, 1e9] and non-decreasing.

  Everything is deterministic: fixed weights, sorted iteration, no random
  numbers, no wall clock, no network.
"""

import json
import math
import os
import sys
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a module
# shipped beside this file would import. (This entry is a single file.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Normal quantiles for the five scored levels come from _norm_ppf below
# (Acklam's approximation, error under 1.2e-9).


def _norm_ppf(p):
    """Inverse standard-normal CDF (Acklam's rational approximation).

    Absolute error below 1.2e-9, so the five scored levels reproduce the
    tabulated values above to far more digits than the 2-decimal rounding.
    """
    if p <= 0.0 or p >= 1.0:
        raise ValueError("p must lie in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
             ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)

# Gaussian-kernel bandwidth on log(hour-1 viewers) when weighting comparables.
BANDWIDTH = 1.5
# Weight multiplier for a comparable whose PC status differs from the target's.
CROSS_PC_WEIGHT = 0.15
# Trim fraction (each side) for the weighted trimmed-mean median.
TRIM = 0.10
# Floor for the robust log-spread, so the 5%/95% tails never collapse.
MIN_SIGMA = 0.05
# Centred moving-average window (hours) for smoothing the forecast in log space.
SMOOTH_WINDOW = 3
MAX_VIEWERS = 1_000_000_000.0
MIN_VIEWERS = 0.01


def round2(x: float) -> float | int:
    """x rounded to 2 decimals, half up (as JavaScript Math.round(x*100)/100)."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def _parse_ts(text):
    """Parse an ISO-8601 UTC timestamp; return None when unparseable."""
    try:
        from datetime import datetime, timezone
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return None


def _day_series(comp):
    """Release-day hourly viewers (hours 1..24) of a comparable, or None.

    A comparable is usable only when all 24 release-day hours are present
    and positive. This also drops the target game's own category history,
    which is not a launch day and has missing hours.
    """
    from datetime import timedelta
    day_start = _parse_ts(comp.get("day_start", ""))
    if day_start is None:
        return None
    by_from = {}
    for row in comp.get("hourly") or []:
        ts = _parse_ts(row.get("from", ""))
        if ts is not None and row.get("viewers") is not None:
            by_from[ts] = row["viewers"]
    series = []
    for h in range(24):
        value = by_from.get(day_start + timedelta(hours=h))
        if value is None or value <= 0:
            return None
        series.append(float(value))
    return series


def _has_pc(platforms):
    """True when a platforms string mentions PC."""
    return "PC" in (platforms or "").upper()


def _target_has_pc(case):
    """PC status of the target game, from its own category-history comparable.

    Returns True/False, or None when no comparable carries the target's name.
    """
    name = (case.get("game") or {}).get("name", "")
    if not name:
        return None
    for comp in case.get("comparables") or []:
        if name.lower() in (comp.get("name") or "").lower():
            return _has_pc(comp.get("platforms", ""))
    return None


def _build_pool(case):
    """Usable comparables: (log-ratio list, weight base data)."""
    pool = []
    for comp in case.get("comparables") or []:
        series = _day_series(comp)
        if series is None:
            continue
        p1 = series[0]
        pool.append({
            "p1": p1,
            "log_p1": math.log(p1),
            "pc": _has_pc(comp.get("platforms", "")),
            "lr": [math.log(v / p1) for v in series],
        })
    return pool


def _weighted_quantile(pairs, tau):
    """Weighted empirical quantile (midpoint cumulative weights, linear interp)."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return ordered[0][0]
    points = []
    cum = 0.0
    for value, weight in ordered:
        cum += weight
        points.append((cum - 0.5 * weight, value))
    target = tau * total
    if target <= points[0][0]:
        return points[0][1]
    if target >= points[-1][0]:
        return points[-1][1]
    for i in range(1, len(points)):
        if points[i][0] >= target:
            x0, y0 = points[i - 1]
            x1, y1 = points[i]
            if x1 == x0:
                return y1
            frac = (target - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return points[-1][1]


def _trimmed_mean(pairs, trim):
    """Weighted mean of the values between the trim and 1-trim weight quantiles."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return ordered[0][0]
    lo = trim * total
    hi = (1.0 - trim) * total
    acc = 0.0
    wsum = 0.0
    cum = 0.0
    for value, weight in ordered:
        seg_lo = max(cum, lo)
        seg_hi = min(cum + weight, hi)
        if seg_hi > seg_lo:
            acc += value * (seg_hi - seg_lo)
            wsum += seg_hi - seg_lo
        cum += weight
    if wsum <= 0:
        return _weighted_quantile(pairs, 0.5)
    return acc / wsum


def _hour_quantiles_log(pool, weights, hour, levels):
    """Log-space quantiles of hour `hour`'s ratio to hour 1, at `levels`."""
    pairs = [(c["lr"][hour - 1], w) for c, w in zip(pool, weights)]
    median = _trimmed_mean(pairs, TRIM)
    q25 = _weighted_quantile(pairs, 0.25)
    q75 = _weighted_quantile(pairs, 0.75)
    sigma = max((q75 - q25) / 1.3489795003921634, MIN_SIGMA)
    out = {}
    for tau in levels:
        if tau == 0.25:
            out[tau] = q25
        elif tau == 0.75:
            out[tau] = q75
        elif tau == 0.5:
            out[tau] = median
        else:
            out[tau] = median + _norm_ppf(tau) * sigma
    return out


def _smooth_log(rows, levels, window=SMOOTH_WINDOW):
    """Centred moving average of log values across neighbouring hours."""
    hours = sorted(rows)
    half = window // 2
    smoothed = {}
    for h in hours:
        lo = max(hours[0], h - half)
        hi = min(hours[-1], h + half)
        near = [hh for hh in hours if lo <= hh <= hi]
        smoothed[h] = {tau: sum(math.log(rows[hh][tau]) for hh in near) / len(near)
                       for tau in levels}
    return {h: {tau: math.exp(v) for tau, v in vals.items()}
            for h, vals in smoothed.items()}


def forecast_case(case, name):
    """Forecast hours 2..24 of one case as {"hours": [{hour, q: [...]}]}."""
    levels = list(case.get("levels") or LEVELS)
    # Any level in (0, 1) is forecastable; fall back to the scored five.
    levels = [tau for tau in levels if 0.0 < tau < 1.0] or list(LEVELS)
    first = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
    if first is not None and first.get("viewers") is not None:
        p1 = max(1.0, float(first["viewers"]))
    else:
        # No hour-1 print (should not happen in a valid case): fall back to
        # the last pre-checkpoint hourly point, else 1 viewer.
        hourly = case.get("history_hourly") or []
        p1 = 1.0
        if hourly:
            last = hourly[-1].get("viewers")
            if last is not None:
                p1 = max(1.0, float(last))

    pool = _build_pool(case)
    target_pc = _target_has_pc(case)
    log_p1 = math.log(p1)
    weights = []
    for comp in pool:
        d = comp["log_p1"] - log_p1
        w = math.exp(-((d / BANDWIDTH) ** 2))
        if target_pc is not None and comp["pc"] != target_pc:
            w *= CROSS_PC_WEIGHT
        weights.append(w)
    if not pool or sum(weights) <= 0:
        # No usable comparable: fall back to the house baseline's shape.
        return {"hours": [{"hour": row["hour"],
                           "q": [round2(p1 * math.exp(_norm_ppf(tau) * 0.15 * math.sqrt(row["hour"] - 1)))
                                 for tau in levels]}
                          for row in case["forecast"]]}

    rows = {}
    for row in case["forecast"]:
        h = row["hour"]
        log_q = _hour_quantiles_log(pool, weights, h, levels)
        rows[h] = {tau: p1 * math.exp(log_q[tau]) for tau in levels}
    rows = _smooth_log(rows, levels)

    hours = []
    for row in case["forecast"]:
        h = row["hour"]
        qs = []
        prev = None
        for tau in levels:
            value = round2(min(max(rows[h][tau], MIN_VIEWERS), MAX_VIEWERS))
            if prev is not None and value < prev:
                value = prev
            qs.append(value)
            prev = value
        hours.append({"hour": h, "q": qs})
    return {"hours": hours}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
