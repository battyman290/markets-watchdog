import os
import json
import time
import requests
import feedparser
import yfinance as yf
from datetime import datetime, timezone

STATE_FILE = "state.json"
FEEDS_FILE = "feeds.json"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Tickers to watch for sudden price moves.
# "threshold" is the % move (up or down) that triggers an alert.
TICKERS = {
    "Nifty 50": {"symbol": "^NSEI", "threshold": 2.0},
    "Sensex": {"symbol": "^BSESN", "threshold": 2.0},
    "Thermax Ltd": {"symbol": "THERMAX.NS", "threshold": 5.0},
    "Exide Industries": {"symbol": "EXIDEIND.NS", "threshold": 5.0},
    "Mahindra Lifespace": {"symbol": "MAHLIFE.NS", "threshold": 5.0},
}

MAX_SEEN_PER_FEED = 300  # cap memory per feed so state.json doesn't grow forever


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing Telegram credentials — printing instead of sending:")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Telegram's hard limit is 4096 characters per message.
    chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)] or [text]
    for chunk in chunks:
        try:
            resp = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=20,
            )
            if resp.status_code != 200:
                print("Telegram send failed:", resp.text)
        except Exception as e:
            print("Telegram send error:", e)
        time.sleep(1)


def check_prices(state):
    alerts = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    price_state = state.setdefault("price_alerts_sent", {})

    for name, info in TICKERS.items():
        try:
            t = yf.Ticker(info["symbol"])
            hist = t.history(period="5d")
            if len(hist) < 2:
                continue
            prev_close = hist["Close"].iloc[-2]
            last_close = hist["Close"].iloc[-1]
            pct_change = ((last_close - prev_close) / prev_close) * 100

            key = f"{name}_{today}"
            already_sent = price_state.get(key, False)

            if abs(pct_change) >= info["threshold"] and not already_sent:
                direction = "up" if pct_change > 0 else "down"
                alerts.append(
                    f"\U0001F4C8 SUDDEN MOVE: {name} is {direction} {pct_change:.2f}% today "
                    f"(prev close {prev_close:.2f} -> now {last_close:.2f})"
                )
                price_state[key] = True
        except Exception as e:
            print(f"Price check failed for {name}: {e}")

    # trim old entries so this dict doesn't grow forever
    if len(price_state) > 200:
        for k in sorted(price_state.keys())[:-200]:
            del price_state[k]

    return alerts


def check_feeds(state):
    feeds = load_json(FEEDS_FILE, [])
    seen = state.setdefault("seen_links", {})
    alerts = []

    for feed in feeds:
        url = feed.get("url", "").strip()
        label = feed.get("label", "Update")
        category = feed.get("category", "General")
        if not url or "PASTE_" in url:
            continue  # not filled in yet

        seen_for_feed = set(seen.get(url, []))
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"Failed to parse feed {url}: {e}")
            continue

        new_links = []
        for entry in parsed.entries[:20]:
            link = entry.get("link", "")
            title = entry.get("title", "No title")
            if not link or link in seen_for_feed:
                continue
            new_links.append(link)
            alerts.append(f"\U0001F514 [{category}] {label}\n{title}\n{link}")

        if new_links:
            updated = list(seen_for_feed) + new_links
            seen[url] = updated[-MAX_SEEN_PER_FEED:]

    return alerts


def main():
    state = load_json(STATE_FILE, {})

    all_alerts = []
    all_alerts.extend(check_prices(state))
    all_alerts.extend(check_feeds(state))

    if all_alerts:
        header = f"\U0001F4CA Market & Company Alerts \u2014 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        body = "\n\n".join(all_alerts)
        send_telegram(header + body)
        print(f"Sent {len(all_alerts)} alert(s).")
    else:
        print("No new alerts this run.")

    save_json(STATE_FILE, state)


if __name__ == "__main__":
    main()
