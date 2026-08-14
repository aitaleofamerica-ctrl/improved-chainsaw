import os
import time
import requests
import pandas as pd
import yfinance as yf


# =========================================================
# SETTINGS
# =========================================================

# Support
SUPPORT_LOOKBACK = 50
SUPPORT_DISTANCE = 0.03       # Support ke ±3% area me

# Scanner
BATCH_SIZE = 40               # ONLY scan batches - NOT signal limit
PERIOD = "6mo"

# Entry
ENTRY_BUFFER = 0.005          # Day-2 High + 0.5%

# Day-2 strong candle
MIN_BODY_RATIO = 0.50         # Body >= 50% of candle range
MIN_CLOSE_POSITION = 0.65     # Close upper 35% area me
MIN_BODY_VS_DAY1 = 1.00       # Day-2 body >= Day-1 body

# Slight downtrend
MAX_BELOW_SMA20 = 0.08        # 20 SMA se maximum 8% neeche

# Telegram
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# NSE official equity list
NSE_LIST_URL = (
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
)


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram secrets missing.")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    data = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:
        response = requests.post(
            url,
            data=data,
            timeout=20
        )

        print("Telegram:", response.status_code)

        return response.ok

    except Exception as e:
        print("Telegram error:", e)
        return False


# =========================================================
# GET NSE EQUITY STOCK LIST
# =========================================================

def get_nse_stocks():

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,*/*"
    }

    response = requests.get(
        NSE_LIST_URL,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    from io import StringIO

    df = pd.read_csv(
        StringIO(response.text)
    )

    # NSE column-name variations
    if " SERIES" in df.columns:

        series_col = " SERIES"

    elif "SERIES" in df.columns:

        series_col = "SERIES"

    else:

        raise ValueError(
            "NSE SERIES column not found."
        )

    if "SYMBOL" not in df.columns:

        raise ValueError(
            "NSE SYMBOL column not found."
        )

    # Only normal equity stocks
    df = df[
        df[series_col]
        .astype(str)
        .str.strip()
        .eq("EQ")
    ]

    symbols = (
        df["SYMBOL"]
        .astype(str)
        .str.strip()
        .dropna()
        .unique()
        .tolist()
    )

    return symbols


# =========================================================
# DAY-1 BULLISH PATTERN
# =========================================================

def candle_pattern(df, i):

    if i < 1:
        return None

    # Day-1
    o = float(df["Open"].iloc[i])
    h = float(df["High"].iloc[i])
    l = float(df["Low"].iloc[i])
    c = float(df["Close"].iloc[i])

    # Candle before Day-1
    po = float(df["Open"].iloc[i - 1])
    pc = float(df["Close"].iloc[i - 1])

    body = abs(c - o)
    candle_range = h - l

    if candle_range <= 0:
        return None

    # Day-1 MUST be bullish/green
    if c <= o:
        return None

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    previous_red = pc < po

    # =====================================================
    # BULLISH HAMMER
    # =====================================================

    hammer = (
        lower_wick >= body * 2
        and upper_wick <= max(
            body,
            candle_range * 0.10
        )
        and c > l + candle_range * 0.55
    )

    if hammer:
        return "Bullish Hammer"

    # =====================================================
    # BULLISH INVERTED HAMMER
    # =====================================================

    inverted_hammer = (
        upper_wick >= body * 2
        and lower_wick <= max(
            body,
            candle_range * 0.10
        )
        and c > l + candle_range * 0.55
    )

    if inverted_hammer:
        return "Bullish Inverted Hammer"

    # =====================================================
    # BULLISH ENGULFING
    # =====================================================

    bullish_engulfing = (
        previous_red
        and o <= pc
        and c >= po
        and c > o
    )

    if bullish_engulfing:
        return "Bullish Engulfing"

    # =====================================================
    # PIERCING PATTERN
    # =====================================================

    piercing = (
        previous_red
        and c > (po + pc) / 2
        and c < po
    )

    if piercing:
        return "Piercing Pattern"

    # =====================================================
    # BULLISH HARAMI
    # =====================================================

    bullish_harami = (
        previous_red
        and o >= pc
        and c <= po
        and c > pc
    )

    if bullish_harami:
        return "Bullish Harami"

    # Doji intentionally rejected
    return None


# =========================================================
# SLIGHT DOWNTREND CHECK
# =========================================================

def is_slight_downtrend(df, i):

    if i < 50:
        return False

    close = df["Close"]

    sma20 = float(
        close.iloc[i - 19:i + 1].mean()
    )

    sma50 = float(
        close.iloc[i - 49:i + 1].mean()
    )

    current_close = float(
        close.iloc[i]
    )

    if sma20 <= 0:
        return False

    # 20 SMA below 50 SMA
    trend_down = sma20 < sma50

    # Price is below 20 SMA
    below_sma20 = current_close < sma20

    # But not TOO far below it
    distance_below = (
        (sma20 - current_close) / sma20
    )

    not_too_far = (
        distance_below <= MAX_BELOW_SMA20
    )

    return (
        trend_down
        and below_sma20
        and not_too_far
    )


# =========================================================
# SUPPORT CHECK
# =========================================================

def support_condition(df, prev):

    if prev < SUPPORT_LOOKBACK:
        return False, None

    # 50 candles BEFORE Day-1
    support = float(
        df["Low"].iloc[
            prev - SUPPORT_LOOKBACK:prev
        ].min()
    )

    day1_low = float(
        df["Low"].iloc[prev]
    )

    day1_close = float(
        df["Close"].iloc[prev]
    )

    upper = support * (
        1 + SUPPORT_DISTANCE
    )

    lower = support * (
        1 - SUPPORT_DISTANCE
    )

    near_support = (
        lower <= day1_low <= upper
        or
        lower <= day1_close <= upper
    )

    return near_support, support


# =========================================================
# STRONG DAY-2 CHECK
# =========================================================

def strong_day2(
    day1_open,
    day1_close,
    day2_open,
    day2_high,
    day2_low,
    day2_close
):

    day1_body = abs(
        day1_close - day1_open
    )

    day2_body = abs(
        day2_close - day2_open
    )

    day2_range = (
        day2_high - day2_low
    )

    if day2_range <= 0:
        return False

    # =====================================================
    # DAY-2 MUST BE GREEN
    # =====================================================

    if day2_close <= day2_open:
        return False

    # =====================================================
    # DAY-2 BODY MUST BE STRONG
    # =====================================================

    body_ratio = (
        day2_body / day2_range
    )

    if body_ratio < MIN_BODY_RATIO:
        return False

    # =====================================================
    # DAY-2 CLOSE MUST BE NEAR TOP
    # =====================================================

    close_position = (
        (day2_close - day2_low)
        / day2_range
    )

    if close_position < MIN_CLOSE_POSITION:
        return False

    # =====================================================
    # DAY-2 BODY MUST NOT BE WEAKER THAN DAY-1
    # =====================================================

    if day2_body < (
        day1_body * MIN_BODY_VS_DAY1
    ):
        return False

    return True


# =========================================================
# CHECK ONE STOCK
# =========================================================

def check_stock(symbol):

    ticker = symbol + ".NS"

    try:

        df = yf.download(
            ticker,
            period=PERIOD,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False
        )

        if df is None or df.empty:
            return None

        # =================================================
        # YFINANCE MULTI-INDEX
        # =================================================

        if isinstance(
            df.columns,
            pd.MultiIndex
        ):

            df.columns = (
                df.columns
                .get_level_values(0)
            )

        required = [
            "Open",
            "High",
            "Low",
            "Close"
        ]

        for col in required:

            if col not in df.columns:
                return None

        df = df.dropna(
            subset=required
        )

        if len(df) < 60:
            return None

        # =================================================
        # LAST COMPLETED DAILY CANDLE
        # =================================================

        # At 5 PM after market close,
        # latest daily candle should be completed.
        #
        # We also make sure the date is not a future date.

        today = pd.Timestamp.now().normalize()

        valid_rows = df[
            pd.to_datetime(
                df.index
            ).normalize() <= today
        ]

        if valid_rows.empty:
            return None

        df = valid_rows

        # Day-2 = latest available completed daily candle
        i = len(df) - 1

        # Day-1 = candle immediately before Day-2
        prev = i - 1

        if prev < 1:
            return None

        # =================================================
        # DAY-1 VALUES
        # =================================================

        day1_open = float(
            df["Open"].iloc[prev]
        )

        day1_high = float(
            df["High"].iloc[prev]
        )

        day1_low = float(
            df["Low"].iloc[prev]
        )

        day1_close = float(
            df["Close"].iloc[prev]
        )

        # =================================================
        # DAY-1 BULLISH SETUP
        # =================================================

        pattern = candle_pattern(
            df,
            prev
        )

        if pattern is None:
            return None

        # =================================================
        # SUPPORT OR SLIGHT DOWNTREND
        # =================================================

        near_support, support = (
            support_condition(
                df,
                prev
            )
        )

        downtrend = is_slight_downtrend(
            df,
            prev
        )

        # At least ONE condition required
        if not near_support and not downtrend:
            return None

        # =================================================
        # DAY-2 VALUES
        # =================================================

        day2_open = float(
            df["Open"].iloc[i]
        )

        day2_high = float(
            df["High"].iloc[i]
        )

        day2_low = float(
            df["Low"].iloc[i]
        )

        day2_close = float(
            df["Close"].iloc[i]
        )

        # =================================================
        # DAY-2 STRONG GREEN
        # =================================================

        if not strong_day2(
            day1_open,
            day1_close,
            day2_open,
            day2_high,
            day2_low,
            day2_close
        ):
            return None

        # =================================================
        # MOST IMPORTANT CONFIRMATION
        #
        # Day-2 CLOSE > Day-1 HIGH
        # =================================================

        if day2_close <= day1_high:
            return None

        # =================================================
        # ENTRY
        #
        # Day-2 High + 0.5%
        # =================================================

        entry = day2_high * (
            1 + ENTRY_BUFFER
        )

        # =================================================
        # STOP LOSS
        #
        # Day-1 Low
        # =================================================

        sl = day1_low

        risk = entry - sl

        if risk <= 0:
            return None

        # =================================================
        # TARGETS
        # =================================================

        tp1 = entry + (
            risk * 2
        )

        tp2 = entry + (
            risk * 3
        )

        # =================================================
        # ZONE
        # =================================================

        if near_support and downtrend:

            zone = "Support + Slight Downtrend"

        elif near_support:

            zone = "Support Zone"

        else:

            zone = "Slight Downtrend"

        # =================================================
        # SUPPORT TEXT
        # =================================================

        if support is not None:

            support_text = (
                f"₹{support:.2f}"
            )

        else:

            support_text = "N/A"

        # =================================================
        # DATE
        # =================================================

        date = df.index[i]

        try:

            confirmation_date = (
                pd.Timestamp(date)
                .strftime("%d-%m-%Y")
            )

        except Exception:

            confirmation_date = str(date)

        # =================================================
        # TELEGRAM MESSAGE
        # =================================================

        message = (
            "🚨 BULLISH SETUP FOUND\n\n"

            f"📊 Stock: {symbol}\n"
            f"⏱ Timeframe: 1D\n"
            f"📅 Confirmation: "
            f"{confirmation_date}\n\n"

            f"🕯 Day-1 Pattern: "
            f"{pattern}\n"

            f"📍 Zone: "
            f"{zone}\n"

            f"📍 Support: "
            f"{support_text}\n\n"

            f"📈 Day-1 High: "
            f"₹{day1_high:.2f}\n"

            f"📈 Day-2 High: "
            f"₹{day2_high:.2f}\n"

            f"✅ Day-2 Close: "
            f"₹{day2_close:.2f}\n\n"

            f"🟢 ENTRY: "
            f"₹{entry:.2f}\n"

            f"🛑 SL: "
            f"₹{sl:.2f}\n"

            f"🎯 TP1: "
            f"₹{tp1:.2f} (1:2)\n"

            f"🎯 TP2: "
            f"₹{tp2:.2f} (1:3)\n\n"

            f"💰 Risk/Share: "
            f"₹{risk:.2f}\n"

            f"💪 Day-2: STRONG GREEN\n"

            f"✅ Day-2 Close > "
            f"Day-1 High"
        )

        return message

    except Exception as e:

        # One stock fail hone par
        # scanner band nahi hoga
        print(
            f"{symbol}: error -> {e}"
        )

        return None


# =========================================================
# MAIN SCANNER
# =========================================================

def main():

    print(
        "========================================"
    )

    print(
        "Starting NSE Bullish Scanner..."
    )

    print(
        "========================================"
    )

    # =====================================================
    # GET ALL NSE EQ STOCKS
    # =====================================================

    try:

        symbols = get_nse_stocks()

    except Exception as e:

        print(
            "NSE stock list error:",
            e
        )

        send_telegram(
            "❌ NSE Bullish Scanner\n\n"
            "Scanner could not load NSE stock list."
        )

        return

    print(
        f"Total NSE EQ stocks: "
        f"{len(symbols)}"
    )

    signals = []

    # =====================================================
    # NO SIGNAL MAXIMUM
    #
    # 40 = BATCH SIZE ONLY
    # =====================================================

    for start in range(
        0,
        len(symbols),
        BATCH_SIZE
    ):

        batch = symbols[
            start:start + BATCH_SIZE
        ]

        end_number = min(
            start + BATCH_SIZE,
            len(symbols)
        )

        print(
            f"\nScanning "
            f"{start + 1} - "
            f"{end_number}"
        )

        for symbol in batch:

            result = check_stock(
                symbol
            )

            if result:

                print(
                    "\nSIGNAL FOUND:"
                )

                print(result)

                signals.append(
                    result
                )

                # Every valid signal
                # goes to Telegram
                send_telegram(
                    result
                )

            # Small delay
            time.sleep(0.15)

        # Pause after each batch
        time.sleep(2)

    # =====================================================
    # NO SIGNAL
    # =====================================================

    if not signals:

        print(
            "\nNo bullish setup found today."
        )

        send_telegram(
            "📊 NSE Bullish Scanner\n\n"
            "No setup found today.\n"
            "No stock matched all conditions."
        )

    else:

        print(
            f"\nTotal valid setups found: "
            f"{len(signals)}"
        )

    print(
        "\n========================================"
    )

    print(
        "Scanner finished."
    )

    print(
        "========================================"
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
