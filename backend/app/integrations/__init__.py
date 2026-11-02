"""Collegamenti con i servizi esterni (banche, SDI, pagamenti).

Ogni servizio ha un'interfaccia comune e un'implementazione "demo" che simula i dati.
Per collegare un provider reale si crea una nuova classe che rispetta la stessa interfaccia
e la si registra nella funzione get_*_provider() del file corrispondente.
"""
