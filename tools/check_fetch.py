import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.fetch import fetch_ohlcv
import pandas as pd

for s in ['RELIANCE','TCS']:
    df = fetch_ohlcv(s, period='2y')
    print(s, '->', 'None' if df is None else f'{len(df)} rows')
