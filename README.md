# pepper-bot

Wysyła na Discord (lub Telegram) nowe okazje z Pepper.pl z kategorii **karty graficzne** i **procesory**.
Działa w GitHub Actions: zadanie startuje co 30 minut i w środku sprawdza Pepper co minutę.

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
   Dalej zadanie uruchamia się samo co 30 minut.

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

## Obserwowanie cen (Ceneo + Amazon.pl)

`price_watch.py` co 15 minut sprawdza ceny kart z listy `price_watch.items` w `config.json`
i wysyła powiadomienie (zielone na Discordzie), gdy cena spadnie do progu `max_price` lub niżej.
O tej samej ofercie przypomni tylko wtedy, gdy cena spadnie o co najmniej 1% albo gdy
wcześniej wróciła powyżej progu. Stan zapisuje w `price_state.json`.

- `include` / `exclude` – wyrażenia regularne dopasowywane do nazwy oferty (małymi literami).
- `max_price` – próg w zł; oferty poniżej 60% progu są pomijane jako akcesoria lub błędne opisy
  (zmienisz to polem `min_price`).
- `sources` – `["ceneo", "amazon"]`. Ceneo zbiera oferty m.in. z Media Expert, x-kom, Morele,
  Proshop i RTV Euro AGD. Amazon po kilku zapytaniach potrafi włączyć ochronę antybotową –
  bot wtedy odpuszcza go do następnego sprawdzenia (w logu: „Amazon włączył ochronę antybotową”).

Lokalnie: `python price_watch.py --dry-run` pokaże, co by wysłał.

## Lokalnie

```bash
python pepper_bot.py --dry-run   # pokaże, co by wysłał
python pepper_bot.py             # pętla na Twoim komputerze
```
Webhook lokalnie podaj w zmiennej `DISCORD_WEBHOOK` albo w pliku `secrets.json`:
`{"discord_webhook": "https://discord.com/api/webhooks/..."}`. Ten plik jest w `.gitignore`, więc nie trafi do repo.
