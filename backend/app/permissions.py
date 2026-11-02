"""Ruoli e permessi.

Ogni utente ha un ruolo diverso per ciascuna azienda (tabella memberships).
Per aggiungere un ruolo o un permesso basta modificare questo file.
"""

ROLES = {
    "titolare": "Titolare",
    "amministrazione": "Amministrazione",
    "commercialista": "Commercialista",
    "lettura": "Sola lettura",
}

ALL_PERMISSIONS = {
    "view",               # vedere conti, movimenti, fatture, scadenze, crediti, budget, IVA
    "note",               # scrivere note e chiedere chiarimenti
    "export",             # esportare i dati e scaricare i report
    "upload_documents",   # caricare documenti (F24, bilanci, scontrini...)
    "reconcile",          # confermare o annullare abbinamenti movimento-fattura e intercompany
    "categorize",         # cambiare la categoria dei movimenti e creare regole
    "manage_invoices",    # importare e modificare fatture
    "manage_deadlines",   # creare e modificare scadenze, spese ricorrenti, finanziamenti
    "send_reminders",     # inviare solleciti di pagamento ai clienti
    "manage_budget",      # impostare il budget
    "request_payment",    # preparare un pagamento da far autorizzare
    "authorize_payment",  # autorizzare e inviare un pagamento
    "manage_banks",       # collegare, sincronizzare e scollegare conti, importare estratti conto
    "use_assistant",      # fare domande all'assistente
    "view_accounting",    # vedere prima nota, registri, mastrini e bilancio
    "manage_accounting",  # registrazioni manuali, piano dei conti, cespiti, ratei e risconti, liquidazioni
    "close_fiscal_year",  # chiudere e riaprire l'esercizio (e chiudere i mesi)
    "manage_payroll",     # inserire le paghe del mese dal riepilogo del consulente del lavoro
    "view_commissions",   # vedere attivazioni dei partner, provvigioni e bonus
    "manage_commissions", # importare avanzamenti e backoffice, listino, gare, approvare i rendiconti
    "manage_members",     # invitare utenti, cambiare ruoli, revocare accessi
    "view_audit",         # vedere il registro attività
}

ROLE_PERMISSIONS = {
    "titolare": set(ALL_PERMISSIONS),
    "amministrazione": {
        "view", "note", "export", "upload_documents", "reconcile", "categorize",
        "manage_invoices", "manage_deadlines", "send_reminders", "manage_budget",
        "request_payment", "manage_banks", "use_assistant", "view_accounting", "manage_accounting", "manage_payroll",
        "view_commissions", "manage_commissions",
    },
    "commercialista": {"view", "note", "export", "upload_documents", "use_assistant", "view_accounting",
                       "manage_accounting", "close_fiscal_year", "manage_payroll", "view_commissions"},
    "lettura": {"view", "view_accounting"},
}


def permissions_for(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(role: str, permission: str) -> bool:
    return permission in permissions_for(role)
