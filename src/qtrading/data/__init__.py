"""Market data: Binance (crypto), Yahoo Finance (stock underlyings), cached and aligned to an hourly UTC grid.

Convention used throughout: a bar is indexed by its CLOSE time — the moment its close price became
known. This makes look-ahead impossible by construction: at grid time T you may use any bar with index <= T.
"""
