"""Bankabrufe: Hintergrund-Jobs, Speichern der Ergebnisse, Status und Hinweise."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from sqlalchemy import func, select

from . import ki
from .analysen import pruefe_budgets
from .context import AppContext
from .db import Account, Connection, TransactionRow
from .fetchers.base import (Abgebrochen, AuswahlNoetig, FetchError, FetchResult, FreigabeNoetig, Interaktion,
                            PinFalsch, ZugangGesperrt)
from .service import (GRUPPE_FUER_TYP, holdings_setzen, kurse_ergaenzen, markiere_interne_umbuchungen, melde_vertragsereignisse,
                      pruefe_kuendigungen, pruefe_ueberfaellig, saldo_setzen, speichere_transaktionen, sync_contracts,
                      wertpapiere_ohne_verlauf)

log = logging.getLogger(__name__)

# Diese Zustände brauchen dich – automatische Abrufe lassen sie in Ruhe (kein Spam in der Banking-App,
# keine weiteren Fehlversuche mit falscher PIN).
AUTOMATISCH_UEBERSPRINGEN = {"pin_falsch", "gesperrt", "freigabe_noetig", "auswahl_noetig", "laeuft"}
MANUELL_UEBERSPRINGEN = {"pin_falsch", "gesperrt", "laeuft"}

STATUS_FUER_FEHLER = {PinFalsch: "pin_falsch", ZugangGesperrt: "gesperrt", FreigabeNoetig: "freigabe_noetig",
                      AuswahlNoetig: "auswahl_noetig", Abgebrochen: "abgebrochen"}
FEHLER_BIS_HINWEIS = 3


@dataclass
class Job:
    interaktion: Interaktion
    fertig: bool = False


class SyncManager:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self._jobs: dict[int, Job] = {}
        self._lock = threading.Lock()

    # ---------- Steuerung ----------
    def live(self, conn_id: int) -> dict | None:
        job = self._jobs.get(conn_id)
        if not job:
            return None
        return {**job.interaktion.zustand(), "laeuft": not job.fertig}

    def _job_anlegen(self, conn_id: int, interaktiv: bool) -> Job | None:
        with self._lock:
            job = self._jobs.get(conn_id)
            if job and not job.fertig:
                return None
            job = Job(Interaktion(interaktiv))
            self._jobs[conn_id] = job
            return job

    def starten(self, conn_id: int, interaktiv: bool = True, erstverbindung: bool = False) -> bool:
        """Abruf im Hintergrund starten (für die Web-App). False, wenn bereits einer läuft."""
        job = self._job_anlegen(conn_id, interaktiv)
        if job is None:
            return False
        threading.Thread(target=self._lauf, args=(conn_id, job, erstverbindung), daemon=True,
                         name=f"abruf-{conn_id}").start()
        return True

    def ausfuehren(self, conn_id: int, interaktiv: bool = False, erstverbindung: bool = False) -> str | None:
        """Abruf synchron ausführen (Scheduler, Tests). Gibt den neuen Status zurück."""
        job = self._job_anlegen(conn_id, interaktiv)
        if job is None:
            return None
        self._lauf(conn_id, job, erstverbindung)
        with self.ctx.session_factory() as s:
            conn = s.get(Connection, conn_id)
            return conn.status if conn else None

    def eingabe(self, conn_id: int, daten: dict) -> bool:
        job = self._jobs.get(conn_id)
        if not job or job.fertig:
            return False
        job.interaktion.eingabe(daten)
        return True

    def abbrechen(self, conn_id: int) -> bool:
        job = self._jobs.get(conn_id)
        if not job or job.fertig:
            return False
        job.interaktion.abbrechen()
        return True

    def alle_starten(self) -> list[int]:
        """„Aktualisieren“-Knopf: alle Verbindungen abrufen, bei denen du nichts ändern musst."""
        with self.ctx.session_factory() as s:
            ids = [c.id for c in s.scalars(select(Connection)) if c.status not in MANUELL_UEBERSPRINGEN]
        return [i for i in ids if self.starten(i, interaktiv=True)]

    def automatisch_abrufen(self) -> None:
        """Geplanter Lauf: Verbindungen nacheinander abrufen; ein Fehler stoppt nicht die anderen."""
        with self.ctx.session_factory() as s:
            ids = [c.id for c in s.scalars(select(Connection)) if c.status not in AUTOMATISCH_UEBERSPRINGEN]
        for conn_id in ids:
            try:
                self.ausfuehren(conn_id, interaktiv=False)
            except Exception:  # noqa: BLE001 – darf den Scheduler nie stoppen
                log.exception("Abruf %s fehlgeschlagen", conn_id)
        with self.ctx.session_factory() as s:
            pruefe_ueberfaellig(self.ctx.notifier, s, self.ctx.today())
            pruefe_kuendigungen(self.ctx.notifier, s, self.ctx.today())
            pruefe_budgets(self.ctx.notifier, s, self.ctx.today())
            s.commit()

    # ---------- Ein Abruf ----------
    def _lauf(self, conn_id: int, job: Job, erstverbindung: bool) -> None:
        ia = job.interaktion
        try:
            with self.ctx.session_factory() as s:
                conn = s.get(Connection, conn_id)
                if conn is None:
                    ia.melden("fehler", "Verbindung nicht gefunden.")
                    return
                conn.status, conn.letzter_versuch = "laeuft", self.ctx.now()
                s.commit()
                try:
                    source = self._source(s, conn, ia)
                except FetchError as e:
                    self._fehler(conn_id, e, ia)
                    return
            try:
                ergebnis = source.abrufen()
            except FetchError as e:
                self._fehler(conn_id, e, ia)
                return
            except Exception as e:  # noqa: BLE001
                log.exception("Unerwarteter Fehler beim Abruf %s", conn_id)
                self._fehler(conn_id, FetchError(f"Unerwarteter Fehler: {e}"), ia)
                return
            self._speichern(conn_id, ergebnis, ia, erstverbindung)
        except Exception as e:  # noqa: BLE001
            log.exception("Speichern des Abrufs %s fehlgeschlagen", conn_id)
            self._fehler(conn_id, FetchError(f"Speichern fehlgeschlagen: {e}"), ia)
        finally:
            job.fertig = True

    def _source(self, s, conn: Connection, ia: Interaktion):
        vault = self.ctx.vault
        letzte = {}
        for acc in s.scalars(select(Account).where(Account.connection_id == conn.id)):
            d = s.scalar(select(func.max(TransactionRow.buchungsdatum)).where(TransactionRow.account_id == acc.id))
            if d:
                letzte[acc.iban or acc.kontonummer] = d

        conn_id, name = conn.id, conn.name

        def bei_freigabe(_text: str) -> None:
            # Hintergrund-Abruf: kurz erklären, warum die Banking-App gerade nach einer Freigabe fragt.
            with self.ctx.session_factory() as s2:
                self.ctx.notifier.hinweis(
                    s2, "freigabe", f"{name}: Freigabe angefragt",
                    "BankPocket möchte deine Umsätze abrufen. Bitte bestätige in deiner Banking-App.",
                    link=f"#/verbindung/{conn_id}", schluessel=f"freigabe|{conn_id}|{self.ctx.today()}")
                s2.commit()

        fabrik = self.ctx.quelle(conn.art)
        if fabrik is None:
            raise FetchError(f"Unbekannte Datenquelle „{conn.art}“.")
        return fabrik(
            blz=conn.blz, url=conn.server_url, login=vault.decrypt_str(conn.login_enc),
            pin=vault.decrypt_str(conn.pin_enc), product_id=self.ctx.settings.fints_product_id,
            interaktion=ia, client_data=vault.decrypt(conn.client_data_enc) if conn.client_data_enc else None,
            tan_medium=conn.tan_medium, letzte_buchung=letzte, heute=self.ctx.today(),
            bei_freigabe=None if ia.interaktiv else bei_freigabe,
            arbeitsordner=self.ctx.settings.data_dir, verbindung_id=conn.id, bank=conn.bank,
            fremde_wertpapiere=wertpapiere_ohne_verlauf(s, conn.id) if conn.art == "trade_republic" else None,
        )

    def _fehler(self, conn_id: int, e: FetchError, ia: Interaktion) -> None:
        status = STATUS_FUER_FEHLER.get(type(e), "fehler")
        with self.ctx.session_factory() as s:
            conn = s.get(Connection, conn_id)
            if conn is None:
                return
            if e.client_data:
                conn.client_data_enc = self.ctx.vault.encrypt(e.client_data)
            if status == "abgebrochen":
                status = "freigabe_noetig" if conn.letzter_erfolg else "neu"
            conn.status, conn.meldung = status, e.meldung
            conn.fehler_in_folge = conn.fehler_in_folge + 1 if status == "fehler" else 0
            if not ia.interaktiv:  # wer gerade in der App ist, sieht den Fehler dort direkt
                self._fehler_melden(s, conn, status, e.meldung)
            s.commit()
        ia.melden("fehler", e.meldung, status=status)

    def _fehler_melden(self, s, conn: Connection, status: str, meldung: str) -> None:
        heute, link = self.ctx.today(), f"#/verbindung/{conn.id}"
        freigabe_text = ("Die Anmeldung ist abgelaufen. Tippe hier und melde dich neu an – du bestätigst sie "
                         "in der Trade-Republic-App." if conn.art == "trade_republic" else
                         "Die Freigabe bei der Bank ist abgelaufen. Tippe hier und gib sie neu frei – du "
                         "bestätigst sie in der App deiner Bank." if conn.art == "enablebanking" else
                         "Die Bank verlangt eine Freigabe. Tippe hier und starte den Abruf, wenn du deine "
                         "Banking-App zur Hand hast.")
        texte = {
            "pin_falsch": (f"{conn.name}: Anmeldung fehlgeschlagen", meldung),
            "gesperrt": (f"{conn.name}: Zugang gesperrt", meldung),
            "freigabe_noetig": (f"{conn.name}: Abruf pausiert", freigabe_text),
            "auswahl_noetig": (f"{conn.name}: Einstellung nötig", meldung),
        }
        if status in texte:
            titel, text = texte[status]
            self.ctx.notifier.hinweis(s, status, titel, text, link=link, schluessel=f"{status}|{conn.id}|{heute}")
        elif status == "fehler" and conn.fehler_in_folge == FEHLER_BIS_HINWEIS:
            self.ctx.notifier.hinweis(s, "fehler", f"{conn.name}: Abruf schlägt fehl", meldung, link=link,
                                      schluessel=f"fehler|{conn.id}|{heute}")

    def _speichern(self, conn_id: int, erg: FetchResult, ia: Interaktion, erstverbindung: bool) -> None:
        heute, jetzt = self.ctx.today(), self.ctx.now()
        with self.ctx.session_factory() as s:
            conn = s.get(Connection, conn_id)
            konten_info, neue_umsaetze = [], 0
            for fa in erg.konten:
                acc = self._konto_finden(s, conn, fa)
                neu = acc is None
                if neu:
                    acc = Account(quelle=conn.bank, name=fa.name, typ=fa.typ, gruppe=GRUPPE_FUER_TYP[fa.typ],
                                  waehrung=fa.waehrung, iban=fa.iban, kontonummer=fa.kontonummer,
                                  unterkonto=fa.unterkonto, connection_id=conn.id)
                    s.add(acc)
                    s.flush()
                acc.connection_id, acc.zuletzt_aktualisiert = conn.id, jetzt
                if fa.typ == "depot" and acc.typ != "depot":  # früher mangels Kontoart falsch eingeordnet
                    acc.typ, acc.gruppe = "depot", GRUPPE_FUER_TYP["depot"]
                if fa.transaktionen:
                    neue_umsaetze += speichere_transaktionen(s, acc, fa.transaktionen)
                if fa.holdings is not None:
                    holdings_setzen(s, acc, heute, fa.holdings)
                if fa.saldo is not None:
                    saldo_setzen(s, acc, fa.saldo_datum or heute, fa.saldo)
                konten_info.append({"id": acc.id, "name": acc.name, "typ": acc.typ, "gruppe": acc.gruppe,
                                    "saldo": str(fa.saldo) if fa.saldo is not None else None, "neu": neu})

            for symbol, punkte in (erg.kurse or {}).items():
                kurse_ergaenzen(s, symbol, punkte)
            if erg.client_data:
                conn.client_data_enc = self.ctx.vault.encrypt(erg.client_data)
            conn.tan_verfahren = erg.tan_verfahren or conn.tan_verfahren
            conn.tan_verfahren_name = erg.tan_verfahren_name or conn.tan_verfahren_name
            conn.tan_medium = erg.tan_medium if erg.tan_medium is not None else conn.tan_medium
            conn.status, conn.meldung, conn.fehler_in_folge = "ok", "", 0
            conn.letzter_erfolg = jetzt
            if erg.freigabe_erfolgt:
                conn.letzte_freigabe = jetzt

            markiere_interne_umbuchungen(s)
            s.flush()
            vertraege = sync_contracts(s, heute)
            if not erstverbindung:  # beim ersten Import der Historie wäre alles „neu“
                melde_vertragsereignisse(self.ctx.notifier, s, vertraege, heute, push=not ia.interaktiv)
                pruefe_budgets(self.ctx.notifier, s, heute, push=not ia.interaktiv)
            s.commit()
        ia.melden("fertig", f"{len(konten_info)} Konten aktualisiert, {neue_umsaetze} neue Umsätze.",
                  konten=konten_info, neue_umsaetze=neue_umsaetze, status="ok")
        if neue_umsaetze:
            with self.ctx.session_factory() as s:
                ki.nachlauf(self.ctx, s)

    @staticmethod
    def _konto_finden(s, conn: Connection, fa) -> Account | None:
        if fa.iban:
            q = select(Account).where(Account.iban == fa.iban)
        else:
            q = select(Account).where(Account.kontonummer == fa.kontonummer, Account.quelle == conn.bank)
            if fa.unterkonto:
                q = q.where(Account.unterkonto == fa.unterkonto)
        treffer = list(s.scalars(q))
        # Konto dieser Verbindung bevorzugen; sonst eines ohne Verbindung (z. B. nach Neu-Einrichtung)
        for acc in treffer:
            if acc.connection_id == conn.id:
                return acc
        for acc in treffer:
            if acc.connection_id is None:
                return acc
        return None
