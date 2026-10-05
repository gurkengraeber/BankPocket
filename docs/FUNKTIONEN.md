# Funktionen im Detail

Was BankPocket wie rechnet und wo du es findest – zum Nachschlagen. Einrichtung und Betrieb stehen in der
[README](../README.md).

- **Konten ausblenden**: Konto öffnen → „Konto bearbeiten“ → „Konto ausblenden“. Das Konto verschwindet aus der
  Übersicht und zählt nicht mehr zur Summe; Buchungen und Abrufe bleiben. Zurück über „ausgeblendete Konten
  anzeigen“ ganz unten in der Übersicht. Löschen dagegen nimmt alle Buchungen des Kontos mit – und damit die
  Verträge, die daran hingen.
- **Was kostet ein Vertrag im Jahr?** In der Vertragsliste steht unter dem Betrag der aufs Jahr gerechnete Wert.
  Die Vertragsseite zeigt beides: „aufs Jahr gerechnet“ (aktueller Betrag) und „letzte 12 Monate“ (tatsächlich
  gebucht); hinter „Zahlungen“ steht die Summe aller zugeordneten Zahlungen.
- **Kursverlauf im Depot**: ING und Consorsbank nennen nur den heutigen Kurs. Ist Trade Republic verbunden, holt
  dessen Abruf den Jahresverlauf für die Wertpapiere der anderen Depots mit – soweit Trade Republic sie kennt.
- **Wenn die Bank ablehnt**: Bei Banken über FinTS steht hinter der Fehlermeldung die „Meldung der Bank“ mit deren
  Fehlernummer und Text.
- **Zum Startbildschirm**: Auf dem Handy erscheint in der Übersicht unten ein kleiner Hinweis (einmal wegtippen,
  dann bleibt er weg), der Knopf steht weiter in den Einstellungen. Ohne HTTPS legt der Browser nur eine
  Verknüpfung an; als echte App (eigenes Fenster, Push) lässt sich BankPocket erst über HTTPS installieren.
- **Aktueller Monat** (Gehaltskarte in der Übersicht antippen): der Gehaltsmonat vom letzten bis zum nächsten
  Gehalt in vier Zeilen – Einnahmen, Verträge, Sparen, sonstige Ausgaben – und was frei verfügbar bleibt. Bei
  Verträgen und Sparplänen zählt auch, was bis zum Gehalt noch abgeht; jede Zeile führt zu den Buchungen. Das
  durchgestrichene Auge nimmt eine Buchung aus der Rechnung („nicht berücksichtigt“, z. B. Auslagen). Darunter
  „Dein Verlauf“: was in den Gehaltsmonaten davor übrig blieb.
- **„Übrig am …“**: Frei verfügbar minus dein übliches Tempo bis zum nächsten Gehalt. Das Tempo sind die
  Ausgaben der letzten 90 Tage ohne Verträge und Sparen, abzüglich dessen, was nebenbei hereinkam (Erstattungen,
  Rückzahlungen von Freunden). Ein Minus heißt: Im üblichen Tempo reicht das Gehalt nicht bis zum nächsten.
- **Vertragsdaten und Kündigen**: Auf der Seite eines Vertrags trägst du Art, Laufzeit, Kündigungsfrist,
  Verlängerung, Vertragsnummer und eine Notiz ein. BankPocket rechnet daraus den letzten Kündigungstermin (ist er
  verpasst und der Vertrag verlängert sich, den der nächsten Runde). Mit „Will ich kündigen“ kommt 30, 7 und 1 Tag
  vorher ein Hinweis; ohne Laufzeit (jederzeit kündbar) sofort.
- **Versicherungen** (Schild-Symbol auf der Vertragsseite): alle bestätigten Verträge der Kategorie „Versicherung“
  in einer Liste, jede mit ihren Kosten **pro Monat** – egal ob monatlich oder jährlich abgebucht wird. Oben die
  Summe, ein Balken mit dem Kostenanteil je Vertrag und der nächste Kündigungstermin. Je Vertrag: die Art (aus den
  30 verbreitetsten, auch mehrere), **verwaltet über** (direkt, Makler, App wie Clark oder Getsafe, Vergleichsportal,
  Arbeitgeber, Bank, Verband – mit Namen), wer versichert ist, Selbstbeteiligung und ein Knopf „Schaden melden“
  (Telefon oder Adresse). Filtern nach Verwaltungsweg; darunter „Wo liegen deine Verträge?“ und die Merkliste
  üblicher Versicherungen, die nicht erfasst sind.
- **Geteilte Verträge**: In den Vertragsdaten unter „Wer zahlt?“ deinen Anteil wählen (WG-Miete, Familien-Abo).
  Dann zählt überall nur dein Teil: Vertragsübersicht, Versicherungen, Analysen, Budgets, Sparquote und „frei
  verfügbar“; an der Buchung steht „dein Anteil“. **Wichtig:** Was die anderen dir dafür überweisen, bei der
  Buchung auf „Nicht berücksichtigen“ stellen – sonst zählt es zusätzlich als Einnahme. (Ohne eingetragenen Anteil
  geht es auch andersherum: den Eingang als „Rückzahlung“ in derselben Kategorie markieren.) Wer den Ausgleich über
  Splitwise führt, trägt dort nichts doppelt ein.
- **Eigene Kategorien** gelten für Einnahmen und Ausgaben – „Anna“ für Geld von Anna lässt sich auch einer Zahlung
  an Anna geben.
- **Was kostet …?** (Analysen, oben): Lebensbereiche wie „Wohnung“ oder „Auto“ bündeln Kategorien und einzelne
  Verträge – Miete, Strom, Internet, Rundfunkbeitrag, Hausrat. Die Seite zeigt den Schnitt pro Monat über die letzten 6 Monate – per Knopf auf 3 oder 12 umstellbar – (jährliche
  und vierteljährliche Zahlungen umgelegt, bei geteilten Verträgen dein Anteil), die festen Verträge darin, zwölf
  Monatsbalken bis zu den Buchungen und woraus sich die Summe zusammensetzt. Einnahmen in einer gewählten Kategorie
  (Untermiete) mindern die Kosten. Vorschläge zum Antippen; eigene Bereiche frei zusammenstellbar.
- **Laden**: Das Gerüst einer Seite (Titel, Reiter, Karten) steht sofort; wo Zahlen noch fehlen, liegen graue
  Platzhalter mit einem durchlaufenden Schimmer. Ist am Gerät „Bewegung reduzieren“ eingeschaltet, stehen die
  Platzhalter still.
- **Fenster schließen**: Die von unten kommenden Fenster lassen sich am Griff nach unten wegwischen (im Inhalt
  auch, sobald er ganz oben steht) – oder Griff bzw. Hintergrund antippen.
- **Kategorien verwalten** (*Einstellungen → Kategorien & Regeln*): Symbol für jede Kategorie per Antippen ändern
  (auch für eingebaute), eigene umbenennen oder löschen, Regeln pflegen und **Unterkategorien** anlegen (eine Ebene,
  z. B. „Bäcker“ unter „Lebensmittel“). In Analysen, Budgets und bei „Frag deine Zahlen“ zählt eine Unterkategorie
  bei ihrer Oberkategorie mit und steht darunter einzeln; in der Auswahl steht sie eingerückt dahinter.
- **Rückzahlung** (Schalter an jedem Geldeingang): Geld kam zurück – eine Erstattung, oder jemand zahlt seinen
  Teil. Der Eingang zählt dann nicht als Einnahme, sondern mindert die Ausgaben der Kategorie, die du dazu wählst
  (in Analysen, Budgets, Bereichen und bei „frei verfügbar“).
- **Nicht berücksichtigen** (Schalter an jeder Buchung): Die Buchung zählt nirgends mit – weder bei „frei
  verfügbar“ noch in Analysen und Budgets (z. B. Auslagen, die du zurückbekommst).
- **Gekündigt**: Auf der Vertragsseite „Ist gekündigt“ antippen – der Vertrag endet zum berechneten Termin, es wird
  nicht mehr erinnert, und danach plant BankPocket keine Abbuchung mehr ein. „Will ich kündigen“ erinnert bei
  Verträgen ohne feste Laufzeit eine Woche vor der nächsten Abbuchung.
- **Eingaben per Knopf**: Vertragsdaten (Art, Anteil, Frist, Laufzeit, Verlängerung) und der Turnus neuer Verträge
  werden angetippt statt getippt; jedes Datumsfeld hat ein Kalendersymbol.
- **Vertragserkennung**: erkennt auch Quartalszahlungen mit streuendem Abstand (von Hand überwiesen) und schon nach
  zwei Zahlungen, wenn es ein Dauerauftrag, eine Lastschrift oder ein bekannter Anbieter mit gleichem Betrag ist;
  Lastschriften mit einem Ausreißer beim Betrag (Einrichtung, Nachzahlung); Jahresbeiträge neben kleinen
  Nachträgen; Vier-Wochen-Rhythmen (Prepaid-Aufladung) samt ausgesetzter Zahlung. Zwei Abos beim selben Anbieter
  bleiben zwei Verträge. Ändert die Erkennung den Zuschnitt einer Gruppe, behält ein bestätigter Vertrag seine
  Zahlungen und bleibt aktiv.
- **Verträge** sind immer nach Zeitraum gruppiert (monatlich, vierteljährlich, jährlich …); sortiert wird innerhalb
  der Gruppe nach Betrag oder Fälligkeit.
- **Sparen** (eigener Reiter): vier Kacheln mit der jeweils wichtigsten Zahl, antippen wechselt den Bereich –
  *Sparquote* (was vom Einkommen übrig bleibt, Schnitt über 3, 6 oder 11 Monate), *Sparpläne* (mit „angelegt je
  Monat“), *Erspartes* (Depots, Sparkonten, Krypto) und *Steuern*. Jede Zahl und jeder Balken führt zu den Buchungen.
- **Jahresansicht**: In den Analysen zwischen „Monat“ und „Jahr“ umschalten – zwölf Monatsbalken, Vergleich zum
  Vorjahr, Kategorien fürs ganze Jahr.
- **Steuern** (im Reiter Sparen): Spenden, Mitgliedsbeiträge, Versicherungen sowie Steuerzahlungen und
  -erstattungen (Finanzamt u. a., am Empfänger erkannt) je Empfänger als Jahressumme – einzelne Buchungen lassen
  sich mit dem Kreuz herausnehmen oder an der Buchung unter „Steuerliste“ ausdrücklich dazunehmen –, fürs
  laufende und das letzte Jahr, antippbar bis zur Buchung (zum Nachschlagen, keine Steuerberatung).
- **Verlauf je Kategorie**: In den Analysen unter den Kategorien – Kategorie wählen, zwölf Monate als Balken mit
  Durchschnitt.
- **Frag deine Zahlen** (Analysen, braucht den Mistral-Schlüssel): Fragen wie „Wie viel für Restaurants im
  Sommer?“. An die KI gehen nur die Frage, das Datum und die Namen deiner Kategorien; sie übersetzt das in einen
  Auftrag (Summe, Durchschnitt, Verlauf, Rangliste, Vergleich), gerechnet und geantwortet wird auf deinem Server.
  Beträge, Buchungen und Empfänger werden nie gesendet – nenne in der Frage selbst nur, was du preisgeben willst.
- **Analysen**: Die sechs Monatsbalken bleiben beim Wechseln stehen. Ein Stück der Torte antippen zeigt Kategorie
  und Summe in der Mitte, „Buchungen“ darunter öffnet die Liste.
- **Logos**: Buchungen bekannter Anbieter und Läden zeigen deren Logo, alle anderen das Symbol der Kategorie.
- **Verträge**: Die Erkennung schlägt nur vor. Unter *Verträge → Stimmt das?* bestätigst du oder lehnst ab; ein
  abgelehnter Vertrag wird nicht erneut vorgeschlagen. Aus jeder Buchung lässt sich ein eigener Vertrag anlegen,
  der alle Zahlungen derselben Art einsammelt.
- **Überfällig oder doch gezahlt?** Bei einem bestätigten Vertrag zählt jede Zahlung an denselben Empfänger rund
  um den erwarteten Termin – auch mit anderem Betrag (Erhöhung, Gutschrift, Nachzahlung). Weicht der Betrag um
  mehr als 35 % ab, bleibt der erwartete Betrag unverändert. Läuft ein Abo über eine andere Karte oder unter
  anderem Namen weiter, die Buchung einmal von Hand zuordnen – künftige Zahlungen dieser Art kommen dann von selbst.
- **Einnahmen als Verträge**: Gehalt wird auch erkannt, wenn der Betrag schwankt und vom selben Absender
  Spesen kommen – es zählt die größte Zahlung je Monat, erwartet wird die Mitte der letzten drei. Zinsen und
  Dividenden dürfen in der Höhe frei schwanken (erwartet: Mitte der letzten sechs); Verkäufe unter demselben
  Namen zählen nicht mit. Unregelmäßige Eingänge legst du über „Neuen Vertrag aus dieser Buchung anlegen“ an.
- **Depot**: Plus/Minus seit Kauf rechnet mit dem durchschnittlichen Kaufkurs, den Trade Republic je Position
  liefert. Der Wertverlauf einer Position rechnet die Stückzahl aus deinen Käufen zurück (Näherung), der
  Depotwert vor dem ersten Abruf wird zum Kaufpreis angesetzt.
- **Kreditkarte**: Der Ausgleich der Karte vom Girokonto gilt auf beiden Seiten als Umbuchung, nicht als
  Einnahme oder Ausgabe.
- **Unklare Buchungen**: *Analysen → … Buchungen zu klären* (oder Einstellungen) – je Händler eine Kategorie
  wählen, BankPocket merkt sie sich. Überweisungen an Privatpersonen gehen bewusst nicht an die KI; im
  Buchungsdetail fragt „Kategorie erkennen“ sie auf Wunsch für genau diese eine Buchung.
- **Umbuchungen**: Abgang und Zugang zwischen eigenen Konten (gleicher Betrag, bis fünf Tage Abstand) verbindet
  BankPocket als Gegenbuchungen – sichere Paare von selbst, unsichere fragt es unter „Unklare Buchungen“ ab. Im
  Buchungsdetail lässt sich die Gegenbuchung von Hand wählen oder lösen. Erkannte Händler und Verträge gelten nie
  automatisch als Umbuchung.
- **Verträge im Überblick**: Ein Klick auf die Monatssumme öffnet die Analyse: durchschnittliche Einnahmen,
  Verträge und Sparen pro Monat (mit Anteil am Einkommen), was frei verfügbar bleibt, und die Aufteilung nach
  Kategorie als Tortendiagramm. Sparpläne stehen in einem eigenen Abschnitt; steigt oder fällt ein Beitrag gegenüber einem
  zuvor stabilen Betrag, steht das am Vertrag.
- **Logos**: Bekannte Anbieter und Banken zeigen ihr Logo. Der Server holt dafür einmal das Seitensymbol der
  Anbieter-Adresse (Favicon-Dienst von Google, ersatzweise DuckDuckGo) und speichert es in `data/logos/` – nach
  außen geht nur die Adresse des Anbieters, der Browser lädt nur vom eigenen Server. Liste: `bankpocket/logos.py`.
- **Konten ordnen**: *Einstellungen → Konten sortieren*, dort am Griff ziehen (Reihenfolge je Gruppe). Über den Stift auf der Kontoseite
  lassen sich Name und Gruppe ändern und Konten ohne Bankverbindung löschen.
- **Budgets ausblenden**: *Einstellungen → Budgets in der Übersicht zeigen* (gilt je Gerät).
