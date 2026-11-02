"""Piano dei conti di partenza e schema di bilancio CEE (art. 2424 e 2425 c.c., forma semplificata).

Codici a tre livelli: mastro (10) · conto (10.02) · sottoconto (10.02.01). Si registra solo sui sottoconti.
Ogni sottoconto è collegato a una voce dello schema CEE; "cee_neg" è la voce da usare quando il saldo
ha segno opposto al normale (es. una banca in rosso va tra i debiti verso banche).
Il commercialista può aggiungere sottoconti e cambiare i collegamenti.
"""

# kind: attivo | passivo | costo | ricavo | chiusura
# party: "cliente" | "fornitore" | "gruppo" -> il sottoconto ha un partitario per controparte
ACCOUNTS = [
    # ---------------- ATTIVO
    ("10", "Immobilizzazioni", "attivo", None, None, None, None),
    ("10.01", "Immobilizzazioni immateriali", "attivo", None, None, None, None),
    ("10.01.01", "Software e licenze", "attivo", "SP.A.B.I", None, "imm_software", None),
    ("10.01.02", "Avviamento", "attivo", "SP.A.B.I", None, None, None),
    ("10.01.91", "F.do amm. software e licenze", "attivo", "SP.A.B.I", None, "fondo_software", None),
    ("10.01.92", "F.do amm. avviamento", "attivo", "SP.A.B.I", None, None, None),
    ("10.02", "Immobilizzazioni materiali", "attivo", None, None, None, None),
    ("10.02.01", "Fabbricati", "attivo", "SP.A.B.II", None, "imm_fabbricati", None),
    ("10.02.02", "Impianti e macchinari", "attivo", "SP.A.B.II", None, "imm_impianti", None),
    ("10.02.03", "Attrezzature", "attivo", "SP.A.B.II", None, "imm_attrezzature", None),
    ("10.02.04", "Mobili e arredi", "attivo", "SP.A.B.II", None, "imm_mobili", None),
    ("10.02.05", "Macchine d'ufficio elettroniche", "attivo", "SP.A.B.II", None, "imm_elettroniche", None),
    ("10.02.06", "Automezzi", "attivo", "SP.A.B.II", None, "imm_automezzi", None),
    ("10.02.91", "F.do amm. fabbricati", "attivo", "SP.A.B.II", None, "fondo_fabbricati", None),
    ("10.02.92", "F.do amm. impianti e macchinari", "attivo", "SP.A.B.II", None, "fondo_impianti", None),
    ("10.02.93", "F.do amm. attrezzature", "attivo", "SP.A.B.II", None, "fondo_attrezzature", None),
    ("10.02.94", "F.do amm. mobili e arredi", "attivo", "SP.A.B.II", None, "fondo_mobili", None),
    ("10.02.95", "F.do amm. macchine d'ufficio", "attivo", "SP.A.B.II", None, "fondo_elettroniche", None),
    ("10.02.96", "F.do amm. automezzi", "attivo", "SP.A.B.II", None, "fondo_automezzi", None),
    ("10.03", "Immobilizzazioni finanziarie", "attivo", None, None, None, None),
    ("10.03.01", "Partecipazioni", "attivo", "SP.A.B.III", None, None, None),
    ("10.03.02", "Depositi cauzionali", "attivo", "SP.A.B.III", None, None, None),

    ("20", "Attivo circolante", "attivo", None, None, None, None),
    ("20.01", "Rimanenze", "attivo", None, None, None, None),
    ("20.01.01", "Rimanenze di merci", "attivo", "SP.A.C.I", None, "rimanenze", None),
    ("20.02", "Crediti commerciali", "attivo", None, None, None, None),
    ("20.02.01", "Clienti", "attivo", "SP.A.C.II.1", "SP.P.D.6", "clienti", "cliente"),
    ("20.02.02", "Crediti verso società del gruppo", "attivo", "SP.A.C.II.4", "SP.P.D.11", "gruppo_crediti", "gruppo"),
    ("20.02.03", "Fatture da emettere", "attivo", "SP.A.C.II.1", None, None, None),
    ("20.03", "Crediti tributari", "attivo", None, None, None, None),
    ("20.03.01", "IVA su acquisti", "attivo", "SP.A.C.II.5bis", "SP.P.D.12", "iva_credito", None),
    ("20.03.02", "Erario c/IVA", "attivo", "SP.A.C.II.5bis", "SP.P.D.12", "erario_iva", None),
    ("20.03.03", "Erario c/acconti d'imposta", "attivo", "SP.A.C.II.5bis", None, None, None),
    ("20.03.04", "Erario c/ritenute subite", "attivo", "SP.A.C.II.5bis", None, "ritenute_subite", None),
    ("20.04", "Altri crediti", "attivo", None, None, None, None),
    ("20.04.01", "Crediti diversi", "attivo", "SP.A.C.II.5quater", None, None, None),
    ("20.04.02", "Anticipi a fornitori", "attivo", "SP.A.C.II.5quater", None, "anticipi_fornitori", None),
    ("20.04.99", "Movimenti da attribuire (verifica)", "attivo", "SP.A.C.II.5quater", "SP.P.D.14", "transitorio", None),
    ("20.05", "Disponibilità liquide", "attivo", None, None, None, None),
    ("20.05.01", "Cassa contanti", "attivo", "SP.A.C.IV", None, "cassa", None),
    # i sottoconti delle banche (20.05.1x) si creano da soli per ogni conto bancario
    ("25", "Ratei e risconti attivi", "attivo", None, None, None, None),
    ("25.01", "Ratei e risconti attivi", "attivo", None, None, None, None),
    ("25.01.01", "Ratei attivi", "attivo", "SP.A.D", None, "ratei_attivi", None),
    ("25.01.02", "Risconti attivi", "attivo", "SP.A.D", None, "risconti_attivi", None),

    # ---------------- PASSIVO
    ("30", "Patrimonio netto", "passivo", None, None, None, None),
    ("30.01", "Patrimonio netto", "passivo", None, None, None, None),
    ("30.01.01", "Capitale sociale", "passivo", "SP.P.A.I", None, "capitale", None),
    ("30.01.02", "Riserva legale", "passivo", "SP.P.A.IV", None, None, None),
    ("30.01.03", "Altre riserve", "passivo", "SP.P.A.VI", None, None, None),
    ("30.01.04", "Utili (perdite) portati a nuovo", "passivo", "SP.P.A.VIII", None, "utili_a_nuovo", None),
    ("30.01.05", "Utile (perdita) dell'esercizio", "passivo", "SP.P.A.IX", None, "utile_esercizio", None),
    ("35", "Fondi e TFR", "passivo", None, None, None, None),
    ("35.01", "Fondi e TFR", "passivo", None, None, None, None),
    ("35.01.01", "Fondi per rischi e oneri", "passivo", "SP.P.B", None, None, None),
    ("35.01.02", "Fondo TFR", "passivo", "SP.P.C", None, "fondo_tfr", None),
    ("40", "Debiti", "passivo", None, None, None, None),
    ("40.01", "Debiti verso banche", "passivo", None, None, None, None),
    ("40.01.01", "Mutui e finanziamenti bancari", "passivo", "SP.P.D.4", None, "debiti_finanziamenti", None),
    ("40.01.02", "Banche c/anticipi e fidi", "passivo", "SP.P.D.4", None, None, None),
    ("40.02", "Debiti commerciali", "passivo", None, None, None, None),
    ("40.02.01", "Fornitori", "passivo", "SP.P.D.7", "SP.A.C.II.5quater", "fornitori", "fornitore"),
    ("40.02.02", "Fatture da ricevere", "passivo", "SP.P.D.7", None, "fatture_da_ricevere", None),
    ("40.03", "Debiti verso società del gruppo", "passivo", None, None, None, None),
    ("40.03.01", "Debiti verso società del gruppo", "passivo", "SP.P.D.11", "SP.A.C.II.4", "gruppo_debiti", "gruppo"),
    ("40.04", "Debiti tributari", "passivo", None, None, None, None),
    ("40.04.01", "IVA su vendite", "passivo", "SP.P.D.12", "SP.A.C.II.5bis", "iva_debito", None),
    ("40.04.02", "Erario c/ritenute da versare", "passivo", "SP.P.D.12", None, "ritenute_da_versare", None),
    ("40.04.03", "Erario c/imposte e tributi", "passivo", "SP.P.D.12", "SP.A.C.II.5bis", "erario_tributi", None),
    ("40.04.04", "Debiti per IRES e IRAP", "passivo", "SP.P.D.12", None, "debiti_imposte", None),
    ("40.05", "Debiti previdenziali", "passivo", None, None, None, None),
    ("40.05.01", "INPS e INAIL c/contributi", "passivo", "SP.P.D.13", "SP.A.C.II.5quater", "debiti_inps", None),
    ("40.06", "Altri debiti", "passivo", None, None, None, None),
    ("40.06.01", "Dipendenti c/retribuzioni", "passivo", "SP.P.D.14", "SP.A.C.II.5quater", "debiti_dipendenti", None),
    ("40.06.02", "Debiti diversi", "passivo", "SP.P.D.14", None, None, None),
    ("45", "Ratei e risconti passivi", "passivo", None, None, None, None),
    ("45.01", "Ratei e risconti passivi", "passivo", None, None, None, None),
    ("45.01.01", "Ratei passivi", "passivo", "SP.P.E", None, "ratei_passivi", None),
    ("45.01.02", "Risconti passivi", "passivo", "SP.P.E", None, "risconti_passivi", None),

    # ---------------- COSTI
    ("60", "Costi della produzione", "costo", None, None, None, None),
    ("60.01", "Acquisti", "costo", None, None, None, None),
    ("60.01.01", "Acquisti di merci", "costo", "CE.B.6", None, "acquisti_merci", None),
    ("60.01.02", "Materiali di consumo", "costo", "CE.B.6", None, "costi_consumo", None),
    ("60.01.03", "Variazione delle rimanenze di merci", "costo", "CE.B.11", None, "variazione_rimanenze", None),
    ("60.02", "Servizi", "costo", None, None, None, None),
    ("60.02.01", "Servizi e acquisti diversi", "costo", "CE.B.7", None, "costi_generici", None),
    ("60.02.02", "Utenze (energia, gas, acqua, telefono)", "costo", "CE.B.7", None, "costi_utenze", None),
    ("60.02.03", "Carburanti e trasporti", "costo", "CE.B.7", None, "costi_trasporti", None),
    ("60.02.04", "Consulenze e prestazioni professionali", "costo", "CE.B.7", None, "costi_consulenze", None),
    ("60.02.05", "Software, cloud e servizi IT", "costo", "CE.B.7", None, "costi_software", None),
    ("60.02.06", "Manutenzioni e riparazioni", "costo", "CE.B.7", None, "costi_manutenzioni", None),
    ("60.02.07", "Assicurazioni", "costo", "CE.B.7", None, "costi_assicurazioni", None),
    ("60.02.08", "Spese e commissioni bancarie", "costo", "CE.B.7", None, "costi_banca", None),
    ("60.03", "Godimento beni di terzi", "costo", None, None, None, None),
    ("60.03.01", "Affitti passivi", "costo", "CE.B.8", None, "costi_affitti", None),
    ("60.03.02", "Canoni di leasing", "costo", "CE.B.8", None, "costi_leasing", None),
    ("60.03.03", "Noleggi", "costo", "CE.B.8", None, "costi_noleggi", None),
    ("60.04", "Personale", "costo", None, None, None, None),
    ("60.04.01", "Salari e stipendi", "costo", "CE.B.9a", None, "costi_stipendi", None),
    ("60.04.02", "Oneri sociali", "costo", "CE.B.9b", None, "costi_oneri_sociali", None),
    ("60.04.03", "Trattamento di fine rapporto", "costo", "CE.B.9c", None, "costi_tfr", None),
    ("60.05", "Ammortamenti", "costo", None, None, None, None),
    ("60.05.01", "Ammortamento immobilizzazioni immateriali", "costo", "CE.B.10a", None, "amm_immateriali", None),
    ("60.05.02", "Ammortamento immobilizzazioni materiali", "costo", "CE.B.10b", None, "amm_materiali", None),
    ("60.06", "Oneri diversi di gestione", "costo", None, None, None, None),
    ("60.06.01", "Imposte e tasse deducibili", "costo", "CE.B.14", None, "costi_imposte_diverse", None),
    ("60.06.02", "Altri oneri di gestione", "costo", "CE.B.14", None, "costi_altri", None),
    ("70", "Oneri finanziari", "costo", None, None, None, None),
    ("70.01", "Interessi e oneri finanziari", "costo", None, None, None, None),
    ("70.01.01", "Interessi passivi bancari", "costo", "CE.C.17", None, "interessi_passivi", None),
    ("70.01.02", "Interessi passivi su mutui", "costo", "CE.C.17", None, "interessi_mutui", None),
    ("80", "Imposte sul reddito", "costo", None, None, None, None),
    ("80.01", "Imposte sul reddito", "costo", None, None, None, None),
    ("80.01.01", "IRES dell'esercizio", "costo", "CE.20", None, "ires", None),
    ("80.01.02", "IRAP dell'esercizio", "costo", "CE.20", None, "irap", None),

    # ---------------- RICAVI
    ("90", "Ricavi", "ricavo", None, None, None, None),
    ("90.01", "Ricavi delle vendite e prestazioni", "ricavo", None, None, None, None),
    ("90.01.01", "Ricavi delle vendite e prestazioni", "ricavo", "CE.A.1", None, "ricavi", None),
    ("90.01.02", "Ricavi verso società del gruppo", "ricavo", "CE.A.1", None, "ricavi_gruppo", None),
    ("90.02", "Altri ricavi e proventi", "ricavo", None, None, None, None),
    ("90.02.01", "Altri ricavi e proventi", "ricavo", "CE.A.5", None, "altri_ricavi", None),
    ("90.03", "Proventi finanziari", "ricavo", None, None, None, None),
    ("90.03.01", "Interessi attivi", "ricavo", "CE.C.16", None, "interessi_attivi", None),

    # ---------------- CHIUSURA (conti tecnici per chiusura e apertura dei conti)
    ("99", "Conti di chiusura", "chiusura", None, None, None, None),
    ("99.01", "Conti di chiusura", "chiusura", None, None, None, None),
    ("99.01.01", "Stato patrimoniale di apertura", "chiusura", None, None, "sp_apertura", None),
    ("99.01.02", "Stato patrimoniale di chiusura", "chiusura", None, None, "sp_chiusura", None),
    ("99.01.03", "Conto economico (epilogo)", "chiusura", None, None, "ce_epilogo", None),
]

BANK_PARENT = "20.05"

# Da categoria del movimento a conto, per i movimenti senza fattura (modificabile per azienda)
CATEGORY_ACCOUNT_KEYS = {
    "Personale": "costi_stipendi",  # con le paghe registrate dal consulente: "Dipendenti c/retribuzioni"
    "Imposte e tasse": "erario_tributi",
    "Affitti": "costi_affitti",
    "Utenze": "costi_utenze",
    "Leasing e finanziamenti": "debiti_finanziamenti",
    "Oneri bancari": "costi_banca",
    "Carburante e trasporti": "costi_trasporti",
    "Software e servizi": "costi_software",
    "Fornitori": "anticipi_fornitori",
    "Incassi clienti": "transitorio",
    "Altre entrate": "altri_ricavi",
    "Altre uscite": "costi_altri",
    "Da classificare": "transitorio",
}

# Schema di bilancio: (codice, etichetta, livello per il rientro)
SP_ATTIVO = [
    ("SP.A.B", "B) Immobilizzazioni", 0),
    ("SP.A.B.I", "I - Immobilizzazioni immateriali", 1),
    ("SP.A.B.II", "II - Immobilizzazioni materiali", 1),
    ("SP.A.B.III", "III - Immobilizzazioni finanziarie", 1),
    ("SP.A.C", "C) Attivo circolante", 0),
    ("SP.A.C.I", "I - Rimanenze", 1),
    ("SP.A.C.II", "II - Crediti", 1),
    ("SP.A.C.II.1", "1) verso clienti", 2),
    ("SP.A.C.II.4", "4) verso controllanti e società del gruppo", 2),
    ("SP.A.C.II.5bis", "5-bis) crediti tributari", 2),
    ("SP.A.C.II.5quater", "5-quater) verso altri", 2),
    ("SP.A.C.IV", "IV - Disponibilità liquide", 1),
    ("SP.A.D", "D) Ratei e risconti", 0),
]
SP_PASSIVO = [
    ("SP.P.A", "A) Patrimonio netto", 0),
    ("SP.P.A.I", "I - Capitale", 1),
    ("SP.P.A.IV", "IV - Riserva legale", 1),
    ("SP.P.A.VI", "VI - Altre riserve", 1),
    ("SP.P.A.VIII", "VIII - Utili (perdite) portati a nuovo", 1),
    ("SP.P.A.IX", "IX - Utile (perdita) dell'esercizio", 1),
    ("SP.P.B", "B) Fondi per rischi e oneri", 0),
    ("SP.P.C", "C) Trattamento di fine rapporto", 0),
    ("SP.P.D", "D) Debiti", 0),
    ("SP.P.D.4", "4) debiti verso banche", 1),
    ("SP.P.D.6", "6) acconti", 1),
    ("SP.P.D.7", "7) debiti verso fornitori", 1),
    ("SP.P.D.11", "11) verso controllanti e società del gruppo", 1),
    ("SP.P.D.12", "12) debiti tributari", 1),
    ("SP.P.D.13", "13) verso istituti di previdenza", 1),
    ("SP.P.D.14", "14) altri debiti", 1),
    ("SP.P.E", "E) Ratei e risconti", 0),
]
CE_SCHEMA = [
    ("CE.A", "A) Valore della produzione", 0, "+"),
    ("CE.A.1", "1) Ricavi delle vendite e delle prestazioni", 1, "+"),
    ("CE.A.5", "5) Altri ricavi e proventi", 1, "+"),
    ("CE.B", "B) Costi della produzione", 0, "-"),
    ("CE.B.6", "6) per materie prime, sussidiarie, di consumo e merci", 1, "-"),
    ("CE.B.7", "7) per servizi", 1, "-"),
    ("CE.B.8", "8) per godimento di beni di terzi", 1, "-"),
    ("CE.B.9", "9) per il personale", 1, "-"),
    ("CE.B.9a", "a) salari e stipendi", 2, "-"),
    ("CE.B.9b", "b) oneri sociali", 2, "-"),
    ("CE.B.9c", "c) trattamento di fine rapporto", 2, "-"),
    ("CE.B.10", "10) ammortamenti e svalutazioni", 1, "-"),
    ("CE.B.10a", "a) ammortamento delle immobilizzazioni immateriali", 2, "-"),
    ("CE.B.10b", "b) ammortamento delle immobilizzazioni materiali", 2, "-"),
    ("CE.B.11", "11) variazioni delle rimanenze di materie prime, sussidiarie, di consumo e merci", 1, "-"),
    ("CE.B.14", "14) oneri diversi di gestione", 1, "-"),
    ("CE.C", "C) Proventi e oneri finanziari", 0, "+"),
    ("CE.C.16", "16) altri proventi finanziari", 1, "+"),
    ("CE.C.17", "17) interessi e altri oneri finanziari", 1, "-"),
    ("CE.20", "20) Imposte sul reddito dell'esercizio", 0, "-"),
]


def level_of(code: str) -> int:
    return code.count(".") + 1


def template_accounts() -> list[dict]:
    out = []
    for code, name, kind, cee, cee_neg, key, party in ACCOUNTS:
        out.append({"code": code, "name": name, "kind": kind, "level": level_of(code), "postable": level_of(code) == 3,
                    "cee": cee, "cee_neg": cee_neg, "key": key, "party": party, "system": True})
    return out
