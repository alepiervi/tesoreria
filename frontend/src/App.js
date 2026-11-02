import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { Loading, ToastProvider } from "./components/ui";
import { AuthProvider, useAuth } from "./lib/auth";
import AcceptInvite from "./pages/AcceptInvite";
import Audit from "./pages/Audit";
import CompanyPage from "./pages/CompanyPage";
import Deadlines from "./pages/Deadlines";
import Documents from "./pages/Documents";
import Export from "./pages/Export";
import GroupDashboard from "./pages/GroupDashboard";
import Invoices from "./pages/Invoices";
import Login from "./pages/Login";
import Members from "./pages/Members";
import Questions from "./pages/Questions";
import Reconciliation from "./pages/Reconciliation";
import Settings from "./pages/Settings";
import Transactions from "./pages/Transactions";
import Assistant from "./pages/Assistant";
import Budget from "./pages/Budget";
import Intercompany from "./pages/Intercompany";
import Loans from "./pages/Loans";
import Notifications from "./pages/Notifications";
import Receipts from "./pages/Receipts";
import Receivables from "./pages/Receivables";
import Vat from "./pages/Vat";
import Assets from "./pages/accounting/Assets";
import ChartOfAccounts from "./pages/accounting/ChartOfAccounts";
import Closing from "./pages/accounting/Closing";
import Journal from "./pages/accounting/Journal";
import Statements from "./pages/accounting/Statements";
import VatRegisters from "./pages/accounting/VatRegisters";
import Classify from "./pages/accounting/Classify";
import CentralRisk from "./pages/CentralRisk";
import Health from "./pages/Health";
import MonthClose from "./pages/MonthClose";
import Payroll from "./pages/Payroll";
import Plan from "./pages/Plan";
import Projects from "./pages/Projects";
import Compare from "./pages/group/Compare";
import Consolidated from "./pages/group/Consolidated";
import GroupCash from "./pages/group/GroupCash";
import Activations from "./pages/commissions/Activations";
import Guide from "./pages/Guide";
import DevErrors from "./pages/developer/Errors";
import DevOwnerInvite from "./pages/developer/OwnerInvite";
import DevStatus from "./pages/developer/Status";
import CommissionSetup from "./pages/commissions/Setup";
import CommissionStatements from "./pages/commissions/Statements";

function Protected({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/invito/:token" element={<AcceptInvite />} />
            <Route element={<Protected><Layout /></Protected>}>
              <Route path="/" element={<GroupDashboard />} />
              <Route path="/aziende/:companyId" element={<CompanyPage />} />
              <Route path="/movimenti" element={<Transactions />} />
              <Route path="/fatture" element={<Invoices />} />
              <Route path="/riconciliazione" element={<Reconciliation />} />
              <Route path="/scadenze" element={<Deadlines />} />
              <Route path="/chiarimenti" element={<Questions />} />
              <Route path="/documenti" element={<Documents />} />
              <Route path="/export" element={<Export />} />
              <Route path="/utenti" element={<Members />} />
              <Route path="/registro" element={<Audit />} />
              <Route path="/impostazioni" element={<Settings />} />
              <Route path="/notifiche" element={<Notifications />} />
              <Route path="/assistente" element={<Assistant />} />
              <Route path="/crediti" element={<Receivables />} />
              <Route path="/intercompany" element={<Intercompany />} />
              <Route path="/iva" element={<Vat />} />
              <Route path="/budget" element={<Budget />} />
              <Route path="/finanziamenti" element={<Loans />} />
              <Route path="/scontrini" element={<Receipts />} />
              <Route path="/contabilita/prima-nota" element={<Journal />} />
              <Route path="/contabilita/piano-conti" element={<ChartOfAccounts />} />
              <Route path="/contabilita/registri-iva" element={<VatRegisters />} />
              <Route path="/contabilita/bilancio" element={<Statements />} />
              <Route path="/contabilita/cespiti" element={<Assets />} />
              <Route path="/contabilita/chiusure" element={<Closing />} />
              <Route path="/contabilita/da-classificare" element={<Classify />} />
              <Route path="/salute" element={<Health />} />
              <Route path="/piano" element={<Plan />} />
              <Route path="/centrale-rischi" element={<CentralRisk />} />
              <Route path="/paghe" element={<Payroll />} />
              <Route path="/chiusura-mese" element={<MonthClose />} />
              <Route path="/commesse" element={<Projects />} />
              <Route path="/gruppo/consolidato" element={<Consolidated />} />
              <Route path="/gruppo/liquidita" element={<GroupCash />} />
              <Route path="/gruppo/confronto" element={<Compare />} />
              <Route path="/provvigioni" element={<Activations />} />
              <Route path="/provvigioni/rendiconti" element={<CommissionStatements />} />
              <Route path="/provvigioni/impostazioni" element={<CommissionSetup />} />
              <Route path="/sviluppatore" element={<DevStatus />} />
              <Route path="/sviluppatore/errori" element={<DevErrors />} />
              <Route path="/sviluppatore/titolare" element={<DevOwnerInvite />} />
              <Route path="/guida" element={<Guide />} />
              <Route path="/guida/:guideId" element={<Guide />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
