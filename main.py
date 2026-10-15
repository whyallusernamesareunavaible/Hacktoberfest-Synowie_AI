import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import random
import re
import secrets
import time
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator, model_validator

app = FastAPI(title="Arena Gliwic - API buildów i walk")

for _assets_dir in ("Characters", "Potwory", "Wizard", "the-tower-is-jammed-ost", "ui-assets"):
    _assets_path = Path(__file__).resolve().parent / _assets_dir
    if _assets_path.is_dir():
        app.mount(f"/{_assets_dir}", StaticFiles(directory=_assets_path), name=_assets_dir.lower())

# Gdy strony serwuje Apache z XAMPP (http://localhost/...), a API przechodzi
# przez proxy w .htaccess, wszystko jest na jednym adresie i CORS nie jest potrzebny.
# Poniższe adresy przydają się tylko przy uruchomieniu "na bezpośrednio".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1",
                   "http://10.132.198.126",
                   "http://localhost:8765", "http://127.0.0.1:8765",
                   "http://10.132.198.126:8765",
                   "http://localhost:5500", "http://127.0.0.1:5500"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Logowanie (bezhasłowe, token HMAC) ----------

# Przy restarcie serwera losowy sekret unieważnia stare tokeny (użytkownik zaloguje się ponownie).
# W środowisku innym niż lokalne ustaw ARENA_TOKEN_SECRET na stały, prywatny sekret.
TOKEN_SECRET = os.environ.get("ARENA_TOKEN_SECRET") or secrets.token_hex(32)
TOKEN_TTL = 60 * 60 * 12  # 12 godzin
NICK_RE = re.compile(r"^[\w _-]{2,20}$")
bearer = HTTPBearer(auto_error=False)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def wystaw_token(nick: str) -> str:
    payload = _b64(json.dumps({"nick": nick, "exp": int(time.time()) + TOKEN_TTL}).encode())
    sig = _b64(hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def sprawdz_token(token: str) -> str:
    try:
        payload, sig = token.split(".", 1)
        expected = _b64(hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError
        data = json.loads(_unb64(payload))
        if data["exp"] < time.time():
            raise ValueError
        return data["nick"]
    except Exception:
        raise HTTPException(status_code=401, detail="Sesja wygasła lub jest nieprawidłowa. Zaloguj się ponownie.")


def wymagaj_logowania(cred: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> str:
    if cred is None:
        raise HTTPException(status_code=401, detail="Brak tokenu. Zaloguj się.")
    return sprawdz_token(cred.credentials)


class LoginRequest(BaseModel):
    nick: str


# ---------- Dane gry (katalog przedmiotów, klasy) ----------

class Klasa(str, Enum):
    wojownik = "wojownik"
    mag = "mag"
    lotrzyk = "lotrzyk"


SLOTY = {"glowa", "klatka", "bron", "pierscien1", "pierscien2"}

# Bazowe statystyki klas: HP, atak, pancerz, szansa na krytyk (%)
BAZA = {
    Klasa.wojownik: {"hp": 120, "atak": 12, "pancerz": 8, "krytyk": 5},
    Klasa.mag: {"hp": 80, "atak": 18, "pancerz": 2, "krytyk": 8},
    Klasa.lotrzyk: {"hp": 95, "atak": 14, "pancerz": 4, "krytyk": 20},
}

# id -> przedmiot. Rozbuduj o własne!
PRZEDMIOTY: Dict[int, dict] = {
    1: {"nazwa": "Miecz Gliwicki", "slot": "bron", "min_poziom": 1,
        "klasy": ["wojownik", "lotrzyk"], "bonus": {"atak": 8}},
    2: {"nazwa": "Różdżka Radiostacji", "slot": "bron", "min_poziom": 1,
        "klasy": ["mag"], "bonus": {"atak": 12, "krytyk": 3}},
    3: {"nazwa": "Hełm Hutnika", "slot": "glowa", "min_poziom": 3,
        "klasy": ["wojownik", "mag", "lotrzyk"], "bonus": {"pancerz": 4, "hp": 10}},
    4: {"nazwa": "Kolczuga Górnika", "slot": "klatka", "min_poziom": 5,
        "klasy": ["wojownik", "lotrzyk"], "bonus": {"pancerz": 9, "hp": 25}},
    5: {"nazwa": "Pierścień Krytyka", "slot": "pierscien1", "min_poziom": 2,
        "klasy": ["wojownik", "mag", "lotrzyk"], "bonus": {"krytyk": 6}},
    6: {"nazwa": "Pierścień Krytyka", "slot": "pierscien2", "min_poziom": 2,
        "klasy": ["wojownik", "mag", "lotrzyk"], "bonus": {"krytyk": 6}},
}

MAX_POZIOM = 50


def punkty_do_rozdania(poziom: int) -> int:
    return 10 + 3 * (poziom - 1)


# ---------- Modele z walidacją ----------

class Atrybuty(BaseModel):
    sila: int = Field(0, ge=0, le=200)
    zwinnosc: int = Field(0, ge=0, le=200)
    inteligencja: int = Field(0, ge=0, le=200)
    wytrzymalosc: int = Field(0, ge=0, le=200)

    def suma(self) -> int:
        return self.sila + self.zwinnosc + self.inteligencja + self.wytrzymalosc


class Build(BaseModel):
    nazwa: str = Field(..., min_length=2, max_length=30)
    klasa: Klasa
    poziom: int = Field(..., ge=1, le=MAX_POZIOM)
    atrybuty: Atrybuty
    ekwipunek: Dict[str, Optional[int]] = Field(default_factory=dict)

    @field_validator("nazwa")
    @classmethod
    def czysta_nazwa(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Nazwa jest za krótka")
        return v

    @model_validator(mode="after")
    def sprawdz_build(self):
        # 1. Budżet punktów atrybutów
        limit = punkty_do_rozdania(self.poziom)
        if self.atrybuty.suma() > limit:
            raise ValueError(
                f"Rozdano {self.atrybuty.suma()} punktów, a na poziomie "
                f"{self.poziom} możesz maksymalnie {limit}"
            )

        # 2. Ekwipunek: sloty, istnienie przedmiotu, dopasowanie
        for slot, item_id in self.ekwipunek.items():
            if slot not in SLOTY:
                raise ValueError(f"Nieznany slot: '{slot}'. Dozwolone: {sorted(SLOTY)}")
            if item_id is None:
                continue
            item = PRZEDMIOTY.get(item_id)
            if item is None:
                raise ValueError(f"Przedmiot o id {item_id} nie istnieje")
            if item["slot"] != slot:
                raise ValueError(
                    f"'{item['nazwa']}' pasuje do slotu '{item['slot']}', nie '{slot}'"
                )
            if self.poziom < item["min_poziom"]:
                raise ValueError(
                    f"'{item['nazwa']}' wymaga poziomu {item['min_poziom']}"
                )
            if self.klasa.value not in item["klasy"]:
                raise ValueError(
                    f"'{item['nazwa']}' nie jest dostępny dla klasy {self.klasa.value}"
                )

        # 3. Broń wymagana
        if not self.ekwipunek.get("bron"):
            raise ValueError("Postać musi mieć założoną broń")
        return self


class BattleRequest(BaseModel):
    build_a: Build
    build_b: Build
    seed: Optional[int] = None


class ArenaBuild(BaseModel):
    """Snapshot statystyk używany przez serwer do deterministycznej symulacji."""

    nazwa: str = Field(..., min_length=2, max_length=30)
    klasa: Klasa
    staty: Dict[str, float]

    @field_validator("staty")
    @classmethod
    def sprawdz_staty(cls, value: Dict[str, float]) -> Dict[str, float]:
        wymagane = {"atk", "hp", "armor", "crit", "mob", "mag", "as"}
        if set(value) != wymagane:
            raise ValueError("Snapshot buildu ma nieprawidłowy zestaw statystyk")
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v <= 0
            for v in value.values()
        ):
            raise ValueError("Statystyki buildu muszą być dodatnie")
        if value["crit"] > 75 or value["as"] > 10 or value["hp"] > 10000:
            raise ValueError("Statystyka buildu przekracza limit")
        return value


class ArenaBattleRequest(BaseModel):
    build: ArenaBuild
    poziom: int = Field(1, ge=1, le=100)
    cache_seed: int = Field(..., ge=0, le=2**32 - 1)


class ArenaEventRequest(BaseModel):
    poziom: int = Field(..., ge=1, le=100)
    cache_seed: int = Field(..., ge=0, le=2**32 - 1)
    max_hp: float = Field(..., gt=0, le=10000)


class ArenaShopRequest(BaseModel):
    poziom: int = Field(..., ge=1, le=100)
    cache_seed: int = Field(..., ge=0, le=2**32 - 1)


# ---------- Statystyki i walka ----------

def policz_staty(b: Build) -> dict:
    s = dict(BAZA[b.klasa])
    a = b.atrybuty
    s["hp"] += a.wytrzymalosc * 5 + b.poziom * 4
    s["atak"] += a.sila * 1.0 + a.inteligencja * 1.2 + b.poziom
    s["pancerz"] += a.wytrzymalosc * 0.5
    s["krytyk"] += a.zwinnosc * 0.4
    for item_id in b.ekwipunek.values():
        if item_id:
            for k, v in PRZEDMIOTY[item_id]["bonus"].items():
                s[k] += v
    s["krytyk"] = min(s["krytyk"], 75)
    return s


def symuluj(a: Build, b: Build, seed: Optional[int]) -> dict:
    rng = random.Random(seed)
    sa, sb = policz_staty(a), policz_staty(b)
    hp = {a.nazwa: sa["hp"], b.nazwa: sb["hp"]}
    staty = {a.nazwa: sa, b.nazwa: sb}
    kolejnosc = [a.nazwa, b.nazwa]
    log: List[str] = []

    for tura in range(1, 101):
        for atakujacy in kolejnosc:
            cel = kolejnosc[1] if atakujacy == kolejnosc[0] else kolejnosc[0]
            at, ob = staty[atakujacy], staty[cel]
            dmg = max(1.0, at["atak"] - ob["pancerz"] * 0.5)
            dmg *= rng.uniform(0.9, 1.1)
            krytyk = rng.uniform(0, 100) < at["krytyk"]
            if krytyk:
                dmg *= 2
            dmg = round(dmg)
            hp[cel] -= dmg
            log.append(
                f"Tura {tura}: {atakujacy} zadaje {dmg} obrażeń"
                f"{' (KRYTYK!)' if krytyk else ''}. {cel} ma {max(0, round(hp[cel]))} HP."
            )
            if hp[cel] <= 0:
                return {"zwyciezca": atakujacy, "tury": tura,
                        "staty": {a.nazwa: sa, b.nazwa: sb}, "log": log}
    return {"zwyciezca": None, "tury": 100, "staty": {a.nazwa: sa, b.nazwa: sb}, "log": log}


PRZECIWNICY = [
    ("Grzyb", 50, 6, 3, 1.0),
    ("Grzyb Trujący", 68, 8, 5, 1.05),
    ("Grzyb Pancerny", 92, 7, 12, 0.9),
    ("Grzyb Wściekły", 58, 12, 4, 1.35),
]


def symuluj_arene(req: ArenaBattleRequest) -> dict:
    """Wykonuje całą walkę na serwerze i zwraca dane potrzebne tylko do animacji."""
    rng = random.Random(req.cache_seed)
    if req.poziom % 10 == 0:
        typ_przeciwnika = len(PRZECIWNICY)
        nazwa, bazowe_hp, bazowy_atak, bazowy_pancerz, szybkosc = (
            "Evil Wizard", 430, 22, 22, 1.15
        )
    else:
        typ_przeciwnika = rng.randrange(len(PRZECIWNICY))
        nazwa, bazowe_hp, bazowy_atak, bazowy_pancerz, szybkosc = PRZECIWNICY[typ_przeciwnika]
    skala = 1 + 0.15 * (req.poziom - 1)
    przeciwnik = {
        "nazwa": f"{nazwa}{' +' + str((req.poziom - 1) // 5) if req.poziom > 5 else ''}",
        "hp": round(bazowe_hp * skala),
        "atak": bazowy_atak * skala,
        "pancerz": bazowy_pancerz * skala,
        "szybkosc": szybkosc,
    }
    gracz = req.build.staty
    hp_gracza, hp_wroga = gracz["hp"], przeciwnik["hp"]
    czas_gracza, czas_wroga = 1 / gracz["as"], 1 / przeciwnik["szybkosc"]
    zdarzenia: List[dict] = []

    for _ in range(1000):
        if czas_gracza <= czas_wroga:
            czas_gracza += 1 / gracz["as"]
            if rng.random() < 0.05:
                zdarzenia.append({"atakujacy": "gracz", "typ": "unik", "obrazenia": 0,
                                  "hp_gracza": max(0, round(hp_gracza)),
                                  "hp_wroga": max(0, round(hp_wroga))})
            else:
                krytyk = rng.random() * 100 < gracz["crit"]
                obrazenia = max(
                    1,
                    round(
                        (gracz["atk"] + gracz["mag"] * 0.4)
                        * rng.uniform(0.85, 1.15)
                        * 100
                        / (100 + przeciwnik["pancerz"])
                        * (1.5 if krytyk else 1),
                    ),
                )
                hp_wroga -= obrazenia
                zdarzenia.append(
                    {
                        "atakujacy": "gracz",
                        "typ": "krytyk" if krytyk else "trafienie",
                        "obrazenia": obrazenia,
                        "hp_celu": max(0, round(hp_wroga)),
                        "hp_gracza": max(0, round(hp_gracza)),
                    }
                )
        else:
            czas_wroga += 1 / przeciwnik["szybkosc"]
            if rng.random() < gracz["mob"] / (gracz["mob"] + 300):
                zdarzenia.append({"atakujacy": "wrog", "typ": "unik", "obrazenia": 0,
                                  "hp_gracza": max(0, round(hp_gracza)),
                                  "hp_wroga": max(0, round(hp_wroga))})
            else:
                obrazenia = max(
                    1,
                    round(
                        przeciwnik["atak"]
                        * rng.uniform(0.85, 1.15)
                        * 100
                        / (100 + gracz["armor"])
                    ),
                )
                hp_gracza -= obrazenia
                zdarzenia.append(
                    {
                        "atakujacy": "wrog",
                        "typ": "trafienie",
                        "obrazenia": obrazenia,
                        "hp_celu": max(0, round(hp_gracza)),
                        "hp_gracza": max(0, round(hp_gracza)),
                        "hp_wroga": max(0, round(hp_wroga)),
                    }
                )
        if hp_wroga <= 0 or hp_gracza <= 0:
            break

    zwyciezca = "gracz" if hp_wroga <= 0 else "wrog" if hp_gracza <= 0 else None
    boss = req.poziom % 10 == 0
    wygrana = zwyciezca == "gracz"
    nagroda = (80 + req.poziom * 4) if boss else (3 + rng.randrange(5))
    drop = None
    if wygrana and rng.random() < (0.75 if boss else 0.08):
        rarity = 3 if boss else rng.randrange(4)
        loot = [
            ("Miecz Runiczny", "weapon", {"atk": 18, "as": 0.1}),
            ("Pancerz Cienia", "chest", {"armor": 22, "hp": 35}),
            ("Korona Otchłani", "head", {"mag": 22, "hp": 20}),
            ("Buty Błyskawic", "boots", {"mob": 18, "as": 0.12}),
        ][rng.randrange(4)]
        multiplier = [0.75, 1, 1.35, 1.8][rarity]
        drop = {
            "n": loot[0], "t": loot[1], "ri": rarity,
            "price": 35 + rarity * 35,
            "st": {k: round(v * multiplier, 2) for k, v in loot[2].items()},
        }
    return {
        "cache": {"seed": req.cache_seed, "przeciwnik": przeciwnik["nazwa"]},
        "gracz": {
            "nazwa": req.build.nazwa,
            "staty": gracz,
            "max_hp": round(gracz["hp"]),
            "hp": max(0, round(hp_gracza)),
        },
        "przeciwnik": {
            **przeciwnik,
            "typ": typ_przeciwnika,
            "max_hp": przeciwnik["hp"],
            "hp": max(0, round(hp_wroga)),
        },
        "zdarzenia": zdarzenia,
        "zwyciezca": zwyciezca,
        "poziom": req.poziom,
        "boss": boss,
        "nagroda": nagroda if wygrana else 0,
        "drop": drop,
        "event_available": req.poziom > 1 and rng.random() < 0.22,
    }


def rozstrzygnij_wydarzenie(req: ArenaEventRequest) -> dict:
    rng = random.Random(req.cache_seed)
    if rng.random() < 0.35:
        return {"typ": "pułapka", "obrazenia": max(1, round(req.max_hp * 0.22)),
                "drop": None, "cache_seed": req.cache_seed}
    rarity = 0 if rng.random() < 0.78 else 2
    loot = [
        ("Miecz Runiczny", "weapon", {"atk": 18, "as": 0.1}),
        ("Pancerz Cienia", "chest", {"armor": 22, "hp": 35}),
        ("Korona Otchłani", "head", {"mag": 22, "hp": 20}),
        ("Buty Błyskawic", "boots", {"mob": 18, "as": 0.12}),
    ][rng.randrange(4)]
    drop = {"n": loot[0], "t": loot[1], "ri": rarity,
            "price": 35 + rarity * 35,
            "st": {k: round(v * [0.75, 1, 1.35, 1.8][rarity], 2)
                   for k, v in loot[2].items()}}
    return {"typ": "drop", "obrazenia": 0, "drop": drop,
            "cache_seed": req.cache_seed}


def wygeneruj_sklep(seed: int) -> list[dict]:
    rng = random.Random(seed)
    pool = [
        ("Miecz Runiczny", "weapon", {"atk": 18, "as": 0.1}),
        ("Pancerz Cienia", "chest", {"armor": 22, "hp": 35}),
        ("Korona Otchłani", "head", {"mag": 22, "hp": 20}),
        ("Buty Błyskawic", "boots", {"mob": 18, "as": 0.12}),
        ("Pierścień Smoka", "ring", {"atk": 10, "crit": 5}),
        ("Amulet Dusz", "amulet", {"mag": 18, "crit": 4}),
    ]
    sklep = []
    for _ in range(3):
        rarity = rng.randrange(4)
        name, slot, stats = pool[rng.randrange(len(pool))]
        multiplier = [0.75, 1, 1.35, 1.8][rarity]
        sklep.append({
            "n": name, "t": slot, "ri": rarity, "price": 35 + rarity * 35,
            "st": {k: round(v * multiplier, 2) for k, v in stats.items()},
        })
    return sklep


# ---------- Endpointy ----------

# Strony HTML. W XAMPP serwuje je Apache, ale te trasy pozwalają też uruchomić
# samo FastAPI (http://127.0.0.1:8765/) bez Apache'a.
BASE_DIR = Path(__file__).parent


def _strona(nazwa: str):
    plik = BASE_DIR / nazwa
    if not plik.is_file():
        return JSONResponse(status_code=404, content={"error": f"Nie znaleziono pliku {nazwa}"})
    return FileResponse(plik, media_type="text/html")


@app.get("/")
@app.get("/login.html")
def strona_logowania():
    return _strona("login.html")


@app.get("/arena.html")
def strona_areny():
    return _strona("arena.html")


@app.get("/kreator-bohatera.html")
def strona_kreatora():
    return _strona("kreator-bohatera.html")


@app.post("/auth/token")
def logowanie(req: LoginRequest):
    nick = " ".join(req.nick.split())
    if not NICK_RE.fullmatch(nick):
        raise HTTPException(status_code=422,
                            detail="Nick: 2–20 znaków, litery, cyfry, spacja, _ lub -.")
    return {"access_token": wystaw_token(nick), "token_type": "bearer", "nick": nick}


@app.get("/health")
def zdrowie():
    return {"ok": True, "service": "arena"}


@app.exception_handler(RequestValidationError)
async def blad_walidacji(request: Request, exc: RequestValidationError):
    bledy: Dict[str, str] = {}
    for err in exc.errors():
        pole = ".".join(str(p) for p in err["loc"] if p != "body") or "build"
        bledy.setdefault(pole, err["msg"].removeprefix("Value error, "))
    return JSONResponse(status_code=422, content={"errors": bledy})


@app.get("/przedmioty")
def lista_przedmiotow(_nick: str = Depends(wymagaj_logowania)):
    """Katalog dla frontendu (listy wyboru ekwipunku)."""
    return {"sloty": sorted(SLOTY), "przedmioty": PRZEDMIOTY}


@app.post("/build/validate")
def waliduj_build(build: Build, _nick: str = Depends(wymagaj_logowania)):
    """Jeśli dotarło tutaj, build jest poprawny. Zwraca policzone statystyki."""
    return {"ok": True, "staty": policz_staty(build),
            "pozostale_punkty": punkty_do_rozdania(build.poziom) - build.atrybuty.suma()}


@app.post("/battle")
def walka(req: BattleRequest, _nick: str = Depends(wymagaj_logowania)):
    if req.build_a.nazwa == req.build_b.nazwa:
        return JSONResponse(status_code=422,
                            content={"errors": {"nazwa": "Postacie muszą mieć różne nazwy"}})
    return symuluj(req.build_a, req.build_b, req.seed)


@app.post("/arena/battle")
def walka_areny(req: ArenaBattleRequest, _nick: str = Depends(wymagaj_logowania)):
    return symuluj_arene(req)


@app.post("/arena/event")
def wydarzenie_areny(req: ArenaEventRequest, _nick: str = Depends(wymagaj_logowania)):
    return rozstrzygnij_wydarzenie(req)


@app.post("/arena/shop")
def sklep_areny(req: ArenaShopRequest, _nick: str = Depends(wymagaj_logowania)):
    return {"cache_seed": req.cache_seed, "items": wygeneruj_sklep(req.cache_seed)}


@app.get("/lobby.html")
def strona_lobby():
    return _strona("lobby.html")

# ======================= MULTIPLAYER (WebSocket: /ws/lobby) =======================
# Serwer jest autorytatywny: klient wysyła tylko DEFINICJĘ buildu (klasa, punkty umiejętności,
# ekwipunek), a statystyki i wynik walki liczy serwer. Dane poniżej odzwierciedlają kreator.

K_KLASY = {
    "war": ({"atk": 18, "hp": 150, "armor": 30, "crit": 5, "mob": 30, "mag": 5, "as": 1.0},
            [(5, {"atk": 3}), (5, {"hp": 15}), (5, {"armor": 4}), (5, {"crit": 1.5}), (3, {"mob": 5}), (3, {"as": 0.04})]),
    "mag": ({"atk": 10, "hp": 90, "armor": 10, "crit": 8, "mob": 40, "mag": 45, "as": 1.0},
            [(5, {"mag": 5}), (5, {"atk": 3}), (5, {"armor": 3}), (5, {"crit": 1.5}), (3, {"mob": 6}), (5, {"hp": 8})]),
    "rog": ({"atk": 15, "hp": 110, "armor": 15, "crit": 20, "mob": 60, "mag": 10, "as": 1.1},
            [(5, {"crit": 2}), (5, {"mob": 5}), (5, {"atk": 2.5}), (5, {"armor": 3}), (3, {"as": 0.06}), (5, {"atk": 1.5, "mag": 2})]),
}
K_NAZWY = {"war": "Wojownik", "mag": "Mag", "rog": "Łotrzyk"}
K_BAZOWE = [
    ("Hełm Strażnika", "head", {"armor": 8, "hp": 20}), ("Kaptur Cienia", "head", {"crit": 3, "mob": 4}),
    ("Korona Maga", "head", {"mag": 8, "hp": 10}), ("Kolczuga", "chest", {"armor": 14, "hp": 30}),
    ("Szata Arcymaga", "chest", {"mag": 12, "armor": 4}), ("Skórzana Kurtka", "chest", {"mob": 6, "crit": 2, "armor": 6}),
    ("Miecz Bojowy", "weapon", {"atk": 12, "as": 0.05}), ("Różdżka Burzy", "weapon", {"atk": 7, "mag": 12}),
    ("Sztylet Zabójcy", "weapon", {"atk": 8, "crit": 6, "as": 0.12}), ("Tarcza Wieży", "off", {"armor": 16, "hp": 25}),
    ("Księga Zaklęć", "off", {"mag": 10, "crit": 2}), ("Pierścień Mocy", "ring", {"atk": 4, "crit": 1.5}),
    ("Sygnet Życia", "ring", {"hp": 30}), ("Buty Wędrowca", "boots", {"mob": 10, "armor": 2}),
    ("Ciężkie Buty", "boots", {"armor": 7, "hp": 10}), ("Amulet Mądrości", "amulet", {"mag": 9, "hp": 10}),
    ("Talizman Łowcy", "amulet", {"crit": 3, "atk": 3}),
]
K_SLOTY = {"head": "head", "chest": "chest", "boots": "boots", "amulet": "amulet",
           "weapon": "weapon", "off": "off", "ring1": "ring", "ring2": "ring"}
K_PRZEDMIOTY = {
    f"{n}{i}": {"typ": t, "st": {k: round(v * m, 2 if k == "as" else 1) for k, v in st.items()}}
    for n, t, st in K_BAZOWE for i, m in enumerate((1, 1.4, 1.9, 2.6))
}
K_PUNKTY = 10


def staty_z_kreatora(b) -> dict:
    """Waliduje build z kreatora i liczy statystyki. Rzuca ValueError przy oszustwie/błędzie."""
    if not isinstance(b, dict) or b.get("c") not in K_KLASY:
        raise ValueError("Nieprawidłowy build albo klasa")
    baza, umiej = K_KLASY[b["c"]]
    t = dict(baza)
    rk, eq = b.get("rk") or {}, b.get("eq") or {}
    if not isinstance(rk, dict) or not isinstance(eq, dict) or len(rk) > 12 or len(eq) > 12:
        raise ValueError("Nieprawidłowy build")
    suma = 0
    for k, r in rk.items():
        try:
            i = int(k)
        except (TypeError, ValueError):
            raise ValueError("Nieprawidłowe umiejętności")
        if not 0 <= i < len(umiej) or isinstance(r, bool) or not isinstance(r, int) or not 0 <= r <= umiej[i][0]:
            raise ValueError("Nieprawidłowe punkty umiejętności")
        suma += r
        for stat, v in umiej[i][1].items():
            t[stat] += v * r
    if suma > K_PUNKTY:
        raise ValueError(f"Rozdano {suma} punktĂłw, limit to {K_PUNKTY}")
    for slot, iid in eq.items():
        if iid is None:
            continue
        it = K_PRZEDMIOTY.get(iid) if isinstance(iid, str) else None
        if slot not in K_SLOTY or it is None or it["typ"] != K_SLOTY[slot]:
            raise ValueError(f"Nieprawidłowy przedmiot w slocie '{slot}'")
        for stat, v in it["st"].items():
            t[stat] += v
    t["crit"] = min(t["crit"], 75)
    t["dps"] = (t["atk"] + t["mag"] * 0.4) * (1 + t["crit"] / 100 * 0.5) * t["as"]
    return {k: round(v, 2) for k, v in t.items()}


def symuluj_pvp(sa: dict, sb: dict, seed: int) -> dict:
    """Walka 1v1 oparta na czasie ataków. Zdarzenia: a=indeks atakującego, k=hit|crit|miss."""
    rng = random.Random(seed)
    s, hp = [sa, sb], [sa["hp"], sb["hp"]]
    mx, t, zd = [round(x) for x in hp], [1 / sa["as"], 1 / sb["as"]], []
    snap = lambda: [max(0, round(h)) for h in hp]
    for _ in range(600):
        a = 0 if t[0] < t[1] - 1e-9 else 1 if t[1] < t[0] - 1e-9 else rng.randrange(2)
        d = 1 - a
        t[a] += 1 / s[a]["as"]
        if rng.random() < s[d]["mob"] / (s[d]["mob"] + 300):
            zd.append({"a": a, "k": "miss", "d": 0, "hp": snap()})
            continue
        kryt = rng.random() * 100 < s[a]["crit"]
        dmg = max(1, round((s[a]["atk"] + s[a]["mag"] * 0.4) * rng.uniform(0.85, 1.15)
                           * 100 / (100 + s[d]["armor"]) * (1.5 if kryt else 1)))
        hp[d] -= dmg
        zd.append({"a": a, "k": "crit" if kryt else "hit", "d": dmg, "hp": snap()})
        if hp[d] <= 0:
            return {"events": zd, "winner": a, "max": mx, "seed": seed}
    p = [hp[0] / sa["hp"], hp[1] / sb["hp"]]
    return {"events": zd, "winner": 0 if p[0] > p[1] else 1 if p[1] > p[0] else None, "max": mx, "seed": seed}


RANKING_PLIK = Path(__file__).with_name("ranking.json")


def _wczytaj_ranking() -> dict:
    try:
        r = json.loads(RANKING_PLIK.read_text(encoding="utf-8"))
        return r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        return {}


RANKING: Dict[str, dict] = _wczytaj_ranking()


def _wpis(nick: str) -> dict:
    return RANKING.setdefault(nick.lower(), {"nick": nick, "elo": 1000, "w": 0, "l": 0, "r": 0})


def _zapisz_ranking() -> None:
    try:
        tmp = RANKING_PLIK.with_suffix(".tmp")
        tmp.write_text(json.dumps(RANKING, ensure_ascii=False), encoding="utf-8")
        tmp.replace(RANKING_PLIK)
    except OSError:
        pass


def _wynik(a: "Gracz", b: "Gracz", zwyciezca: Optional[int]):
    ra, rb = _wpis(a.nick), _wpis(b.nick)
    przed = [ra["elo"], rb["elo"]]
    sa = 0.5 if zwyciezca is None else 1.0 if zwyciezca == 0 else 0.0
    ea = 1 / (1 + 10 ** ((rb["elo"] - ra["elo"]) / 400))
    ra["elo"], rb["elo"] = round(ra["elo"] + 24 * (sa - ea)), round(rb["elo"] + 24 * ((1 - sa) - (1 - ea)))
    for w, kl in ((ra, "w" if sa == 1 else "l" if sa == 0 else "r"), (rb, "l" if sa == 1 else "w" if sa == 0 else "r")):
        w[kl] += 1
    _zapisz_ranking()
    return przed, [ra["elo"], rb["elo"]]


NICK_RE = re.compile(r"^[\w -]{2,20}$")
ONLINE: Dict[str, "Gracz"] = {}
_ZADANIA: set = set()


class Gracz:
    def __init__(self, ws, nick: str, klasa: str, staty: dict):
        self.ws, self.nick, self.klasa, self.staty = ws, nick, klasa, staty
        self.key, self.status, self.cel, self.duel, self.ts = nick.lower(), "idle", None, None, []

    def opis(self) -> dict:
        w, s = _wpis(self.nick), self.staty
        return {"nick": self.nick, "c": self.klasa, "cn": K_NAZWY[self.klasa], "hp": round(s["hp"]),
                "dps": round(s["dps"], 1), "armor": round(s["armor"]), "st": self.status,
                "elo": w["elo"], "w": w["w"], "l": w["l"]}


async def _wyslij(g: Gracz, msg: dict) -> None:
    try:
        await g.ws.send_json(msg)
    except Exception:
        pass


async def _blad(g: Gracz, m: str, fatal: bool = False) -> None:
    await _wyslij(g, {"t": "error", "m": m, "fatal": fatal})


async def _odswiez() -> None:
    top = sorted((v for v in RANKING.values() if v["w"] + v["l"] + v["r"]), key=lambda v: -v["elo"])[:10]
    msg = {"t": "lobby", "players": [g.opis() for g in ONLINE.values()],
           "ranking": [{k: v[k] for k in ("nick", "elo", "w", "l")} for v in top]}
    await asyncio.gather(*(_wyslij(g, msg) for g in list(ONLINE.values())))


async def _wyslij_ch(g: Optional[Gracz]) -> None:
    if g is not None and ONLINE.get(g.key) is g:
        cel = ONLINE.get(g.cel) if g.cel else None
        await _wyslij(g, {"t": "ch", "out": cel.nick if cel else None,
                          "inc": [x.nick for x in list(ONLINE.values()) if x.cel == g.key]})


async def _odblokuj(g: Gracz, did: str) -> None:
    await asyncio.sleep(90)  # zabezpieczenie, gdyby klient nie wysłał "done"
    if g.duel == did:
        g.status, g.duel = "idle", None
        await _odswiez()


async def _pojedynek(a: Gracz, b: Gracz) -> None:
    cele = {a.cel, b.cel}
    a.cel = b.cel = None
    dotkniete = [ONLINE.get(k) for k in cele]
    for x in list(ONLINE.values()):
        if x.cel in (a.key, b.key):
            x.cel = None
            dotkniete.append(x)
            await _wyslij(x, {"t": "info", "m": "Rywal rozpoczął inną walkę, wyzwanie wygasło."})
    r = symuluj_pvp(a.staty, b.staty, secrets.randbits(32))
    opisy = [a.opis(), b.opis()]
    przed, po = _wynik(a, b, r["winner"])
    did = secrets.token_hex(4)
    for i, g in enumerate((a, b)):
        g.status, g.duel = "duel", did
        await _wyslij(g, {"t": "duel", "you": i, "players": opisy, "elo": {"przed": przed, "po": po}, **r})
        task = asyncio.create_task(_odblokuj(g, did))
        _ZADANIA.add(task)
        task.add_done_callback(_ZADANIA.discard)
    for x in {a, b, *dotkniete}:
        await _wyslij_ch(x)
    await _odswiez()


async def _obsluz(g: Gracz, m: dict) -> None:
    t = m.get("t")
    if t == "build":
        if g.status != "idle" or g.cel:
            return await _blad(g, "Nie możesz zmienić buildu w trakcie wyzwania lub walki.")
        try:
            g.staty = staty_z_kreatora(m.get("build"))
        except ValueError as e:
            return await _blad(g, str(e))
        g.klasa = m["build"]["c"]
        await _wyslij(g, {"t": "welcome", "nick": g.nick, "me": g.staty})
        await _odswiez()
    elif t == "challenge":
        c = ONLINE.get(str(m.get("to", "")).lower())
        if c is None or c is g:
            return await _blad(g, "Nie ma takiego gracza online.")
        if g.status != "idle" or g.cel:
            return await _blad(g, "Masz już aktywne wyzwanie albo trwa walka.")
        if c.status != "idle":
            return await _blad(g, f"{c.nick} jest w walce.")
        g.cel = c.key
        await _wyslij_ch(g)
        await _wyslij_ch(c)
    elif t == "cancel":
        c = ONLINE.get(g.cel) if g.cel else None
        g.cel = None
        await _wyslij_ch(g)
        await _wyslij_ch(c)
    elif t in ("accept", "decline"):
        c = ONLINE.get(str(m.get("from", "")).lower())
        if c is None or c.cel != g.key:
            return await _blad(g, "To wyzwanie już nie istnieje.")
        if t == "decline":
            c.cel = None
            await _wyslij(c, {"t": "info", "m": f"{g.nick} odrzucił Twoje wyzwanie."})
            await _wyslij_ch(c)
            await _wyslij_ch(g)
        elif g.status != "idle" or c.status != "idle":
            await _blad(g, "Któryś z graczy jest akurat w walce.")
        else:
            await _pojedynek(c, g)
    elif t == "done" and g.status == "duel":
        g.status, g.duel = "idle", None
        await _odswiez()


async def _odlacz(g: Gracz) -> None:
    ONLINE.pop(g.key, None)
    dotkniete = [ONLINE.get(g.cel)] if g.cel else []
    for x in list(ONLINE.values()):
        if x.cel == g.key:
            x.cel = None
            dotkniete.append(x)
    for x in dotkniete:
        await _wyslij_ch(x)
    await _odswiez()


@app.websocket("/ws/lobby")
async def ws_lobby(ws: WebSocket):
    await ws.accept()
    g: Optional[Gracz] = None
    try:
        try:
            m = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=15))
        except (ValueError, asyncio.TimeoutError):
            m = None
        nick = " ".join(str(m.get("nick", "")).split()) if isinstance(m, dict) else ""
        tmp = Gracz(ws, nick or "?", "war", {})
        if not isinstance(m, dict) or m.get("t") != "join" or not NICK_RE.fullmatch(nick):
            return await _blad(tmp, "Nieprawidłowy nick (2–20 znaków: litery, cyfry, spacja, _ lub -).", True)
        try:
            staty = staty_z_kreatora(m.get("build"))
        except ValueError as e:
            return await _blad(tmp, str(e), True)
        if nick.lower() in ONLINE:
            return await _blad(tmp, "Ten nick jest już online (może masz otwartą drugą kartę).", True)
        g = Gracz(ws, nick, m["build"]["c"], staty)
        ONLINE[g.key] = g
        await _wyslij(g, {"t": "welcome", "nick": g.nick, "me": g.staty})
        await _odswiez()
        while True:
            raw = await ws.receive_text()
            now = time.monotonic()
            g.ts = [x for x in g.ts if now - x < 5] + [now]
            if len(g.ts) > 25:  # prosty limit: max 25 wiadomości / 5 s
                return await ws.close(code=1008)
            try:
                msg = json.loads(raw) if len(raw) < 4000 else None
            except ValueError:
                msg = None
            if isinstance(msg, dict):
                await _obsluz(g, msg)
    except WebSocketDisconnect:
        pass
    finally:
        if g is not None and ONLINE.get(g.key) is g:
            await _odlacz(g)
        try:
            await ws.close()
        except Exception:
            pass
