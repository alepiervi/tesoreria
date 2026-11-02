import { useCallback, useEffect, useState } from "react";
import CompanyPicker from "../components/CompanyPicker";
import { Card, Empty, ErrorBox, Loading, PageHeader } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDateTime } from "../lib/format";

const ACTIONS = {
  login: "Accesso", login_fallito: "Accesso fallito", logout_ovunque: "Uscita da tutti i dispositivi",
  password_cambiata: "Password cambiata", "2fa_attivata": "Verifica in due passaggi attivata", "2fa_disattivata": "Verifica in due passaggi disattivata",
  azienda_creata: "Azienda creata", azienda_modificata: "Dati azienda modificati",
  invito_creato: "Invito creato", invito_annullato: "Invito annullato", invito_accettato: "Invito accettato",
  ruolo_impostato: "Ruolo modificato", accesso_revocato: "Accesso revocato", utente_disattivato: "Utente disattivato", utente_riattivato: "Utente riattivato",
  conto_collegato: "Conto collegato", conto_manuale_creato: "Conto manuale aggiunto",
  estratto_conto_importato: "Estratto conto importato", conto_reso_automatico: "Conto reso automatico", conto_sincronizzato: "Movimenti aggiornati", consenso_rinnovato: "Consenso bancario rinnovato", conto_scollegato: "Conto scollegato",
  categoria_modificata: "Categoria modificata", movimento_riconciliato: "Movimento riconciliato", movimento_senza_fattura: "Movimento senza fattura",
  riconciliazione_annullata: "Riconciliazione annullata", riconciliazione_automatica: "Riconciliazione automatica",
  nota_aggiunta: "Nota aggiunta", richiesta_chiarimento: "Chiarimento richiesto",
  fatture_importate: "Fatture importate", sdi_sincronizzato: "Fatture scaricate da SDI", fattura_inserita: "Fattura inserita", fattura_eliminata: "Fattura eliminata",
  scadenza_creata: "Scadenza creata", scadenza_modificata: "Scadenza modificata", scadenza_eliminata: "Scadenza eliminata", scadenza_chiusa: "Scadenza chiusa",
  pagamento_richiesto: "Pagamento preparato", pagamento_autorizzato: "Pagamento autorizzato",
  ricorrenza_creata: "Voce ricorrente creata", ricorrenza_eliminata: "Voce ricorrente eliminata",
  documento_caricato: "Documento caricato", documento_scaricato: "Documento scaricato", documento_eliminato: "Documento eliminato",
  export: "Export dati", report_mensile: "Report mensile",
  intercompany_confermato: "Trasferimento interno confermato", intercompany_automatico: "Trasferimenti interni automatici",
  intercompany_annullato: "Trasferimento interno annullato", regola_categoria: "Regola di categoria",
  sollecito_inviato: "Sollecito inviato", impostazioni_iva: "Impostazioni IVA", budget_salvato: "Budget salvato",
  finanziamento_creato: "Finanziamento aggiunto", finanziamento_modificato: "Finanziamento modificato",
  finanziamento_eliminato: "Finanziamento eliminato", scontrino_caricato: "Scontrino caricato", scontrino_abbinato: "Scontrino abbinato",
  registrazione_manuale: "Registrazione in prima nota", registrazione_modificata: "Registrazione modificata", registrazione_eliminata: "Registrazione eliminata",
  conto_creato: "Conto aggiunto al piano dei conti", impostazioni_contabili: "Collegamenti contabili modificati",
  contabilizzazione_fattura: "Conto della fattura modificato", cespite_creato: "Cespite aggiunto", cespite_da_fattura: "Cespite da fattura",
  cespite_eliminato: "Cespite eliminato", ammortamenti_registrati: "Ammortamenti registrati", rateo_risconto: "Rateo o risconto registrato",
  liquidazioni_iva_registrate: "Liquidazioni IVA registrate", esercizio_chiuso: "Esercizio chiuso", esercizio_riaperto: "Esercizio riaperto",
  export_contabile: "Export contabile",
  trasferimento_gruppo_preparato: "Trasferimento tra aziende preparato", piano_salvato: "Piano a 3 anni salvato",
  centrale_rischi_aggiornata: "Centrale Rischi aggiornata", paghe_registrate: "Paghe registrate", paghe_eliminate: "Paghe eliminate",
  mese_chiuso: "Mese chiuso", mese_riaperto: "Mese riaperto", fatture_classificate: "Fatture classificate",
  commessa_creata: "Commessa creata", rimanenze_registrate: "Rimanenze registrate",
  avanzamenti_importati: "Avanzamenti partner importati", backoffice_importato: "File backoffice importato",
  listino_provvigioni: "Listino provvigioni modificato", percettore_provvigioni: "Struttura o dipendente aggiunto",
  gara_provvigioni: "Gara creata", attivazione_assegnata: "Attivazione assegnata a mano",
  provvigioni_approvate: "Rendiconti provvigioni approvati", provvigioni_riaperte: "Rendiconto provvigioni riaperto",
};

export default function Audit() {
  const { byId } = useAuth();
  const [companyId, setCompanyId] = useState("");
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await api.get("/audit", { params: { company_id: companyId || undefined, limit: 300 } });
      setItems(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [companyId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <PageHeader title="Registro attività" subtitle="Chi ha fatto cosa e quando: accessi, pagamenti, export, modifiche"
        actions={<CompanyPicker value={companyId} onChange={setCompanyId} allowAll permission="view_audit" />} />
      <ErrorBox>{error}</ErrorBox>
      {!items ? <Loading /> : (
        <Card padded={false}>
          {items.length === 0 ? <Empty title="Nessuna attività registrata" /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="table-head text-left">
                    <th className="px-5 py-3">Quando</th>
                    <th className="py-3 pr-3">Chi</th>
                    <th className="py-3 pr-3">Cosa</th>
                    <th className="py-3 pr-3">Azienda</th>
                    <th className="py-3 pr-5">Dettaglio</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((a) => (
                    <tr key={a.id} className="border-b border-soft">
                      <td className="whitespace-nowrap px-5 py-2.5 text-muted">{fmtDateTime(a.at)}</td>
                      <td className="py-2.5 pr-3">{a.user_name || a.user_email || "—"}</td>
                      <td className="py-2.5 pr-3 font-semibold">{ACTIONS[a.action] || a.action}</td>
                      <td className="py-2.5 pr-3 text-muted">{byId[a.company_id]?.name || ""}</td>
                      <td className="py-2.5 pr-5 text-muted">{a.target || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
