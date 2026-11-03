"""Ceny w sklepach, które blokują serwery GitHuba (Amazon, x-kom, Ceneo) - na laptopie w domu.

Harmonogram zadań Windows uruchamia ten plik co 10 minut przez pyw (bez okna konsoli).
Wynik i błędy dopisuje do laptop.log obok. Stan trzyma w price_state_laptop.json,
osobno od price_state.json, który commituje bot na GitHubie.

Instalacja: README.md, sekcja "Laptop w domu".
"""
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


def main():
    # pyw nie ma konsoli, więc wszystko idzie do pliku
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        sys.stdout = sys.stderr = log
        try:
            import price_watch
            # o odstępy dba Harmonogram zadań (co 10 min), więc bez interval_minutes z config.json
            price_watch.check(price_watch.load_config(), force=True)
        except Exception:
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "błąd:")
            traceback.print_exc()


if __name__ == "__main__":
    main()
