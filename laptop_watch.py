"""Ceny w sklepach, które blokują serwery GitHuba (Amazon, x-kom, Ceneo) - na laptopie w domu.

Harmonogram zadań Windows uruchamia ten plik co 10 minut przez pyw (bez okna konsoli).
x-kom jest sprawdzany przy każdym uruchomieniu, Amazon i Ceneo rzadziej (SOURCE_INTERVALS),
bo przy częstszych zapytaniach coraz częściej blokowały domowe łącze.
Wynik i błędy dopisuje do laptop.log obok. Stan trzyma w price_state_laptop.json,
osobno od price_state.json, który commituje bot na GitHubie.

Instalacja: README.md, sekcja "Laptop w domu".
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PRICE_SOURCES", "amazon,xkom,ceneo")
os.environ.setdefault("PRICE_STATE_FILE", str(HERE / "price_state_laptop.json"))
sys.path.insert(0, str(HERE))
LOG_FILE = HERE / "laptop.log"
LAST_RUN_FILE = HERE / ".laptop_last_run.json"  # kiedy ostatnio sprawdzono każdy sklep
SOURCE_INTERVALS = {"amazon": 30, "ceneo": 30}  # minuty; pozostałe sklepy przy każdym uruchomieniu


def due_sources(now, last_run):
    """Sklepy, na które przyszła pora w tym uruchomieniu."""
    sources = [s.strip() for s in os.environ["PRICE_SOURCES"].split(",")]
    # minuta zapasu, bo Harmonogram zadań nie startuje co do sekundy
    return [s for s in sources if now - last_run.get(s, 0) >= (SOURCE_INTERVALS.get(s, 0) - 1) * 60]


def send_test():
    """py laptop_watch.py --test - wysyła wiadomość testową na Discorda."""
    from pepper_bot import http_post_json, load_config
    config = load_config()
    if not config["discord_webhook"]:
        print("Brak webhooka - sprawdź, czy plik nazywa się secrets.json (nie secrets.json.txt).")
        return
    http_post_json(config["discord_webhook"], {"content": "Test z laptopa - bot cen działa."})
    print("Wysłano wiadomość testową na Discorda.")


def main():
    if "--test" in sys.argv:
        send_test()
        return
    # pyw nie ma konsoli, więc wszystko idzie do pliku
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        sys.stdout = sys.stderr = log
        try:
            import price_watch
            now = time.time()
            last_run = json.loads(LAST_RUN_FILE.read_text()) if LAST_RUN_FILE.exists() else {}
            due = due_sources(now, last_run)
            os.environ["PRICE_SOURCES"] = ",".join(due)
            # o odstępy dba Harmonogram zadań i SOURCE_INTERVALS, więc bez interval_minutes z config.json
            price_watch.check(price_watch.load_config(), force=True)
            last_run.update(dict.fromkeys(due, now))
            LAST_RUN_FILE.write_text(json.dumps(last_run))
        except Exception:
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "błąd:")
            traceback.print_exc()


if __name__ == "__main__":
    main()
