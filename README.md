# pepper-bot

Wysyła na Discord (lub Telegram) nowe okazje z Pepper.pl z kategorii **karty graficzne** i **procesory**.
Działa w GitHub Actions: zadanie przez ok. 58 minut sprawdza Pepper co minutę, a na koniec
samo uruchamia następne. Harmonogram co godzinę jest tylko zapasem, gdyby łańcuch się przerwał.

## Uruchomienie na GitHubie

1. **Utwórz publiczne repozytorium** na github.com, np. `pepper-bot`, bez README.
   Repo musi być publiczne, bo wtedy minuty Actions są bez limitu.
2. **Wgraj pliki** z tego folderu, łącznie z ukrytym folderem `.github`.
   Najprościej z terminala w tym folderze:
   ```bash
   git init -b main
   git add .
   git commit -m "Pepper bot"
   git remote add origin https://github.com/TWOJ_LOGIN/pepper-bot.git
   git push -u origin main
   ```
   Uwaga: przy wgrywaniu przez przeglądarkę ("Add file → Upload files") folder `.github`
   bywa pomijany. Wtedy utwórz plik ręcznie przez "Add file → Create new file" ze ścieżką
   `.github/workflows/pepper.yml` i wklej do niego zawartość.
3. **Dodaj webhook jako sekret:** Settings → Secrets and variables → Actions →
   New repository secret. Nazwa: `DISCORD_WEBHOOK`, wartość: adres webhooka z Discorda.
   (Opcjonalnie Telegram: `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID`).
4. **Pozwól botowi zapisywać `seen.json`:** Settings → Actions → General →
   Workflow permissions → zaznacz "Read and write permissions" → Save.
5. **Uruchom pierwszy raz ręcznie:** zakładka Actions → "Pepper bot" → Run workflow.
   Pierwsze sprawdzenie tylko zapamiętuje obecne okazje (bez spamu), kolejne wysyłają nowe.
   Dalej każde zadanie samo uruchamia następne. Żeby zatrzymać bota: Actions → "Pepper bot" →
   ⋯ → Disable workflow (samo Cancel workflow zatrzyma łańcuch, ale harmonogram go wznowi).

## Zmiana filtrów

Edytuj `config.json` (można bezpośrednio na GitHubie, ikoną ołówka):

- `keywords` – słowa, z których co najmniej jedno musi być w tytule, np. `["5070", "9070"]`. Pusta lista = wszystko.
- `exclude` – słowa, które wykluczają okazję.
- `max_price` – maksymalna cena w zł, `null` = bez limitu.

## Dobrze wiedzieć

- GitHub może wyłączyć harmonogram po 60 dniach bez aktywności w repo. Jeśli powiadomienia
  przestaną przychodzić, wejdź w Actions i włącz workflow ponownie albo zrób dowolny commit.
- Sprawdzanie co minutę w pętli jest niezgodne z przeznaczeniem GitHub Actions według
  regulaminu. W najgorszym razie GitHub wyłączy Actions w repo. Żeby przejść na bezpieczny
  wariant co 5 minut, w `.github/workflows/pepper.yml` ustaw `cron: "*/5 * * * *"` i `LOOP_MINUTES: 1`.
- Postęp i błędy widać w zakładce Actions, w logach zadania.

## Obserwowanie cen (Amazon.pl, Morele, MediaMarkt, Proline, Sferis, x-kom, Ceneo)

`price_watch.py` co 30 minut sprawdza ceny kart z listy `price_watch.items` w `config.json`
i wysyła powiadomienie (zielone na Discordzie), gdy cena spadnie do progu `max_price` lub niżej.
O tej samej ofercie przypomni tylko wtedy, gdy cena spadnie o co najmniej 1% albo gdy
wcześniej wróciła powyżej progu. Stan zapisuje w `price_state.json`.

- `include` / `exclude` – wyrażenia regularne dopasowywane do nazwy oferty (małymi literami).
- `max_price` – próg w zł; oferty poniżej 60% progu są pomijane jako akcesoria lub błędne opisy
  (zmienisz to polem `min_price`).
- `sources` – dowolne z `amazon`, `morele`, `mediamarkt`, `proline`, `sferis`, `xkom`, `ceneo`.
  Gdy sklep włączy ochronę antybotową albo odmówi dostępu, bot odpuszcza go do następnego
  sprawdzenia (w logu np. „Amazon włączył ochronę antybotową”). Brane są tylko oferty dostępne
  od ręki (poza Amazonem i MediaMarktem, gdzie strona wyszukiwania tego nie pokazuje).
  Z serwerów GitHuba działają Morele, MediaMarkt, Proline i Sferis; Amazon tylko częściowo;
  x-kom i Ceneo blokują. RTV Euro AGD, Media Expert, Komputronik, Neonet, Proshop i Allegro
  blokują takie zapytania nawet z domowego internetu, więc ich nie ma.

- `queries` – kilka szerokich wyszukiwań (np. „rx 9070” łapie też GRE), dopasowywanych do wszystkich kart z listy.
  Każde zapytanie idzie po kolei do wszystkich sklepów, potem bot czeka losowo `delay_seconds`
  (domyślnie 10–20 s).
- Na GitHubie sprawdzane są tylko Morele, MediaMarkt, Proline i Sferis (`PRICE_SOURCES` w workflow).
  Amazon, x-kom i Ceneo sprawdza laptop w domu – patrz niżej.

- `category` – `gpu` albo `cpu`. Kanał Pepper z polem `price_watch_category` (np. „Procesory” z `cpu`)
  przepuszcza tylko modele z tej kategorii, każdy w swoim progu `max_price`.

Lokalnie: `python price_watch.py --dry-run` pokaże, co by wysłał.

## Laptop w domu (Amazon, x-kom, Ceneo co 10 minut)

Te sklepy blokują serwery GitHuba, ale wpuszczają domowy internet (Amazon czasem pokazuje
blokadę i tutaj – wtedy pominięte wyszukiwania wracają przy następnym sprawdzeniu).
`laptop_watch.py` sprawdza je, a wynik dopisuje do `laptop.log`.

1. Zainstaluj Pythona z python.org i zaznacz „Add python.exe to PATH”.
2. Pobierz repo (Code → Download ZIP) i rozpakuj do `C:\PepperBot`.
3. Utwórz `C:\PepperBot\secrets.json` z webhookiem Discorda:
   `{"discord_webhook": "https://discord.com/api/webhooks/..."}`. Webhook skopiujesz w Discordzie:
   ustawienia serwera → Integracje → Webhooki (z sekretów GitHuba nie da się go odczytać).
4. Test w wierszu poleceń: `py C:\PepperBot\laptop_watch.py`, potem otwórz `C:\PepperBot\laptop.log`.
   Powinna tam być linia `ceny: wysłano ... (9 zapytań na źródło: amazon, xkom, ceneo)`.
5. Uruchamianie co 10 minut bez okna konsoli:
   `schtasks /create /tn "PepperBot ceny" /tr "pyw C:\PepperBot\laptop_watch.py" /sc minute /mo 10 /f`
   Zatrzymanie: `schtasks /delete /tn "PepperBot ceny" /f`.
6. Zasilanie: przy zasilaczu usypianie „Nigdy”, a zamknięcie pokrywy „Nic nie rób”
   (Panel sterowania → Opcje zasilania). W Lenovo Vantage ustaw limit ładowania baterii na ok. 80%.

Zadanie działa tylko, gdy jesteś zalogowany – po restarcie (np. po aktualizacji Windows) zaloguj się raz.
Aktualizacja: pobierz ZIP ponownie i nadpisz pliki, zostawiając `secrets.json` i `price_state_laptop.json`.

## Lokalnie

```bash
python pepper_bot.py --dry-run   # pokaże, co by wysłał
python pepper_bot.py             # pętla na Twoim komputerze
```
Webhook lokalnie podaj w zmiennej `DISCORD_WEBHOOK` albo w pliku `secrets.json`:
`{"discord_webhook": "https://discord.com/api/webhooks/..."}`. Ten plik jest w `.gitignore`, więc nie trafi do repo.
