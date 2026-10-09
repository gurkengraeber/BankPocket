"""Datenbankschema (SQLAlchemy 2). SQLite zum Start, Postgres später über BANKPOCKET_DB_URL möglich."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from decimal import Decimal

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, String, Text, TypeDecorator,
                        UniqueConstraint, create_engine, event, inspect, select)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .models import monatsbetrag

GRUPPEN = ["Tägliche Konten", "Sparkonten", "Crypto", "Virtuell"]
KONTOTYPEN = ["giro", "spar", "depot", "krypto", "virtuell", "kreditkarte"]


class Money(TypeDecorator):
    """Geldbetrag als Ganzzahl in Cent – exakt und ohne SQLite-Decimal-Probleme."""
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else int((Decimal(value) * 100).to_integral_value())

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value) / 100


class ExactDecimal(TypeDecorator):
    """Beliebig genaue Dezimalzahl als Text (Krypto-Mengen mit 8+ Nachkommastellen)."""
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else str(Decimal(value))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class Base(DeclarativeBase):
    pass


class Connection(Base):
    """Zugang zu einer Bank (FinTS). Zugangsdaten nur verschlüsselt (siehe vault.py)."""
    __tablename__ = "connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    art: Mapped[str] = mapped_column(String(16), default="fints")
    bank: Mapped[str] = mapped_column(String(32))  # ing, consorsbank, andere
    name: Mapped[str] = mapped_column(String(60))
    blz: Mapped[str] = mapped_column(String(12))
    server_url: Mapped[str] = mapped_column(String(200))
    login_enc: Mapped[str] = mapped_column(Text)
    pin_enc: Mapped[str] = mapped_column(Text)
    client_data_enc: Mapped[str | None] = mapped_column(Text)  # FinTS-Sitzungsdaten (System-ID, BPD/UPD)
    tan_verfahren: Mapped[str | None] = mapped_column(String(10))
    tan_verfahren_name: Mapped[str | None] = mapped_column(String(80))
    tan_medium: Mapped[str | None] = mapped_column(String(80))
    # neu | laeuft | ok | fehler | freigabe_noetig | auswahl_noetig | pin_falsch | gesperrt
    status: Mapped[str] = mapped_column(String(20), default="neu")
    meldung: Mapped[str] = mapped_column(Text, default="")
    letzter_versuch: Mapped[datetime | None] = mapped_column(DateTime)
    letzter_erfolg: Mapped[datetime | None] = mapped_column(DateTime)
    letzte_freigabe: Mapped[datetime | None] = mapped_column(DateTime)  # letzte starke Authentifizierung
    fehler_in_folge: Mapped[int] = mapped_column(Integer, default=0)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    quelle: Mapped[str] = mapped_column(String(32))  # ing, consorsbank, trade_republic, binance, manuell …
    name: Mapped[str] = mapped_column(String(100))
    typ: Mapped[str] = mapped_column(String(16))
    gruppe: Mapped[str] = mapped_column(String(32))
    waehrung: Mapped[str] = mapped_column(String(8), default="EUR")
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)  # False = „Geschlossen“
    # eigene Reihenfolge innerhalb der Gruppe; neue Konten stehen hinten, bis man sie einsortiert
    position: Mapped[int] = mapped_column(Integer, default=9999)
    zuletzt_aktualisiert: Mapped[datetime | None] = mapped_column(DateTime)  # „Stand“
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("connections.id", ondelete="SET NULL"))
    iban: Mapped[str | None] = mapped_column(String(40))
    kontonummer: Mapped[str | None] = mapped_column(String(40))
    unterkonto: Mapped[str | None] = mapped_column(String(10))
    balances: Mapped[list[Balance]] = relationship(back_populates="account", cascade="all, delete-orphan")


class Balance(Base):
    __tablename__ = "balances"
    __table_args__ = (UniqueConstraint("account_id", "datum"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    datum: Mapped[date] = mapped_column(Date)
    saldo: Mapped[Decimal] = mapped_column(Money)
    account: Mapped[Account] = relationship(back_populates="balances")


class TransactionRow(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    buchungsdatum: Mapped[date] = mapped_column(Date, index=True)
    betrag: Mapped[Decimal] = mapped_column(Money)
    gegenpartei: Mapped[str] = mapped_column(String(200), default="")
    iban_gegenpartei: Mapped[str] = mapped_column(String(40), default="")
    verwendungszweck: Mapped[str] = mapped_column(Text, default="")
    glaeubiger_id: Mapped[str] = mapped_column(String(40), default="")
    mandatsreferenz: Mapped[str] = mapped_column(String(80), default="")
    kategorie: Mapped[str | None] = mapped_column(String(40))
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id", ondelete="SET NULL"))
    hash: Mapped[str] = mapped_column(String(64), unique=True)  # Deduplizierung
    rohdaten: Mapped[str] = mapped_column(Text, default="")  # Originalzeile, unverändert
    gesehen: Mapped[bool] = mapped_column(Boolean, default=False)  # Badge „neue Buchungen“
    intern: Mapped[bool] = mapped_column(Boolean, default=False)  # Umbuchung zwischen eigenen Konten
    intern_fix: Mapped[bool] = mapped_column(Boolean, default=False)  # Umbuchung vom Nutzer festgelegt – bleibt so
    # Umbuchung nur, weil der eigene Name als Gegenseite steht – lässt sich mit der Einstellung zurücknehmen
    intern_name: Mapped[bool] = mapped_column(Boolean, default=False)
    notiz: Mapped[str] = mapped_column(Text, default="")
    gegenbuchung_id: Mapped[int | None] = mapped_column(Integer)  # andere Seite einer Umbuchung (eigenes Konto)
    paar_nein: Mapped[str] = mapped_column(Text, default="")  # Buchungen, die der Nutzer als Gegenbuchung ablehnt
    vertrag_fix: Mapped[bool] = mapped_column(Boolean, default=False)  # Vertragszuordnung vom Nutzer – bleibt so
    tags: Mapped[str] = mapped_column(Text, default="")  # frei vergebene Schlagworte, durch Komma getrennt
    ausgeschlossen: Mapped[bool] = mapped_column(Boolean, default=False)  # zählt nicht bei „frei verfügbar“
    steuer: Mapped[str] = mapped_column(String(4), default="")  # Steuerliste: "" = automatisch, "ja", "nein"
    # Geld kam zurück (Erstattung, Freund zahlt seinen Teil): mindert die Ausgaben der Kategorie statt Einnahme zu sein
    rueckzahlung: Mapped[bool] = mapped_column(Boolean, default=False)
    buchungstext: Mapped[str] = mapped_column(String(80), default="")  # z. B. „Lastschrift“
    importiert_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Holding(Base):
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    datum: Mapped[date] = mapped_column(Date)
    symbol: Mapped[str] = mapped_column(String(20))  # ISIN oder Ticker
    name: Mapped[str] = mapped_column(String(120), default="")
    einstand: Mapped[Decimal | None] = mapped_column(ExactDecimal)  # durchschnittlicher Kaufkurs je Stück
    menge: Mapped[Decimal] = mapped_column(ExactDecimal)
    kurs: Mapped[Decimal] = mapped_column(ExactDecimal)
    wert: Mapped[Decimal] = mapped_column(Money)


class Price(Base):
    """Tageskurs eines Wertpapiers – für den Wertverlauf einzelner Positionen."""
    __tablename__ = "prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    datum: Mapped[date] = mapped_column(Date)
    kurs: Mapped[Decimal] = mapped_column(ExactDecimal)


class ContractRow(Base):
    __tablename__ = "contracts"
    id: Mapped[int] = mapped_column(primary_key=True)
    schluessel: Mapped[str | None] = mapped_column(String(300), unique=True)  # None bei manuellen Verträgen
    name: Mapped[str] = mapped_column(String(200))
    kategorie: Mapped[str] = mapped_column(String(40))
    turnus: Mapped[str] = mapped_column(String(16))
    erwarteter_betrag: Mapped[Decimal] = mapped_column(Money)
    letzte_zahlung: Mapped[date | None] = mapped_column(Date)
    naechste_faelligkeit: Mapped[date] = mapped_column(Date)
    typ: Mapped[str] = mapped_column(String(10))
    quelle: Mapped[str] = mapped_column(String(10), default="auto")
    methode: Mapped[str] = mapped_column(String(16), default="")
    vorkommen: Mapped[int] = mapped_column(Integer, default=0)
    sicherheit: Mapped[int] = mapped_column(Integer, default=0)  # 0–100, wie sicher die Erkennung ist
    betrag_gestiegen: Mapped[bool] = mapped_column(Boolean, default=False)
    vorheriger_betrag: Mapped[Decimal | None] = mapped_column(Money)
    bearbeitet: Mapped[bool] = mapped_column(Boolean, default=False)  # Name/Kategorie vom Nutzer gesetzt
    entfernt: Mapped[bool] = mapped_column(Boolean, default=False)  # vom Nutzer entfernt, nicht neu anlegen
    nicht_mehr_erkannt: Mapped[bool] = mapped_column(Boolean, default=False)
    bestaetigt: Mapped[bool] = mapped_column(Boolean, default=False)  # Nutzer hat „ja, das ist ein Vertrag“ gesagt
    betrag_fix: Mapped[bool] = mapped_column(Boolean, default=False)  # Betrag vom Nutzer festgelegt – bleibt so
    # Selbst angelegte Verträge: Woran passende Buchungen erkannt werden (siehe contracts.muster)
    muster: Mapped[str | None] = mapped_column(String(300))
    # Vom Nutzer gepflegte Vertragsdaten: was es ist, bis wann es läuft und wie man herauskommt
    art: Mapped[str] = mapped_column(String(300), default="")  # z. B. „Haftpflicht“, „Mobilfunk“, „Abo“
    frist_wert: Mapped[int | None] = mapped_column(Integer)  # Kündigungsfrist: Anzahl …
    frist_einheit: Mapped[str] = mapped_column(String(8), default="")  # … tage | wochen | monate
    laufzeit_bis: Mapped[date | None] = mapped_column(Date)  # Ende der laufenden Vertragslaufzeit
    verlaengerung_monate: Mapped[int | None] = mapped_column(Integer)  # verlängert sich danach um so viele Monate
    kuendigen: Mapped[bool] = mapped_column(Boolean, default=False)  # „will ich kündigen“ – rechtzeitig erinnern
    vertragsnummer: Mapped[str] = mapped_column(String(80), default="")
    notiz: Mapped[str] = mapped_column(Text, default="")
    anteil_prozent: Mapped[int] = mapped_column(Integer, default=100)  # geteilte Verträge: so viel davon zahle ich
    gekuendigt_zum: Mapped[date | None] = mapped_column(Date)  # Kündigung ist raus: der Vertrag endet an diesem Tag
    # Versicherungen: wo der Vertrag liegt und was im Schadensfall zählt
    verwaltet_ueber: Mapped[str] = mapped_column(String(20), default="")  # direkt | makler | app | portal | …
    verwaltet_name: Mapped[str] = mapped_column(String(80), default="")  # z. B. „Clark“, „Check24“, Name des Maklers
    versichert: Mapped[str] = mapped_column(String(20), default="")  # ich | partner | familie | haushalt
    selbstbeteiligung: Mapped[Decimal | None] = mapped_column(Money)
    kontakt: Mapped[str] = mapped_column(String(200), default="")  # Telefon oder Adresse für Schadensmeldungen

    @property
    def mein_betrag(self) -> Decimal:
        """Der eigene Anteil am Betrag – bei geteilten Verträgen (WG-Miete, Familien-Abo) weniger als abgebucht."""
        return (self.erwarteter_betrag * (self.anteil_prozent or 100) / 100).quantize(Decimal("0.01"))

    @property
    def gilt(self) -> bool:
        """Erkannte Verträge sind bis zur Bestätigung nur Vorschläge und zählen nirgends mit."""
        return self.quelle == "manuell" or bool(self.bestaetigt)

    @property
    def monatlich(self) -> Decimal:
        return monatsbetrag(self.erwarteter_betrag, self.turnus) * (self.anteil_prozent or 100) / 100


class Budget(Base):
    __tablename__ = "budgets"
    id: Mapped[int] = mapped_column(primary_key=True)
    kategorie: Mapped[str] = mapped_column(String(40))
    limit: Mapped[Decimal] = mapped_column(Money)
    zeitraum: Mapped[str] = mapped_column(String(16), default="monatlich")


class Notice(Base):
    """Hinweis in der App (und optional als Push): Freigabe nötig, neuer Vertrag, …"""
    __tablename__ = "hinweise"
    id: Mapped[int] = mapped_column(primary_key=True)
    art: Mapped[str] = mapped_column(String(20))
    titel: Mapped[str] = mapped_column(String(160))
    text: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(160), default="")
    schluessel: Mapped[str | None] = mapped_column(String(200), unique=True)  # verhindert Doppelmeldungen
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    gelesen: Mapped[bool] = mapped_column(Boolean, default=False)


class PushSubscription(Base):
    __tablename__ = "push_abos"
    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class KategorieRow(Base):
    """Eigene Kategorie (zusätzlich zu den eingebauten)."""
    __tablename__ = "kategorien"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    emoji: Mapped[str] = mapped_column(String(16), default="🏷️")
    typ: Mapped[str] = mapped_column(String(10), default="ausgabe")
    ober: Mapped[str] = mapped_column(String(40), default="")  # Unterkategorie von … (leer = eigenständig)


class Bereich(Base):
    """Ein Lebensbereich wie „Wohnung“ oder „Auto“: Kategorien und einzelne Verträge, die zusammen ein Thema
    ausmachen – für die Frage „Was kostet mich das im Monat?“."""
    __tablename__ = "bereiche"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    emoji: Mapped[str] = mapped_column(String(16), default="🏡")
    kategorien: Mapped[str] = mapped_column(Text, default="[]")  # JSON-Liste von Kategorienamen
    vertraege: Mapped[str] = mapped_column(Text, default="[]")  # JSON-Liste von Vertrags-IDs


class RegelRow(Base):
    """Stichwort → Kategorie; Nutzerregeln haben Vorrang vor den eingebauten."""
    __tablename__ = "regeln"
    id: Mapped[int] = mapped_column(primary_key=True)
    stichwort: Mapped[str] = mapped_column(String(80))
    kategorie: Mapped[str] = mapped_column(String(40))
    typ: Mapped[str] = mapped_column(String(10), default="ausgabe")


class KiKategorieRow(Base):
    """Von der KI eingeordneter Händler – jeder Händler wird nur einmal gefragt."""
    __tablename__ = "ki_kategorien"
    typ: Mapped[str] = mapped_column(String(10), primary_key=True)
    schluessel: Mapped[str] = mapped_column(String(200), primary_key=True)  # normalisierter Händlername
    kategorie: Mapped[str] = mapped_column(String(40))
    erstellt: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class KeyValue(Base):
    __tablename__ = "einstellungen"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")  # Lesen während Abrufe schreiben
    cur.execute("PRAGMA busy_timeout=15000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def ensure_schema(engine: Engine) -> None:
    """Tabellen anlegen und neue Spalten ergänzen – einfache Migration für additive Schemaänderungen."""
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            vorhanden = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in vorhanden:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                default = col.default.arg if col.default is not None and col.default.is_scalar else None
                if isinstance(default, bool):
                    ddl += f" DEFAULT {int(default)}"
                elif isinstance(default, int):
                    ddl += f" DEFAULT {default}"
                elif isinstance(default, str):
                    ddl += " DEFAULT '" + default.replace("'", "''") + "'"
                conn.exec_driver_sql(ddl)


def make_sessionmaker(url: str) -> sessionmaker:
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _sqlite_pragmas)
    ensure_schema(engine)
    if url.startswith("sqlite:///"):
        # Buchungen, Passwort-Hash und Sitzungsgeheimnis gehen andere Benutzer des Rechners nichts an
        datei = Path(url[len("sqlite:///"):])
        for p in (datei, datei.with_name(datei.name + "-wal"), datei.with_name(datei.name + "-shm")):
            if p.exists():
                try:
                    p.chmod(0o600)
                except OSError:
                    pass
    return sessionmaker(engine, expire_on_commit=False)


def oberkategorien(session) -> dict[str, str]:
    """Unterkategorie → Oberkategorie. Auswertungen zählen Unterkategorien bei ihrer Oberkategorie mit."""
    return {k.name: k.ober for k in session.scalars(select(KategorieRow)) if k.ober}


def kv_get(session, key: str) -> str | None:
    row = session.get(KeyValue, key)
    return row.value if row else None


def kv_set(session, key: str, value: str) -> None:
    row = session.get(KeyValue, key)
    if row:
        row.value = value
    else:
        session.add(KeyValue(key=key, value=value))
