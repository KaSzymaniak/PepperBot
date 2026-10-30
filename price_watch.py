"""Obserwowanie cen kart graficznych na Ceneo i Amazon.pl.

Dla każdej karty z listy price_watch.items w config.json szuka ofert i wysyła
powiadomienie (Discord/Telegram, te same sekrety co pepper_bot.py), gdy cena
spadnie do progu max_price lub niżej. O tej samej ofercie powiadamia ponownie
tylko wtedy, gdy cena spadnie jeszcze bardziej albo gdy wcześniej wróciła
powyżej progu.

Sprawdza najwyżej co price_watch.interval_minutes - można go wołać co minutę
(jak w workflow), a i tak nie będzie zbyt często pytał sklepów.

Użycie:
    python price_watch.py --once     # sprawdzenie, jeśli minął interwał
    python price_watch.py --force    # sprawdzenie od razu
    python price_watch.py --dry-run  # pokazuje co by wysłał, nic nie wysyła
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pepper_bot import http_post_json, load_config

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "price_state.json"
LAST_RUN_FILE = HERE / ".price_last_run"  # poza repo, żeby nie commitować co 15 min
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


def browser_get(url, retries=1):
    req = urllib.request.Request(url, headers={
        "User-Agent": BROWSER_UA,
        "Accept-Language": "pl-PL,pl;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # Amazon czasem odpowiada 503 przy pierwszym zapytaniu - jedna ponowna próba
        if e.code == 503 and retries > 0:
            time.sleep(5)
            return browser_get(url, retries - 1)
        raise


def to_price(value, penny="0"):
    """'3 146' + '52' -> 3146.52"""
    return float(re.sub(r"[^\d]", "", value) + "." + (penny or "0"))


def search_ceneo(query):
    # ;0112-0 = sortowanie od najtańszych
    url = "https://www.ceneo.pl/Karty_graficzne;szukaj-" + urllib.parse.quote_plus(query) + ";0112-0.htm"
    d = browser_get(url)
    for chunk in d.split('class="cat-prod-row__name"')[1:]:
        name = re.search(r"<span\s*>([^<]+)</span>", chunk)
        link = re.search(r'href="/(\d+)', chunk)
        price = re.search(r'<span class="value">([\d\s\xa0]+)</span><span class="penny">,?(\d*)', chunk)
        if name and link and price:
            yield {
                "source": "Ceneo",
                "name": html.unescape(name.group(1)).strip(),
                "link": f"https://www.ceneo.pl/{link.group(1)}",
                "price": to_price(price.group(1), price.group(2)),
            }


def search_amazon(query):
    url = "https://www.amazon.pl/s?i=computers&k=" + urllib.parse.quote_plus(query)
    d = browser_get(url)
    if "s-search-result" not in d and ("captcha" in d.lower() or "bm-verify" in d or "Challenge" in d):
        raise Blocked("Amazon włączył ochronę antybotową")
    for chunk in d.split('data-component-type="s-search-result"')[1:]:
        asin = re.search(r'data-asin="(\w{10})"', chunk)
        name = re.search(r"<h2[^>]*>.*?<span[^>]*>([^<]+)</span>", chunk, re.S)
        price = re.search(r'<span class="a-offscreen">([\d\s\xa0.]+),(\d{2})', chunk)
        if asin and name and price:
            yield {
                "source": "Amazon.pl",
                "name": html.unescape(name.group(1)).strip(),
                "link": f"https://www.amazon.pl/dp/{asin.group(1)}",
                "price": to_price(price.group(1), price.group(2)),
            }


class Blocked(Exception):
    """Sklep pokazał captchę/challenge - nie próbujemy go obchodzić, tylko odpuszczamy do następnej rundy."""


SOURCES = {"ceneo": search_ceneo, "amazon": search_amazon}


def is_model(offer, item):
    name = offer["name"].lower()
    if not re.search(item["include"], name):
        return False
    return not (item.get("exclude") and re.search(item["exclude"], name))


def matches(offer, item):
    if not is_model(offer, item):
        return False
    # odrzuca akcesoria i źle opisane oferty, np. "backplate do RX 9070" za 99 zł
    min_price = item.get("min_price", item["max_price"] * 0.6)
    return min_price <= offer["price"] <= item["max_price"]


def fmt(price):
    return f"{price:,.2f}".replace(",", " ").replace(".", ",").replace(",00", "") + " zł"


def notify(config, item, offer, dry_run):
    text = f"{fmt(offer['price'])} (próg {fmt(item['max_price'])}) - {offer['source']}"
    if dry_run:
        print(f"  [DRY] {item['name']}: {offer['name']} | {text} | {offer['link']}")
        return
    if config.get("discord_webhook"):
        http_post_json(config["discord_webhook"], {"embeds": [{
            "title": f"{item['name']} poniżej progu: {offer['name']}"[:256],
            "url": offer["link"],
            "description": text,
            "footer": {"text": f"Obserwowanie cen - {offer['source']}"},
            "color": 0x2ECC71,
        }]})
    tg = config.get("telegram", {})
    if tg.get("bot_token"):
        http_post_json(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage", {
            "chat_id": tg["chat_id"],
            "text": f"[{item['name']}] {offer['name']}\n{text}\n{offer['link']}",
        })


def load_state():
    """{link oferty: cena z ostatniego powiadomienia}"""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    data = json.dumps(state, ensure_ascii=False, indent=0, sort_keys=True)
    if not STATE_FILE.exists() or STATE_FILE.read_text(encoding="utf-8") != data:
        STATE_FILE.write_text(data, encoding="utf-8")


def check(config, dry_run=False, force=False):
    watch = config.get("price_watch")
    if not watch or not watch.get("items"):
        return
    last_run = float(LAST_RUN_FILE.read_text()) if LAST_RUN_FILE.exists() else 0
    if not (dry_run or force) and time.time() - last_run < watch.get("interval_minutes", 15) * 60:
        return
    notified = load_state()
    sent = 0
    for source in watch.get("sources", ["ceneo"]):
        search = SOURCES[source]
        for item in watch["items"]:
            try:
                offers = list(search(item.get("query", item["name"])))
            except Blocked as e:
                print(f"{e} - pomijam {source} do następnego sprawdzenia")
                break
            except Exception as e:
                print(f"Błąd {source} / {item['name']}: {e}")
                continue
            finally:
                time.sleep(2)  # nie zasypujemy sklepu zapytaniami
            for offer in offers:
                key = offer["link"]
                if not matches(offer, item):
                    # oferta wróciła powyżej progu - zapominamy ją, żeby kolejny
                    # spadek znowu dał powiadomienie
                    if key in notified and is_model(offer, item) and offer["price"] > item["max_price"]:
                        del notified[key]
                    continue
                last = notified.get(key)
                # nowa oferta pod progiem albo spadek o co najmniej 1%
                if last is None or offer["price"] <= last * 0.99:
                    try:
                        notify(config, item, offer, dry_run)
                        sent += 1
                        time.sleep(1)
                    except Exception as e:
                        print(f"Błąd wysyłki: {e}")
                        continue
                    notified[key] = offer["price"]
    if not dry_run:
        LAST_RUN_FILE.write_text(str(time.time()))
        save_state(notified)
    print(f"{time.strftime('%H:%M:%S')} ceny: wysłano {sent} powiadomień")


def main():
    config = load_config()
    check(config, dry_run="--dry-run" in sys.argv, force="--force" in sys.argv)


if __name__ == "__main__":
    main()
