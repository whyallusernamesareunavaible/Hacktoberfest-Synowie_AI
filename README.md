# Hacktoberfest-Synowie_AI# Dungeons of Gliwice

Lokalna gra webowa RPG z kreatorem bohatera, dungeonem PvE i pojedynkami
multiplayer. Projekt działa w architekturze **server-authoritative**:

- przeglądarka wybiera build i lokalny seed/cache,
- FastAPI wykonuje obliczenia walki, wydarzeń, sklepu, nagród i dropów,
- frontend nie rozstrzyga wyniku — odtwarza otrzymane zdarzenia jako animacje,
- buildy i ustawienia użytkownika są przechowywane lokalnie w przeglądarce.

Projekt jest przeznaczony do uruchamiania lokalnego przez XAMPP albo
bezpośrednio przez FastAPI.

## Funkcje

### Kreator bohatera

Kreator pod adresem `kreator-bohatera.html` umożliwia:

- wybór jednej z klas: **Wojownik**, **Mag**, **Łucznik**,
- wybór grafiki bohatera,
- rozdawanie punktów w drzewku umiejętności,
- wybór ekwipunku i automatyczne przeliczanie statystyk,
- automatyczny zapis buildu w `localStorage`,
- synchronizację zapisanych klas z lobby multiplayer,
- przejście do areny PvE i lobby multiplayer.

### Arena PvE

Arena pod adresem `arena.html` korzysta z buildu zapisanego w kreatorze.
Serwer wylicza:

- przeciwnika i jego statystyki,
- kolejność ataków,
- obrażenia, krytyki i uniki,
- wynik walki,
- nagrody i drop,
- wydarzenia pomiędzy walkami,
- zawartość sklepu.

Frontend otrzymuje listę zdarzeń i pokazuje ją za pomocą animacji, pasków
życia, sprite'ów i komunikatów. Nie wykonuje własnego losowania wyniku walki.

### Multiplayer

`lobby.html` udostępnia:

- listę zapisanych buildów klas,
- listę graczy online,
- ranking,
- wyzwania innych graczy,
- pojedynki wykonywane przez WebSocket,
- animacje ataków i wynik pojedynku.

Połączenie multiplayer używa endpointu:

```text
ws://adres-serwera:8765/ws/lobby
```

### Audio i ustawienia

Menu ustawień jest dostępne pod ikoną koła zębatego na wszystkich głównych
stronach. Dostępne są:

- ograniczenie animacji,
- suwak głośności efektów dźwiękowych `0–100%`,
- suwak głośności muzyki `0–100%`.

Ustawienia są wspólne dla areny, lobby i kreatora:

```text
arena:reduced-motion
arena:effects-volume
arena:music-volume
```

Wartość `0%` wycisza daną kategorię. Brak zapisanej wartości oznacza domyślnie
`100%`.

## Wymagania

- Windows,
- Python 3.10 lub nowszy,
- XAMPP z uruchomionym Apache, jeśli frontend ma być serwowany przez Apache,
- dostępne porty `80` i `8765`,
- zależności z `requirements.txt`.

Zależności:

- `fastapi` — backend HTTP i WebSocket,
- `uvicorn` — serwer ASGI,
- `websockets` — obsługa komunikacji WebSocket.

## Najszybsze uruchomienie przez XAMPP

1. Uruchom **Apache** w XAMPP Control Panel.
2. Otwórz PowerShell w katalogu projektu.
3. Uruchom:

   ```powershell
   .\start-xampp.bat
   ```

   Skrypt `start-xampp.bat` przekazuje sterowanie do `start.bat`.

4. Otwórz adres:

   ```text
   http://127.0.0.1/hackathon/
   ```

   Z innego urządzenia w tej samej sieci użyj aktualnego adresu IP komputera,
   na przykład:

   ```text
   http://10.132.198.126/hackathon/
   ```

Skrypt:

- kopiuje pliki HTML do `C:\xampp\htdocs\hackathon`,
- kopiuje sprite'y, grafiki klas, favicon i pliki audio,
- kopiuje `.htaccess` oraz README,
- tworzy `.venv`, jeśli środowisko nie istnieje,
- instaluje zależności,
- uruchamia FastAPI na `0.0.0.0:8765`,
- otwiera frontend w przeglądarce.

Apache serwuje statyczny frontend. FastAPI działa osobno i nie wymaga
`mod_proxy` ani `mod_proxy_http`.

## Uruchomienie bez Apache

Wariant zalecany do szybkiego testowania samego FastAPI:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8765
```

Następnie otwórz:

```text
http://127.0.0.1:8765/
```

Dokumentacja OpenAPI:

```text
http://127.0.0.1:8765/docs
```

Wariant dostępny w sieci LAN:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8765
```

## Logowanie i token

Logowanie jest bezhasłowe i służy do przypisania lokalnego profilu do
krótkotrwałego tokenu API.

- nick jest zapisywany jako `arena:session`,
- token jest zapisywany jako `arena:token`,
- token jest wysyłany w nagłówku `Authorization: Bearer <token>`,
- endpointy gry odrzucają brakujący lub niepoprawny token kodem HTTP `401`.

Sekret HMAC jest generowany przy uruchomieniu backendu. Z tego powodu restart
FastAPI unieważnia wcześniej wydane tokeny i wymaga ponownego zalogowania.

Aby użyć stałego sekretu:

```powershell
$env:ARENA_TOKEN_SECRET = "lokalny-sekret-do-testow"
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8765
```

Nie zapisuj prawdziwych sekretów w repozytorium ani w plikach frontendowych.

## Endpointy backendu

Najważniejsze trasy zdefiniowane w `main.py`:

| Metoda | Ścieżka | Zastosowanie |
|---|---|---|
| `GET` | `/health` | sprawdzenie, czy backend działa |
| `POST` | `/auth/token` | wydanie tokenu po podaniu nicku |
| `GET` | `/przedmioty` | pobranie danych przedmiotów |
| `POST` | `/build/validate` | walidacja buildu |
| `POST` | `/battle` | kompatybilny endpoint walki |
| `POST` | `/arena/battle` | walka areny PvE |
| `POST` | `/arena/event` | wydarzenie pomiędzy walkami |
| `POST` | `/arena/shop` | sklep i jego oferta |
| `GET` | `/docs` | interaktywna dokumentacja FastAPI |
| `WebSocket` | `/ws/lobby` | multiplayer lobby i pojedynki |

Większość endpointów gry wymaga tokenu Bearer. Endpoint `/health` jest
przeznaczony do diagnostyki i nie wymaga logowania.

## Struktura projektu

```text
.
├── main.py                         # FastAPI, autoryzacja, walka i WebSocket
├── login.html                      # logowanie lokalnego profilu
├── kreator-bohatera.html           # kreator klas, umiejętności i ekwipunku
├── arena.html                      # dungeon PvE i animacje walki
├── lobby.html                      # multiplayer i pojedynki
├── index.html                      # przekierowanie do logowania
├── test-api.html                   # ręczne testy walidacji API
├── requirements.txt                # zależności Pythona
├── start.bat                       # wdrożenie do XAMPP i start backendu
├── start-xampp.bat                # skrót do start.bat
├── .htaccess                       # konfiguracja statycznego Apache
├── Characters/                     # sprite'y bohaterów
├── Potwory/                        # sprite'y przeciwników
├── Wizard/                         # sprite bossa
├── ui-assets/                      # grafiki klas i favicon
│   ├── wojownik.png
│   ├── mag.png
│   ├── lucznik.png
│   └── favicon.ico
└── the-tower-is-jammed-ost/        # muzyka i efekty dźwiękowe
```

Podczas uruchomienia przez XAMPP frontend jest kopiowany do:

```text
C:\xampp\htdocs\hackathon
```

## Zasoby audio

Efekty klas:

| Klasa | Plik |
|---|---|
| Wojownik | `the-tower-is-jammed-ost/miecz.flac` |
| Łucznik | `the-tower-is-jammed-ost/miecz.flac` |
| Mag | `the-tower-is-jammed-ost/magik.wav` |

Muzyka i cue:

| Sytuacja | Plik lub grupa plików |
|---|---|
| Kreator bohatera | `konstruktorilogin.ogg` |
| Zwykłe poziomy | `The Tower is Jammed 05-08 - Dungeon BGM 1-4.ogg` |
| Walki z bossami | `The Tower is Jammed 09-10 - Boss Battle 1-2.ogg` |
| Poziomy od 20 | `The Tower is Jammed 11 - The Top Floor.ogg` |
| Przejście poziomu | `nowyfloorv2.ogg` |
| Ukończenie piętra | `nowyfloor.ogg` |
| Pokonanie przeciwnika | `zabicieprzeciwnika.ogg` |

Przeglądarka może zablokować automatyczne odtwarzanie do czasu pierwszej
interakcji użytkownika. Nie jest to błąd serwera.

## Dane przechowywane lokalnie

Aplikacja nie korzysta z bazy danych do profilów i buildów. Dane są
przechowywane w `localStorage` aktualnej przeglądarki:

| Klucz | Zawartość |
|---|---|
| `arena:session` | nick bieżącego profilu |
| `arena:token` | token API |
| `arena:builds:<nick>` | zapisane buildy klas |
| `heroBuild` | build używany przez kreator i arenę |
| `arenaProgress` | stan postępu areny |
| `arena:reduced-motion` | ustawienie ograniczenia animacji |
| `arena:effects-volume` | głośność efektów w procentach |
| `arena:music-volume` | głośność muzyki w procentach |

Wyczyszczenie danych witryny usuwa profil i zapisane buildy z danego
urządzenia.

## Diagnostyka

### Backend nie odpowiada

Sprawdź:

```text
http://127.0.0.1:8765/health
```

Oczekiwana odpowiedź zawiera status `ok`. Jeśli port jest zajęty, zatrzymaj
poprzedni proces Uvicorn albo uruchom backend na innym porcie i odpowiednio
zmień adres API w frontendzie.

### Aplikacja pokazuje HTTP 401

Najczęstsze przyczyny:

- backend został zrestartowany i poprzedni token wygasł,
- przeglądarka ma zapisany stary token,
- użytkownik nie przeszedł ponownie logowania.

Rozwiązanie: wyloguj się, zaloguj ponownie i odśwież stronę przez `Ctrl+F5`.

### Brak grafiki lub dźwięku

Sprawdź, czy plik istnieje w repozytorium i czy został skopiowany do:

```text
C:\xampp\htdocs\hackathon
```

Można sprawdzić bezpośrednio:

```text
http://127.0.0.1/hackathon/ui-assets/wojownik.png
http://127.0.0.1/hackathon/ui-assets/favicon.ico
```

Po zmianie zasobów wykonaj `Ctrl+F5`, ponieważ przeglądarka może używać
starego cache.

### Multiplayer się nie łączy

Sprawdź, czy:

- FastAPI działa na porcie `8765`,
- strona ma dostęp do adresu serwera,
- firewall Windows nie blokuje portu `8765`,
- frontend i backend używają tego samego hosta lub poprawnie skonfigurowanego
  adresu LAN.

## Walidacja przed oddaniem zmian

Podstawowe kontrole:

```powershell
.\.venv\Scripts\python.exe -m py_compile main.py
git diff --check
```

Kontrola backendu:

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health
```

Po zmianie frontendu przez XAMPP uruchom ponownie `start.bat`, aby skopiować
aktualne pliki do katalogu Apache.

## Zasady rozwoju

- Nie przenoś obliczeń wyniku walki do frontendu.
- Każda zmiana wyniku walki powinna być wykonana w `main.py`.
- Frontend powinien odtwarzać zdarzenia zwrócone przez serwer.
- Nowe zasoby statyczne dodawaj do odpowiedniego katalogu i dopisz ich
  kopiowanie w `start.bat`.
- Nie zapisuj tokenów, kluczy API ani haseł w repozytorium.
- Po zmianach w HTML i zasobach sprawdź zarówno adres FastAPI, jak i adres
  Apache/XAMPP.
