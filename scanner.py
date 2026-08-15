import os
import time
import requests
import pandas as pd
import yfinance as yf


# =========================================================
# SETTINGS
# =========================================================

# -------------------------
# SUPPORT
# -------------------------

SUPPORT_LOOKBACK = 50
SUPPORT_DISTANCE = 0.03       # Support ke ±3% area me


# -------------------------
# SCANNER
# -------------------------

BATCH_SIZE = 40
PERIOD = "6mo"


# -------------------------
# DAY-2 STRONG CANDLE
# -------------------------

MIN_BODY_RATIO = 0.50         # Body >= 50% candle range
MIN_CLOSE_POSITION = 0.65     # Close upper 35% area me
MIN_BODY_VS_DAY1 = 1.00       # Day-2 body >= Day-1 body


# -------------------------
# SLIGHT DOWNTREND
# -------------------------

MAX_BELOW_SMA20 = 0.08        # 20 SMA se maximum 8% neeche


# -------------------------
# TELEGRAM
# -------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")


# -------------------------
# NSE EQUITY LIST
# -------------------------

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


    # Retry system
    for attempt in range(5):

        try:

            response = requests.post(
                url,
                data=data,
                timeout=20
            )


            # -------------------------
            # SUCCESS
            # -------------------------

            if response.ok:

                print(
                    "Telegram: message sent"
                )

                return True


            # -------------------------
            # RATE LIMIT
            # -------------------------

            if response.status_code == 429:

                try:

                    retry_after = (
                        response.json()
                        .get("parameters", {})
                        .get("retry_after", 5)
                    )

                except Exception:

                    retry_after = 5


                print(
                    f"Telegram rate limit. "
                    f"Waiting {retry_after} seconds..."
                )


                time.sleep(
                    retry_after + 1
                )

                continue


            # -------------------------
            # OTHER ERROR
            # -------------------------

            print(
                "Telegram error:",
                response.status_code,
                response.text
            )

            return False


        except Exception as e:

            print(
                "Telegram connection error:",
                e
            )


            time.sleep(3)


    print(
        "Telegram failed after retries."
    )

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


    # -------------------------
    # SERIES COLUMN
    # -------------------------

    if " SERIES" in df.columns:

        series_col = " SERIES"

    elif "SERIES" in df.columns:

        series_col = "SERIES"

    else:

        raise ValueError(
            "NSE SERIES column not found."
        )


    # -------------------------
    # SYMBOL COLUMN
    # -------------------------

    if "SYMBOL" not in df.columns:

        raise ValueError(
            "NSE SYMBOL column not found."
        )


    # -------------------------
    # ONLY EQ
    # -------------------------

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


    # -------------------------
    # DAY-1
    # -------------------------

    o = float(
        df["Open"].iloc[i]
    )

    h = float(
        df["High"].iloc[i]
    )

    l = float(
        df["Low"].iloc[i]
    )

    c = float(
        df["Close"].iloc[i]
    )


    # -------------------------
    # PREVIOUS CANDLE
    # -------------------------

    po = float(
        df["Open"].iloc[i - 1]
    )

    pc = float(
        df["Close"].iloc[i - 1]
    )


    body = abs(c - o)

    candle_range = h - l


    if candle_range <= 0:

        return None


    # -------------------------
    # DAY-1 MUST BE GREEN
    # -------------------------

    if c <= o:

        return None


    upper_wick = (
        h - max(o, c)
    )

    lower_wick = (
        min(o, c) - l
    )


    previous_red = (
        pc < po
    )


    # =====================================================
    # BULLISH HAMMER
    # =====================================================

    hammer = (

        lower_wick >= body * 2

        and

        upper_wick <= max(
            body,
            candle_range * 0.10
        )

        and

        c > (
            l + candle_range * 0.55
        )
    )


    if hammer:

        return "Bullish Hammer"


    # =====================================================
    # BULLISH INVERTED HAMMER
    # =====================================================

    inverted_hammer = (

        upper_wick >= body * 2

        and

        lower_wick <= max(
            body,
            candle_range * 0.10
        )

        and

        c > (
            l + candle_range * 0.55
        )
    )


    if inverted_hammer:

        return "Bullish Inverted Hammer"


    # =====================================================
    # BULLISH ENGULFING
    # =====================================================

    bullish_engulfing = (

        previous_red

        and

        o <= pc

        and

        c >= po

        and

        c > o
    )


    if bullish_engulfing:

        return "Bullish Engulfing"


    # =====================================================
    # PIERCING PATTERN
    # =====================================================

    piercing = (

        previous_red

        and

        c > (
            po + pc
        ) / 2

        and

        c < po
    )


    if piercing:

        return "Piercing Pattern"


    # =====================================================
    # BULLISH HARAMI
    # =====================================================

    bullish_harami = (

        previous_red

        and

        o >= pc

        and

        c <= po

        and

        c > pc
    )


    if bullish_harami:

        return "Bullish Harami"


    # Doji rejected
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

    trend_down = (
        sma20 < sma50
    )


    # Price below 20 SMA

    below_sma20 = (
        current_close < sma20
    )


    # Not too far below

    distance_below = (
        (sma20 - current_close)
        / sma20
    )


    not_too_far = (
        distance_below
        <= MAX_BELOW_SMA20
    )


    return (
        trend_down
        and
        below_sma20
        and
        not_too_far
    )


# =========================================================
# SUPPORT CHECK
# =========================================================

def support_condition(df, prev):

    if prev < SUPPORT_LOOKBACK:

        return False, None


    # 50 candles BEFORE DAY-1

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


    upper = (
        support
        * (1 + SUPPORT_DISTANCE)
    )


    lower = (
        support
        * (1 - SUPPORT_DISTANCE)
    )


    near_support = (

        lower <= day1_low <= upper

        or

        lower <= day1_close <= upper
    )


    return (
        near_support,
        support
    )


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


    # -------------------------
    # DAY-2 MUST BE GREEN
    # -------------------------

    if day2_close <= day2_open:

        return False


    # -------------------------
    # BODY >= 50%
    # -------------------------

    body_ratio = (
        day2_body
        / day2_range
    )


    if body_ratio < MIN_BODY_RATIO:

        return False


    # -------------------------
    # CLOSE NEAR TOP
    # -------------------------

    close_position = (
        (day2_close - day2_low)
        / day2_range
    )


    if close_position < MIN_CLOSE_POSITION:

        return False


    # -------------------------
    # DAY-2 BODY >= DAY-1 BODY
    # -------------------------

    if day2_body < (
        day1_body
        * MIN_BODY_VS_DAY1
    ):

        return False


    return True


# =========================================================
# CHECK ONE STOCK
# =========================================================

def check_stock(symbol):

    ticker = (
        symbol
        + ".NS"
    )


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
        # IMPORTANT:
        #
        # LATEST CANDLE = DAY-3
        #
        # DAY-2 = SECOND LAST CANDLE
        #
        # DAY-1 = THIRD LAST CANDLE
        #
        # Example:
        #
        # 12 = Day-1
        # 13 = Day-2
        # 14 = Day-3 / IGNORED
        #
        # =================================================

        i = len(df) - 2

        prev = i - 1


        if prev < 1:

            return None


        # =================================================
        # DAY-1
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
        # DAY-1 PATTERN
        # =================================================

        pattern = candle_pattern(
            df,
            prev
        )


        if pattern is None:

            return None


        # =================================================
        # SUPPORT / DOWNTREND
        # =================================================

        near_support, support = (
            support_condition(
                df,
                prev
            )
        )


        downtrend = (
            is_slight_downtrend(
                df,
                prev
            )
        )


        # At least one required

        if (
            not near_support
            and
            not downtrend
        ):

            return None


        # =================================================
        # DAY-2
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
        # DAY-2 CLOSE > DAY-1 HIGH
        # =================================================

        if day2_close <= day1_high:

            return None


        # =================================================
        # ZONE
        # =================================================

        if (
            near_support
            and
            downtrend
        ):

            zone = (
                "Support + Slight Downtrend"
            )

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
        # DATES
        # =================================================

        day1_date = (
            pd.Timestamp(
                df.index[prev]
            ).strftime(
                "%d-%m-%Y"
            )
        )


        day2_date = (
            pd.Timestamp(
                df.index[i]
            ).strftime(
                "%d-%m-%Y"
            )
        )


        # =================================================
        # TELEGRAM MESSAGE
        #
        # NO ENTRY
        # NO SL
        # NO TP
        # =================================================

        message = (

            "🚨 BULLISH SETUP FOUND\n\n"

            f"📊 Stock: {symbol}\n"

            "⏱ Timeframe: 1D\n\n"

            f"🕯 Day-1: "
            f"{day1_date}\n"

            f"🕯 Day-1 Pattern: "
            f"{pattern}\n"

            f"📍 Zone: "
            f"{zone}\n"

            f"📍 Support: "
            f"{support_text}\n\n"

            f"📈 Day-1 High: "
            f"₹{day1_high:.2f}\n"

            f"📈 Day-2: "
            f"{day2_date}\n"

            f"📈 Day-2 High: "
            f"₹{day2_high:.2f}\n"

            f"✅ Day-2 Close: "
            f"₹{day2_close:.2f}\n\n"

            "💪 Day-2: STRONG GREEN\n"

            "✅ Day-2 Close > Day-1 High\n\n"

            "📌 Day-3 NOT INCLUDED"
        )


        return message


    except Exception as e:

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
    # NSE STOCK LIST
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
    # SCAN ALL STOCKS
    #
    # BATCH SIZE 40
    # SIGNAL LIMIT = NONE
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
                    "\n================================"
                )

                print(
                    "SIGNAL FOUND"
                )

                print(
                    result
                )

                print(
                    "================================"
                )


                signals.append(
                    result
                )


                # -----------------------------------------
                # EVERY SIGNAL WILL BE SENT
                # NO 5 SIGNAL LIMIT
                # -----------------------------------------

                send_telegram(
                    result
                )


                # -----------------------------------------
                # TELEGRAM SINGLE-CHAT RATE SAFETY
                # -----------------------------------------

                time.sleep(1.2)


            # Small scanner delay

            time.sleep(0.15)


        # Pause after batch

        time.sleep(2)


    # =====================================================
    # FINAL RESULT
    # =====================================================

    if not signals:


        print(
            "\nNo bullish setup found."
        )


        send_telegram(
            "📊 NSE Bullish Scanner\n\n"
            "No setup found today.\n"
            "No stock matched all conditions."
        )


    else:


        print(
            "\n========================================"
        )


        print(
            f"TOTAL VALID SETUPS: "
            f"{len(signals)}"
        )


        print(
            "========================================"
        )


    print(
        "\nScanner finished."
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()
