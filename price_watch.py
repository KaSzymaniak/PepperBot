"""Obserwowanie cen kart graficznych i procesorów w sklepach (lista w SOURCES).

Dla każdej karty z listy price_watch.items w config.json szuka ofert i wysyła
powiadomienie (Discord/Telegram, te same sekrety co pepper_bot.py), gdy cena
spadnie do progu max_price lub niżej. O tej samej ofercie powiadamia ponownie
tylko wtedy, gdy cena spadnie jeszcze bardziej albo gdy wcześniej wróciła
powyżej progu.

Sprawdza najwyżej co price_watch.interval_minutes (domyślnie 30) - można go wołać co minutę
(jak w workflow), a i tak nie będzie zbyt często pytał sklepów.

Użycie:
    python price_watch.py --once     # sprawdzenie, jeśli minął interwał
    python price_watch.py --force    # sprawdzenie od razu
    python price_watch.py --dry-run  # pokazuje co by wysłał, nic nie wysyła
"""
import html
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pepper_bot import http_post_json, load_config

HERE = Path(__file__).resolve().parent
# laptop trzyma własny stan, żeby nie gryzł się z plikiem commitowanym przez GitHuba
STATE_FILE = Path(os.environ.get("PRICE_STATE_FILE") or HERE / "price_state.json")
LAST_RUN_FILE = HERE / ".price_last_run"  # poza repo, żeby nie commitować co 15 min
MAX_CHALLENGES = 2  # po tylu blokadach antybotowych w jednej rundzie sklep jest pomijany
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
    if "cat-prod-row" not in d:
        # Ceneo nie zwraca błędu, tylko stronę bez listy produktów (np. dla serwerów GitHuba)
        raise Blocked("Ceneo nie zwrócił listy produktów (blokada lub zmiana strony)")
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


def search_xkom(query):
    d = browser_get("https://www.x-kom.pl/szukaj?q=" + urllib.parse.quote(query))
    if '"availabilityStatus"' not in d and "Nie znaleźliśmy" not in d:
        raise Blocked("x-kom nie zwrócił listy produktów (blokada lub zmiana strony)")
    # lista produktów jest w JSON-ie strony; każdy produkt zaczyna się od statusu dostępności
    for chunk in d.split('"availabilityStatus":"')[1:]:
        if not chunk.startswith("Available"):
            continue  # brak w magazynie - x-kom pokazuje wtedy starą cenę
        m = re.search(r'"webUrl":"([^"]+)","fullName":"([^"]*)".*?"price":([\d.]+),'
                      r'"category":\{[^}]*?"parentCategoryName":"([^"]*)"', chunk)
        # wyszukiwarka podsuwa też gotowe zestawy komputerowe
        if m and m.group(4) in ("Karty graficzne", "Procesory"):
            yield {
                "source": "x-kom",
                "name": html.unescape(m.group(2)),
                "link": "https://www.x-kom.pl" + m.group(1),
                "price": float(m.group(3)),
            }


def search_morele(query):
    # bez kategorii Morele zwraca głównie gotowe komputery; 45 = procesory, 12 = karty graficzne
    category = 45 if "ryzen" in query else 12
    d = browser_get(f"https://www.morele.net/wyszukiwarka/?q={urllib.parse.quote_plus(query)}&categoryId={category}")
    if "product-card" not in d and "category-search-title" not in d:
        raise Blocked("Morele nie zwróciło listy produktów (blokada lub zmiana strony)")
    for chunk in d.split('class="product-card__details"')[1:]:
        name = re.search(r'class="product-card__name-link"[^>]*>\s*([^<]+?)\s*</a>', chunk)
        link = re.search(r'href="(https://www\.morele\.net/[^"]+)"', chunk)
        # produkty niedostępne nie mają ceny
        price = re.search(r'data-testid="product-price-new">\s*([\d\s\xa0]+),(\d{2})', chunk)
        if name and link and price:
            yield {
                "source": "Morele",
                "name": html.unescape(name.group(1)),
                "link": link.group(1),
                "price": to_price(price.group(1), price.group(2)),
            }


def search_proline(query):
    d = browser_get("https://proline.pl/wyszukaj?searchString=" + urllib.parse.quote_plus(query))
    if "product-list" not in d and "product-tile" not in d:
        raise Blocked("Proline nie zwrócił listy produktów (blokada lub zmiana strony)")
    for chunk in d.split('<a class="product-tile"')[1:]:
        tile = re.match(r'\s*href="(/[^"]+)"\s*title="([^"]+)"', chunk)
        # formularz "Dodaj do koszyka" (z nazwą, ceną i kategorią) mają tylko produkty dostępne
        name = re.search(r'name="productName" value="([^"]+)"', chunk)
        price = re.search(r'name="productPrice" value="([\d.]+)"', chunk)
        category = re.search(r'name="category" value="([^"]+)"', chunk)
        if not (tile and name and price and category):
            continue
        # kafelki dodatków (np. ochrona reklamacyjna) nie mają własnego formularza
        # i łapałyby formularz innego produktu
        if html.unescape(name.group(1)) != html.unescape(tile.group(2)):
            continue
        if re.match(r"Karty graficzne|Procesory", html.unescape(category.group(1))):
            yield {
                "source": "Proline",
                "name": html.unescape(name.group(1)),
                "link": "https://proline.pl" + tile.group(1),
                "price": float(price.group(1)),
            }


def search_sferis(query):
    d = browser_get("https://www.sferis.pl/wyszukaj?s=" + urllib.parse.quote_plus(query))
    if "jsProductListingItems" not in d:
        raise Blocked("Sferis nie zwrócił listy produktów (blokada lub zmiana strony)")
    # każdy kafelek zaczyna się od linku do produktu kończącego się na -i<id>
    for chunk in re.split(r'(?=<a href="/[^"]+-i\d+" class="[^"]*jsCard")', d)[1:]:
        link = re.match(r'<a href="(/[^"]+)"', chunk)
        name = re.search(r'<p class="title">\s*([^<]+?)\s*</p>', chunk)
        price = re.search(r'<span class="price">\s*([\d\s\xa0]+),(\d{2})', chunk)
        # niedostępne produkty nie mają przycisku "Dodaj do koszyka"
        if link and name and price and "/dodaj-do-koszyka/" in chunk:
            yield {
                "source": "Sferis",
                "name": html.unescape(name.group(1)),
                "link": "https://www.sferis.pl" + link.group(1),
                "price": to_price(price.group(1), price.group(2)),
            }


def search_mediamarkt(query):
    # bez słowa "karta graficzna"/"procesor" MediaMarkt zwraca głównie gotowe komputery
    prefix = "procesor " if "ryzen" in query else "karta graficzna "
    d = browser_get("https://mediamarkt.pl/pl/search.html?query=" + urllib.parse.quote(prefix + query))
    if '"__typename":"GraphqlProduct"' not in d and "GraphqlSearchFacet" not in d:
        raise Blocked("MediaMarkt nie zwrócił listy produktów (blokada lub zmiana strony)")
    # produkty są w JSON-ie strony: osobno nazwa z linkiem, dostępność i cena, łączone po id
    for product_id in dict.fromkeys(re.findall(r'"GraphqlProduct:Media:pl-PL:(\d+)":', d)):
        product = json_object_after(d, f'"GraphqlProduct:Media:pl-PL:{product_id}"')
        status = json_object_after(d, f'"CofrOnlineStatusFeature:Media:pl:{product_id}"')
        price = json_object_after(d, f'"CofrPriceFeature:{{\\"id\\":\\"Media:pl:{product_id}\\"')
        # sama wyszukiwarka trzyma też stare ceny ofert, których nie da się już kupić
        if not (product and status and status.get("isAvailableAndBuyable") and price and price.get("price")):
            continue
        title = product.get("title") or ""
        if re.match(r"karta graficzna|procesor", title.lower()):
            yield {
                "source": "MediaMarkt",
                "name": title,
                "link": "https://mediamarkt.pl" + product["url"],
                "price": float(price["price"]["amount"]),
            }


def json_object_after(d, key_prefix):
    """Obiekt JSON zapisany na stronie pod kluczem zaczynającym się od key_prefix, albo None."""
    i = d.find(key_prefix)
    if i < 0:
        return None
    # koniec klucza: '":' bez ukośnika przed cudzysłowem (klucze cen mają w sobie zakodowany JSON)
    end = re.compile(r'(?<!\\)":(?=\{)').search(d, i + 1)
    if not end:
        return None
    try:
        return json.JSONDecoder().raw_decode(d, end.end())[0]
    except ValueError:
        return None


class Blocked(Exception):
    """Sklep pokazał captchę/challenge - nie próbujemy go obchodzić, tylko odpuszczamy do następnej rundy."""


SOURCES = {
    "ceneo": search_ceneo,
    "amazon": search_amazon,
    "xkom": search_xkom,
    "morele": search_morele,
    "proline": search_proline,
    "sferis": search_sferis,
    "mediamarkt": search_mediamarkt,
}


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
    if not (dry_run or force) and time.time() - last_run < watch.get("interval_minutes", 30) * 60:
        return
    items = watch["items"]
    # kilka szerokich zapytań (np. "rx 9070" łapie 9070, XT i GRE) zamiast osobnego na każdą kartę
    queries = watch.get("queries") or list(dict.fromkeys(i.get("query", i["name"]) for i in items))
    lo, hi = watch.get("delay_seconds", [10, 20])
    sources = os.environ.get("PRICE_SOURCES", "").split(",") if os.environ.get("PRICE_SOURCES") else watch.get("sources", ["ceneo"])
    sources = [s.strip() for s in sources]
    blocked = set()
    challenges = {}  # ile razy sklep pokazał ochronę antybotową w tej rundzie
    notified = load_state()
    sent = 0
    # każde zapytanie po kolei we wszystkich sklepach, potem przerwa - każdy sklep
    # dostaje zapytanie co delay_seconds, a całość trwa tyle, co przy jednym sklepie
    for n, query in enumerate(queries):
        if n:
            time.sleep(random.uniform(lo, hi))  # spokojne tempo, żeby nie obciążać sklepów
        for source in sources:
            if source in blocked:
                continue
            try:
                offers = list(SOURCES[source](query))
            except Blocked as e:
                # Amazon często odrzuca pojedyncze zapytanie, a kolejne (po zwykłej przerwie)
                # przepuszcza - odpuszczamy sklep dopiero po drugiej blokadzie w rundzie
                challenges[source] = challenges.get(source, 0) + 1
                if challenges[source] >= MAX_CHALLENGES:
                    print(f"{e} ({query}) - drugi raz, pomijam {source} do następnego sprawdzenia")
                    blocked.add(source)
                else:
                    print(f"{e} ({query}) - pomijam to wyszukiwanie")
                continue
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    print(f"{source} odmówił dostępu (HTTP 403) - pomijam do następnego sprawdzenia")
                    blocked.add(source)
                else:
                    print(f"Błąd {source} / {query}: {e}")
                continue
            except Exception as e:
                print(f"Błąd {source} / {query}: {e}")
                continue
            for offer in offers:
                item = next((i for i in items if is_model(offer, i)), None)
                if item is None:
                    continue
                key = offer["link"]
                if not matches(offer, item):
                    # oferta wróciła powyżej progu - zapominamy ją, żeby kolejny
                    # spadek znowu dał powiadomienie
                    if key in notified and offer["price"] > item["max_price"]:
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
    print(f"{time.strftime('%H:%M:%S')} ceny: wysłano {sent} powiadomień ({len(queries)} zapytań na źródło: {', '.join(sources)})")


def main():
    config = load_config()
    check(config, dry_run="--dry-run" in sys.argv, force="--force" in sys.argv)


if __name__ == "__main__":
    main()
