# GTA VI launch-day Twitch viewers — hour-by-hour forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Nugroho281/gta6-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Nugroho281/gta6-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Entry for [gta6-twitch-ccu-forecast-01](https://make.fun/?ref=scz7tdtw) on
[make.fun](https://make.fun/?ref=scz7tdtw): forecast how many people watch
Grand Theft Auto VI live on Twitch in each hour of its release day,
2026-11-19 (UTC), after the first — five quantiles (5%, 25%, 50%, 75%, 95%)
for each of hours 2..24.

## Model

For every comparable past launch, take its release-day hourly series and
normalise it by its own hour-1 print: `lr_h = ln(viewers_h / viewers_1)`.
For the target case, weight each comparable by how close its hour-1 print is
to the target's (Gaussian kernel on log viewers, bandwidth 1.5), and
downweight by 0.15 when its platform mix differs from the target's on PC —
a PC launch usually unlocked globally at one time, so its hour 1 already
holds most of the world, while a console-only rolling-midnight launch like
GTA VI keeps growing as the Americas unlock later in the day. The target's
own platform mix is read from the comparable carrying the target game's name
(the GTA VI category's own history entry).

Per hour, the median is the 10%-trimmed weighted mean of the log-ratios,
the interquartile range comes from weighted empirical quantiles, and the
5%/95% tails are median ± 1.645 × IQR/1.349 (a normal tail on a robust
spread). The 23 hourly rows are smoothed with a centred 3-hour moving
average in log space. Forecasts are `q = p1 * exp(lr)`, rounded half-up to
2 decimals, clamped to (0, 1e9] and non-decreasing.

Backtest (leave-one-out over the 37 comparable launches with complete
release days; `python3 tests/backtest.py`): **mean pinball loss 0.3825 vs
house baseline 0.9297** overall, and **0.1793 vs 0.2828** on console-only
launches with hour-1 prints ≥ 20k — the launches most like GTA VI.
90% coverage 0.870 (target ~0.90).

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only — no network, no third-party packages,
no randomness, no wall clock: two runs on the same case are byte-identical.
Runs in ~0.1 s per case (limit 8 s).

---

<sub>Entered on [make.fun](https://make.fun/?ref=scz7tdtw&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
