# Combined Quant V3 dashboard

Open http://127.0.0.1:5001/. The original dashboard remains at `/legacy`.

| View | Information |
| --- | --- |
| Overview | Today's confirmed slots, dated watchlist, coverage, evidence, feed availability |
| Markets & news | Cached indices and FX, covered-universe gainers and losers, sector averages, dated macro observations, sourced news |
| Watchlist | Searchable research candidates, volatility, turnover, scores, rejection counts, stock details |
| Position tracking | Quant V3 paper entries, partial fills, remaining quantity and resolved returns |
| Performance | Closed-fill equity and drawdown; searchable history with separate Quant and legacy filters |
| Learning & research | Model evaluations and baseline comparisons, forward evidence, saved legacy report availability and pattern statistics |
| System health | Runtime, data freshness, coverage, provider checks, recorded API usage and observation activity |

Stock buttons open the last cached intraday session's candle chart, recorded features and historical outcome counts. These observations can overlap and are not independent trades.

Historical context loads independently of today's official slots. Old picks never populate today's slots. Missing values are shown as unavailable, and no synthetic index prices or event calendar are generated. Daily market snapshots are dated daily candles, not streaming quotes. Market refresh runs in a bounded subprocess outside the request path, at most once per five minutes per dashboard process. Core state refreshes every 15 seconds; broader context refreshes every 60 seconds.

The equity curve uses resolved Quant V3 fills, allocating one-third of starting daily capital per slot. It excludes open-position mark-to-market. Legacy outcomes do not enter Quant V3 performance. Legacy report availability does not make those agents part of the Quant V3 decision engine.

Run `python -m pytest tests/test_quant_dashboard.py tests/test_quant_v3.py -q` for dashboard data and Quant V3 regression checks. Dashboard endpoints are read-only; existing scheduler controls retain their protected POST route.
