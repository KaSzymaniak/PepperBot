"""Bot powiadomień o nowych okazjach z Pepper.pl (karty graficzne, procesory...).

Czyta kanały RSS kategorii Pepper i wysyła nowe okazje na Discord (webhook)
i/lub Telegram. Tylko biblioteka standardowa Pythona.

Ustawienia (kanały, filtry) są w config.json. Sekrety NIE trafiają do repo:
bot bierze je ze zmiennych środowiskowych (w GitHub Actions z sekretów repo):
    DISCORD_WEBHOOK, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Lokalnie możesz je zamiast tego wpisać do secrets.json (jest w .gitignore).

Użycie:
    python pepper_bot.py            # pętla, sprawdza co interval_seconds
    python pepper_bot.py --once     # jedno sprawdzenie
    python pepper_bot.py --dry-run  # pokazuje co by wysłał, nic nie wysyła
"""
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.json"
SECRETS_FILE = HERE / "secrets.json"
SEEN_FILE = HERE / "seen.json"
UA = "Mozilla/5.0 (pepper-bot)"
PEPPER_NS = "{http://www.pepper.com/rss}"
SEEN_LIMIT = 2000


def load_config():
    if not CONFIG_FILE.exists():
        sys.exit(f"Brak {CONFIG_FILE.name}.")
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    secrets = {}
    if SECRETS_FILE.exists():
        secrets = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    config["discord_webhook"] = os.environ.get("DISCORD_WEBHOOK") or secrets.get("discord_webhook", "")
    config["telegram"] = {
        "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN") or secrets.get("telegram_bot_token", ""),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID") or secrets.get("telegram_chat_id", ""),
    }
    for feed in config["feeds"]:
        feed["_price_watch_items"] = config.get("price_watch", {}).get("items", [])
    if not config["discord_webhook"] and not config["telegram"]["bot_token"]:
        print("Uwaga: brak DISCORD_WEBHOOK i TELEGRAM_BOT_TOKEN - powiadomienia nie zostaną wysłane.")
    return config


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def http_post_json(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def parse_price(text):
    """'3 885zł' -> 3885.0, brak ceny -> None."""
    if not text:
        return None
    m = re.search(r"\d[\d\s.]*(?:,\d+)?", text.replace("\xa0", " "))
    if not m:
        return None
    num = m.group(0).replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def fetch_deals(feed):
    root = ET.fromstring(http_get(feed["url"]))
    for item in root.iter("item"):
        merchant = item.find(f"{PEPPER_NS}merchant")
        thumb = item.find("{http://search.yahoo.com/mrss/}thumbnail")
        price_text = merchant.get("price") if merchant is not None else None
        yield {
            "id": item.findtext("guid") or item.findtext("link"),
            "title": (item.findtext("title") or "").strip(),
            "link": item.findtext("link"),
            "shop": merchant.get("name") if merchant is not None else None,
            "price_text": price_text,
            "price": parse_price(price_text),
            "image": thumb.get("url") if thumb is not None else None,
            "feed": feed["name"],
        }


def matches(deal, feed):
    title = deal["title"].lower()
    include = [k.lower() for k in feed.get("keywords", [])]
    exclude = [k.lower() for k in feed.get("exclude", [])]
    if include and not any(k in title for k in include):
        return False
    if any(k in title for k in exclude):
        return False
    max_price = feed.get("max_price")
    if max_price and deal["price"] is not None and deal["price"] > max_price:
        return False
    category = feed.get("price_watch_category")
    if category:
        # tylko modele z listy price_watch tej kategorii, każdy z własnym progiem ceny
        models = [i for i in feed["_price_watch_items"] if i.get("category") == category]
        model = next((m for m in models if model_matches(title, m)), None)
        if model is None:
            return False
        if deal["price"] is not None and deal["price"] > model["max_price"]:
            return False
    return True


def model_matches(title, model):
    if not re.search(model["include"], title):
        return False
    return not (model.get("exclude") and re.search(model["exclude"], title))


def notify_discord(webhook, deal):
    price = f"{deal['price_text']} - {deal['shop']}" if deal["price_text"] else (deal["shop"] or "")
    embed = {
        "title": deal["title"][:256],
        "url": deal["link"],
        "description": price,
        "footer": {"text": f"Pepper.pl - {deal['feed']}"},
        "color": 0xE8541E,
    }
    if deal["image"]:
        embed["thumbnail"] = {"url": deal["image"]}
    http_post_json(webhook, {"embeds": [embed]})


def notify_telegram(cfg, deal):
    price = f"\n{deal['price_text']} - {deal['shop']}" if deal["price_text"] else ""
    text = f"[{deal['feed']}] {deal['title']}{price}\n{deal['link']}"
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    http_post_json(url, {"chat_id": cfg["chat_id"], "text": text})


def send(config, deal, dry_run):
    if dry_run:
        print(f"  [DRY] {deal['feed']}: {deal['title']} | {deal['price_text']} | {deal['link']}")
        return
    if config.get("discord_webhook"):
        notify_discord(config["discord_webhook"], deal)
    if config.get("telegram", {}).get("bot_token"):
        notify_telegram(config["telegram"], deal)


def load_seen():
    if SEEN_FILE.exists():
        # dict zachowuje kolejność dodania, więc działa jak uporządkowany zbiór
        return dict.fromkeys(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return None  # pierwsze uruchomienie


def save_seen(seen):
    # trzymamy SEEN_LIMIT najnowszych id, żeby plik nie rósł w nieskończoność;
    # zapisujemy tylko przy zmianie, żeby nie robić pustych commitów
    data = json.dumps(list(seen)[-SEEN_LIMIT:], indent=0)
    if not SEEN_FILE.exists() or SEEN_FILE.read_text(encoding="utf-8") != data:
        SEEN_FILE.write_text(data, encoding="utf-8")


def check(config, dry_run=False):
    seen = load_seen()
    first_run = seen is None
    seen = seen or {}
    new_count = 0
    for feed in config["feeds"]:
        try:
            deals = list(fetch_deals(feed))
        except Exception as e:
            print(f"Błąd pobierania {feed['name']}: {e}")
            continue
        for deal in reversed(deals):  # od najstarszej, żeby kolejność na Discordzie była naturalna
            if deal["id"] in seen:
                continue
            if first_run and not dry_run:
                seen[deal["id"]] = None
                continue  # przy pierwszym starcie tylko zapamiętujemy, bez spamu
            if matches(deal, feed):
                try:
                    send(config, deal, dry_run)
                    new_count += 1
                    time.sleep(1)  # limit Discorda
                except Exception as e:
                    print(f"Błąd wysyłki: {e}")
                    continue  # nie zapamiętujemy - spróbujemy przy następnym sprawdzeniu
            seen[deal["id"]] = None
    if not dry_run:
        save_seen(seen)
    if first_run and not dry_run:
        print(f"Pierwsze uruchomienie - zapamiętano {len(seen)} okazji, powiadomienia od następnych.")
    else:
        print(f"{time.strftime('%H:%M:%S')} wysłano {new_count} nowych okazji")


def main():
    config = load_config()
    dry_run = "--dry-run" in sys.argv
    if dry_run or "--once" in sys.argv:
        check(config, dry_run)
        return
    interval = config.get("interval_seconds", 300)
    while True:
        check(config)
        time.sleep(interval)


if __name__ == "__main__":
    main()
