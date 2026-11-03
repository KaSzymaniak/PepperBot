"""Tymczasowy test: czy sklepy wpuszczają wyszukiwanie z serwerów GitHuba."""
import os
import time
import urllib.error

from price_watch import browser_get

URLS = {
    "Morele (dla porównania)": "https://www.morele.net/wyszukiwarka/?q=rx+9060+xt&categoryId=12",
    "MediaMarkt": "https://mediamarkt.pl/pl/search.html?query=rx%209060%20xt",
    "Proline": "https://proline.pl/wyszukaj?searchString=rx+9060+xt",
    "Sferis": "https://www.sferis.pl/wyszukaj?s=rx+9060+xt",
}

rows = ["| Sklep | Kod | Rozmiar | Trafienia „9060 xt” | Wynik |", "|---|---|---|---|---|"]
for name, url in URLS.items():
    try:
        d, code = browser_get(url, retries=0), 200
    except urllib.error.HTTPError as e:
        d, code = "", e.code
    except Exception as e:
        d, code = "", type(e).__name__
    hits = d.lower().count("9060 xt")
    rows.append(f"| {name} | {code} | {len(d)} | {hits} | {'✅ działa' if hits >= 5 else '❌ blokada'} |")
    time.sleep(3)

print("\n".join(rows))
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
