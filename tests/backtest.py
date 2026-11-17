"""Leave-one-out backtest for the gta6-ccu-forecast model (stdlib only).

Treats each comparable launch in a kit practice case as a pseudo-target:
its hour-1 print is the only known, the OTHER comparables are the pool, and
its actual release-day hours 2..24 are the truth. Scores the mean pinball
loss on the log scale and compares it with the house baseline computed the
same way. Run from the repo root:

    python3 tests/backtest.py [path-to-kit-input-dir]

Defaults to the kit input dir used during development. Exits 0 when the
model beats the baseline overall and on the console-only, p1 >= 20k subset
(the launches most like the final: rolling-midnight console releases).
"""

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main as model  # noqa: E402

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]
KIT_INPUT = Path("/home/hatch/workspace/makefun/work/"
                 "gta6-twitch-ccu-forecast-01-kit/input")


def pinball(y, q, tau):
    d = math.log(max(y, 1)) - math.log(q)
    return 2 * max(tau * d, (tau - 1) * d)


def baseline_forecast(p1):
    return {h: [p1 * math.exp(z * 0.15 * math.sqrt(h - 1)) for z in Z]
            for h in range(2, 25)}


def score(forecast, actual):
    total = 0.0
    n = 0
    for h in range(2, 25):
        for tau, q in zip(LEVELS, forecast[h]):
            total += pinball(actual[h - 1], q, tau)
            n += 1
    return total / n


def load_pool(case_path):
    case = json.loads(Path(case_path).read_text(encoding="utf-8"))
    pool = []
    for comp in case["comparables"]:
        series = model._day_series(comp)
        if series is None:
            continue
        pool.append({"name": comp["name"], "series": series, "p1": series[0],
                     "pc": model._has_pc(comp.get("platforms", "")),
                     "lr": [math.log(v / series[0]) for v in series]})
    return pool


def forecast_for_target(p1, target_pc, pool):
    """Run the model's core on a pseudo-target (pool = other comparables)."""
    log_p1 = math.log(max(p1, 1))
    weights = []
    for comp in pool:
        d = math.log(max(comp["p1"], 1)) - log_p1
        w = math.exp(-((d / model.BANDWIDTH) ** 2))
        if target_pc is not None and comp["pc"] != target_pc:
            w *= model.CROSS_PC_WEIGHT
        weights.append(w)
    rows = {}
    for h in range(2, 25):
        log_q = model._hour_quantiles_log(pool, weights, h, LEVELS)
        rows[h] = {tau: p1 * math.exp(log_q[tau]) for tau in LEVELS}
    rows = model._smooth_log(rows, LEVELS)
    return {h: [rows[h][tau] for tau in LEVELS] for h in range(2, 25)}


def main():
    kit = Path(sys.argv[1]) if len(sys.argv) > 1 else KIT_INPUT
    case_path = kit / "p00.in"
    pool = load_pool(case_path)
    print(f"pool: {len(pool)} comparable launches with complete release days")

    results = []
    covered = 0
    scored_hours = 0
    for i, target in enumerate(pool):
        others = pool[:i] + pool[i + 1:]
        fc = forecast_for_target(target["p1"], target["pc"], others)
        base = baseline_forecast(target["p1"])
        for h in range(2, 25):
            if fc[h][0] <= target["series"][h - 1] <= fc[h][4]:
                covered += 1
            scored_hours += 1
        results.append((target["name"], target["p1"], target["pc"],
                        score(fc, target["series"]),
                        score(base, target["series"])))
    results.sort(key=lambda r: r[3])

    def report(subset, label):
        rows = [r for r in results if subset(r)]
        m = sum(r[3] for r in rows) / len(rows)
        b = sum(r[4] for r in rows) / len(rows)
        print(f"{label}: n={len(rows)} model={m:.4f} baseline={b:.4f} "
              f"improvement={(b - m) / b * 100:.1f}%")
        return m, b

    report(lambda r: True, "overall")
    report(lambda r: not r[2] and r[1] >= 20000,
           "console-only, p1 >= 20k (most like GTA VI)")
    report(lambda r: r[1] >= 50000, "p1 >= 50k")
    print(f"90% coverage: {covered / scored_hours:.3f} (target ~0.90)")
    print()
    print("per-target (best first):")
    for name, p1, pc, m, b in results:
        print(f"  {name[:32]:34s} p1={int(p1):7d} pc={int(pc)} "
              f"model={m:.4f} baseline={b:.4f}")

    overall_m = sum(r[3] for r in results) / len(results)
    overall_b = sum(r[4] for r in results) / len(results)
    console = [r for r in results if not r[2] and r[1] >= 20000]
    console_m = sum(r[3] for r in console) / len(console)
    console_b = sum(r[4] for r in console) / len(console)
    ok = overall_m < overall_b and console_m < console_b
    print()
    print("PASS" if ok else "FAIL",
          f"(model {overall_m:.4f} vs baseline {overall_b:.4f} overall; "
          f"console {console_m:.4f} vs {console_b:.4f})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
