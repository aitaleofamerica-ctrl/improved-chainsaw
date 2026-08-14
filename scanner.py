import os
import time
import requests
import pandas as pd
import yfinance as yf

# =========================
# SETTINGS
# =========================

SUPPORT_LOOKBACK = 50
SUPPORT_DISTANCE = 0.03       # 3%
BATCH_SIZE = 40
PERIOD = "3mo"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# NSE official equity securities list
NSE_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"


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
        response = requests.post(url, data=data, timeout=20)
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

    df = pd.read_csv(StringIO(response.text))

    # Only normal equity series
    if " SERIES" in df.columns:
        df = df[df[" SERIES"].astype(str).str.strip() == "EQ"]
        symbol_col = "SYMBOL"
    elif "SERIES" in df.columns:
        df = df[df["SERIES"].astype(str).str.strip() == "EQ"]
        symbol_col = "SYMBOL"
    else:
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
# CANDLE PATTERNS
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

    # 1. Hammer
    hammer = (
        lower_wick >= body * 2
        and upper_wick <= max(body, candle_range * 0.10)
        and c > l + candle_range * 0.55
    )

    if hammer:
        return "Hammer"

    # 2. Inverted Hammer
    inverted_hammer = (
        upper_wick >= body * 2
        and lower_wick <= max(body, candle_range * 0.10)
        and c > l + candle_range * 0.55
    )

    if inverted_hammer:
        return "Inverted Hammer"

    # 3. Bullish Engulfing
    bullish_engulfing = (
        previous_red
        and green
        and o <= pc
        and c >= po
        and c > o
    )

    if bullish_engulfing:
        return "Bullish Engulfing"

    # 4. Piercing Pattern
    piercing = (
        previous_red
        and green
        and c > (po + pc) / 2
        and c < po
    )

    if piercing:
        return "Piercing Pattern"

    # 5. Bullish Harami
    bullish_harami = (
        previous_red
        and green
        and o >= pc
        and c <= po
        and c > pc
    )

    if bullish_harami:
        return "Bullish Harami"

    # 6. Dragonfly Doji
    dragonfly_doji = (
        body <= candle_range * 0.15
        and lower_wick >= candle_range * 0.60
        and upper_wick <= candle_range * 0.15
    )

    if dragonfly_doji:
        return "Dragonfly Doji"

    return None


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

        # Handle yfinance multi-index columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close"]

        for col in required:
            if col not in df.columns:
                return None

        df = df.dropna(subset=required)

        if len(df) < SUPPORT_LOOKBACK + 2:
            return None

        # Current candle = Day 2
        i = len(df) - 1

        # Previous candle = Day 1
        prev = i - 1

        # Day 1 reversal candle
        pattern = candle_pattern(df, prev)

        if pattern is None:
            return None

        # Day 1 support
        support = float(
            df["Low"].iloc[prev - SUPPORT_LOOKBACK + 1:prev + 1].min()
        )

        day1_close = float(df["Close"].iloc[prev])

        near_support = day1_close <= support * (1 + SUPPORT_DISTANCE)

        if not near_support:
            return None

        # Day 2 values
        day2_open = float(df["Open"].iloc[i])
        day2_high = float(df["High"].iloc[i])
        day2_low = float(df["Low"].iloc[i])
        day2_close = float(df["Close"].iloc[i])

        # Day 2 MUST be green
        if day2_close <= day2_open:
            return None

        # Day 2 MUST close above Day 1 reversal candle high
        day1_high = float(df["High"].iloc[prev])

        if day2_close <= day1_high:
            return None

        # =========================
        # BP / SL / TARGETS
        # =========================

        bp = day2_close

        day1_low = float(df["Low"].iloc[prev])

        sl = day1_low

        risk = bp - sl

        if risk <= 0:
            return None

        tp1 = bp + (risk * 2)
        tp2 = bp + (risk * 3)

        rr1 = 2
        rr2 = 3

        date = df.index[i]

        # =========================
        # MESSAGE
        # =========================

        message = (
            "🚨 BULLISH SETUP FOUND\n\n"
            f"📊 Stock: {symbol}\n"
            f"⏱ Timeframe: 1D\n"
            f"📅 Confirmation: {date.strftime('%d-%m-%Y')}\n\n"
            f"🕯 Pattern: {pattern}\n"
            f"📍 Support: ₹{support:.2f}\n\n"
            f"🟢 BP / BUY: ₹{bp:.2f}\n"
            f"🛑 SL: ₹{sl:.2f}\n"
            f"🎯 TP1: ₹{tp1:.2f}  (1:2)\n"
            f"🎯 TP2: ₹{tp2:.2f}  (1:3)\n\n"
            f"💰 Risk: ₹{risk:.2f}\n"
            f"📈 Day-1 High: ₹{day1_high:.2f}\n"
            f"✅ Day-2 Close: ₹{day2_close:.2f}"
        )

        return message

    except Exception as e:

        print(f"{symbol}: error -> {e}")

        return None


# =========================
# MAIN SCANNER
# =========================

def main():

    print("Starting NSE Bullish Scanner...")

    symbols = get_nse_stocks()

    print(f"Total NSE equity symbols: {len(symbols)}")

    signals = []

    for start in range(0, len(symbols), BATCH_SIZE):

        batch = symbols[start:start + BATCH_SIZE]

        print(
            f"Scanning {start + 1} - "
            f"{min(start + BATCH_SIZE, len(symbols))}"
        )

        for symbol in batch:

            result = check_stock(symbol)

            if result:

                print("\nSIGNAL FOUND:")
                print(result)

                signals.append(result)

                send_telegram(result)

            time.sleep(0.15)

        # Small pause between batches
        time.sleep(2)

    # No setup message
    if not signals:

        print("No bullish setup found today.")

        send_telegram(
            "📊 NSE Bullish Scanner\n\n"
            "No setup found today.\n"
            "No stock matched all conditions."
        )

    print("\nScanner finished.")


if __name__ == "__main__":
    main()
