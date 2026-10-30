import pandas as pd
import pandas_ta as ta


def apply_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["EMA_21"] = ta.ema(df["close"], length=21)
    df["EMA_50"] = ta.ema(df["close"], length=50)
    df["RSI_14"] = ta.rsi(df["close"], length=14)

    # iloc avoids KeyError across pandas-ta versions that rename float suffixes (e.g. 2.0 vs 2.0_2.0)
    adx = ta.adx(df["high"], df["low"], df["close"], length=14)
    df["ADX_14"] = adx.iloc[:, 0]

    df["ATR_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    df["VOL_SMA_20"] = ta.sma(df["volume"], length=20)
    df["VOL_SMA_24"] = ta.sma(df["volume"], length=24)

    bb = ta.bbands(df["close"], length=20, std=2)
    df["BB_LOWER_20_2"] = bb.iloc[:, 0]
    df["BB_UPPER_20_2"] = bb.iloc[:, 2]

    df["SUPPORT_50"] = df["low"].rolling(50).min()
    df["RESISTANCE_50"] = df["high"].rolling(50).max()

    return df


if __name__ == "__main__":
    sample = pd.DataFrame({
        "open": range(100, 160),
        "high": range(102, 162),
        "low": range(98, 158),
        "close": range(101, 161),
        "volume": [1000.0] * 60,
    }, dtype=float)
    res = apply_indicators(sample)
    expected = [
        "EMA_21", "EMA_50", "RSI_14", "ADX_14", "ATR_14",
        "VOL_SMA_20", "VOL_SMA_24", "BB_UPPER_20_2", "BB_LOWER_20_2",
        "SUPPORT_50", "RESISTANCE_50",
    ]
    assert all(col in res.columns for col in expected), "Missing required indicator columns"
    assert not res[expected].iloc[-1].isna().any(), "Last row contains NaN values"
