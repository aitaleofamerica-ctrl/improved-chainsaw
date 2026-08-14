import os
import time
import requests
import pandas as pd
import yfinance as yf

# =========================
# SETTINGS
# =========================

SUPPORT_LOOKBACK = 50
SUPPORT_DISTANCE = 0.03       # Support ke aas-paas ±3%
BATCH_SIZE = 40
PERIOD = "3mo"

ENTRY_BUFFER = 0.005          # Day-2 High + 0.5%

# Day-2 strength
MIN_BODY_RATIO = 0.50         # Candle range ka minimum 50% body
MIN_CLOSE_POSITION = 0.65     # Close range ke upper 35% me
MIN_BODY_VS_DAY1 = 1.00       # Day-2 body >= Day-1 body

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

NSE_LIST_URL = (
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
)


# =========================
# TELEGRAM
# =========================

def send_telegram(message):

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram secrets missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

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

    except Exception as e:
        print("Telegram error:", e)


# =========================
# GET NSE STOCK LIST
# =========================

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

    if " SERIES" in df.columns:

        df = df[
            df[" SERIES"].astype(str).str.strip() == "EQ"
        ]

    elif "SERIES" in df.columns:

        df = df[
            df["SERIES"].astype(str).str.strip() == "EQ"
        ]

    symbol_col = "SYMBOL"

    symbols = (
        df[symbol_col]
        .astype(str)
        .str.strip()
        .dropna()
        .unique()
        .tolist()
    )

    return symbols


# =========================
# CANDLE PATTERN
# =========================

def candle_pattern(df, i):

    if i < 1:
        return None

    o = float(df["Open"].iloc[i])
    h = float(df["High"].iloc[i])
    l = float(df["Low"].iloc[i])
    c = float(df["Close"].iloc[i])

    po = float(df["Open"].iloc[i - 1])
    ph = float(df["High"].iloc[i - 1])
    pl = float(df["Low"].iloc[i - 1])
    pc = float(df["Close"].iloc[i - 1])

    body = abs(c - o)
    candle_range = h - l

    if candle_range <= 0:
        return None

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    green = c > o
    previous_red = pc < po

    # =========================
    # HAMMER
    # =========================

    hammer = (
        lower_wick >= body * 2
        and upper_wick <= max(body, candle_range * 0.10)
        and c > l + candle_range * 0.55
    )

    if hammer:
        return "Hammer"

    # =========================
    # INVERTED HAMMER
    # =========================

    inverted_hammer = (
        upper_wick >= body * 2
        and lower_wick <= max(body, candle_range * 0.10)
        and c > l + candle_range * 0.55
    )

    if inverted_hammer:
        return "Inverted Hammer"

    # =========================
    # BULLISH ENGULFING
    # =========================

    bullish_engulfing = (
        previous_red
        and green
        and o <= pc
        and c >= po
        and c > o
    )

    if bullish_engulfing:
        return "Bullish Engulfing"

    # =========================
    # PIERCING
    # =========================

    piercing = (
        previous_red
        and green
        and c > (po + pc) / 2
        and c < po
    )

    if piercing:
        return "Piercing Pattern"

    # =========================
    # BULLISH HARAMI
    # =========================

    bullish_harami = (
        previous_red
        and green
        and o >= pc
        and c <= po
        and c > pc
    )

    if bullish_harami:
        return "Bullish Harami"

    # IMPORTANT:
    # Doji ko setup candle nahi banana
    # =========================

    return None


# =========================
# DOWN TREND CHECK
# =========================

def is_downtrend(df, i):

    if i < 50:
        return False

    close = df["Close"]

    sma20 = close.iloc[i - 19:i + 1].mean()
    sma50 = close.iloc[i - 49:i + 1].mean()

    current_close = float(close.iloc[i])

    # Slight downtrend:
    # 20 DMA below 50 DMA
    # aur price 20 DMA ke neeche
    downtrend = (
        sma20 < sma50
        and current_close < sma20
    )

    return downtrend


# =========================
# SUPPORT CHECK
# =========================

def support_condition(df, prev):

    if prev < SUPPORT_LOOKBACK:
        return False, None

    # Day-1 se pehle ke 50 candles ka support
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

    # Support ke paas / thoda neeche
    support_upper = support * (1 + SUPPORT_DISTANCE)
    support_lower = support * (1 - SUPPORT_DISTANCE)

    near_support = (
        support_lower <= day1_low <= support_upper
        or
        support_lower <= day1_close <= support_upper
    )

    return near_support, support


# =========================
# STRONG DAY-2 CHECK
# =========================

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

    # Green compulsory
    if day2_close <= day2_open:
        return False

    # Day-2 body minimum 50% of candle range
    body_ratio = (
        day2_body / day2_range
    )

    if body_ratio < MIN_BODY_RATIO:
        return False

    # Close upper part of candle
    close_position = (
        (day2_close - day2_low)
        / day2_range
    )

    if close_position < MIN_CLOSE_POSITION:
        return False

    # Day-2 body Day-1 se weak nahi honi chahiye
    if day2_body < day1_body * MIN_BODY_VS_DAY1:
        return False

    return True


# =========================
# CHECK ONE STOCK
# =========================

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

        # Multi-index handle
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

        # =========================
        # DAY-2 = CURRENT CLOSED DAY
        # DAY-1 = PREVIOUS DAY
        # =========================

        i = len(df) - 1
        prev = i - 1

        # =========================
        # DAY-1 VALUES
        # =========================

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

        # =========================
        # DAY-1 BULLISH REVERSAL
        # =========================

        pattern = candle_pattern(
            df,
            prev
        )

        if pattern is None:
            return None

        # =========================
        # SUPPORT OR DOWNTREND
        # =========================

        near_support, support = (
            support_condition(
                df,
                prev
            )
        )

        downtrend = is_downtrend(
            df,
            prev
        )

        # Dono me se koi ek compulsory
        if not near_support and not downtrend:
            return None

        # =========================
        # DAY-2
        # =========================

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

        # =========================
        # DAY-2 STRONG
        # =========================

        if not strong_day2(
            day1_open,
            day1_close,
            day2_open,
            day2_high,
            day2_low,
            day2_close
        ):
            return None

        # =========================
        # DAY-2 CLOSE MUST BE
        # ABOVE DAY-1 HIGH
        # =========================

        if day2_close <= day1_high:
            return None

        # =========================
        # ENTRY = DAY-2 HIGH + 0.5%
        # =========================

        bp = day2_high * (
            1 + ENTRY_BUFFER
        )

        # =========================
        # STOP LOSS
        # =========================

        sl = day1_low

        risk = bp - sl

        if risk <= 0:
            return None

        # =========================
        # TARGETS
        # =========================

        tp1 = bp + (
            risk * 2
        )

        tp2 = bp + (
            risk * 3
        )

        # =========================
        # TREND / SUPPORT TYPE
        # =========================

        if near_support and downtrend:
            zone = "Support + Downtrend"

        elif near_support:
            zone = "Support Zone"

        else:
            zone = "Downtrend"

        date = df.index[i]

        # =========================
        # TELEGRAM MESSAGE
        # =========================

        message = (
            "🚨 BULLISH SETUP FOUND\n\n"

            f"📊 Stock: {symbol}\n"
            f"⏱ Timeframe: 1D\n"
            f"📅 Confirmation: "
            f"{date.strftime('%d-%m-%Y')}\n\n"

            f"🕯 Day-1 Pattern: {pattern}\n"
            f"📍 Zone: {zone}\n"
            f"📍 Support: ₹{support:.2f}\n\n"

            f"📈 Day-1 High: ₹{day1_high:.2f}\n"
            f"📈 Day-2 High: ₹{day2_high:.2f}\n"
            f"✅ Day-2 Close: ₹{day2_close:.2f}\n\n"

            f"🟢 ENTRY / BUY: ₹{bp:.2f}\n"
            f"🛑 SL: ₹{sl:.2f}\n"
            f"🎯 TP1: ₹{tp1:.2f} (1:2)\n"
            f"🎯 TP2: ₹{tp2:.2f} (1:3)\n\n"

            f"💰 Risk: ₹{risk:.2f}\n"
            f"💪 Day-2: STRONG GREEN\n"
            f"✅ Close > Day-1 High"
        )

        return message

    except Exception as e:

        print(
            f"{symbol}: error -> {e}"
        )

        return None


# =========================
# MAIN SCANNER
# =========================

def main():

    print(
        "Starting NSE Bullish Scanner..."
    )

    symbols = get_nse_stocks()

    print(
        f"Total NSE EQ stocks: "
        f"{len(symbols)}"
    )

    signals = []

    # IMPORTANT:
    # No maximum signal limit
    # Jitne match honge sab send honge

    for start in range(
        0,
        len(symbols),
        BATCH_SIZE
    ):

        batch = symbols[
            start:start + BATCH_SIZE
        ]

        print(
            f"Scanning "
            f"{start + 1} - "
            f"{min(start + BATCH_SIZE, len(symbols))}"
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

                send_telegram(
                    result
                )

            time.sleep(0.15)

        # Small pause
        time.sleep(2)

    # =========================
    # NO SIGNAL
    # =========================

    if not signals:

        print(
            "No bullish setup found."
        )

        send_telegram(
            "📊 NSE Bullish Scanner\n\n"
            "No setup found today.\n"
            "No stock matched all conditions."
        )

    else:

        print(
            f"\nTotal signals found: "
            f"{len(signals)}"
        )

    print(
        "\nScanner finished."
    )


if __name__ == "__main__":
    main()
