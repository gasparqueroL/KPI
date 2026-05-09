import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AlertasProvider } from "./components/AlertasContext";
import ApiErrorBridge from "./components/ApiErrorBridge";
import { ConfirmProvider } from "./components/ConfirmDialog";
import ErrorBoundary from "./components/ErrorBoundary";
import GlobalSearch from "./components/GlobalSearch";
import { ToastProvider } from "./components/Toast";
import Layout from "./components/Layout";
import Direccion from "./pages/Direccion";

// Direccion va eager (es la ruta default — la dueña arranca ahí, no
// queremos un flash de "Cargando..." en cada apertura). El resto va
// lazy: cada página es un chunk separado que se descarga al navegar.
// Con esto el bundle inicial baja de ~820KB a ~150-200KB.
const Analisis = lazy(() => import("./pages/Analisis"));
const Caja = lazy(() => import("./pages/Caja"));
const CajaDiaria = lazy(() => import("./pages/CajaDiaria"));
const CasosRevisar = lazy(() => import("./pages/CasosRevisar"));
const Comercial = lazy(() => import("./pages/Comercial"));
const Conciliacion = lazy(() => import("./pages/Conciliacion"));
const Configuracion = lazy(() => import("./pages/Configuracion"));
const CuentasCorrientes = lazy(() => import("./pages/CuentasCorrientes"));
const Importar = lazy(() => import("./pages/Importar"));
const Indice = lazy(() => import("./pages/Indice"));
const KpisManuales = lazy(() => import("./pages/KpisManuales"));
const Proveedores = lazy(() => import("./pages/Proveedores"));

function CargandoRuta() {
  return (
    <div className="empty" style={{ padding: 40, textAlign: "center" }}>
      <span className="spinner" /> Cargando...
    </div>
  );
}

// Routes envueltas en ErrorBoundary con reset por pathname: si una página
// crashea, la dueña navega a otra y se recupera (sin recargar la app).
// useLocation requiere estar dentro de BrowserRouter, por eso este wrapper.
function AppRoutes() {
  const location = useLocation();
  return (
    <ErrorBoundary resetKey={location.pathname}>
      <Suspense fallback={<CargandoRuta />}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/direccion" replace />} />
            <Route path="/direccion" element={<Direccion />} />
            <Route path="/importar" element={<Importar />} />
            <Route path="/comercial" element={<Comercial />} />
            <Route path="/caja" element={<Caja />} />
            <Route path="/caja-diaria" element={<CajaDiaria />} />
            <Route path="/conciliacion" element={<Conciliacion />} />
            <Route path="/cuentas-corrientes" element={<CuentasCorrientes />} />
            <Route path="/proveedores" element={<Proveedores />} />
            <Route path="/analisis" element={<Analisis />} />
            <Route path="/casos" element={<CasosRevisar />} />
            <Route path="/config" element={<Configuracion />} />
            <Route path="/indice" element={<Indice />} />
            <Route path="/kpis-manuales" element={<KpisManuales />} />
          </Route>
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <ApiErrorBridge />
        <ConfirmProvider>
          <AlertasProvider>
            <GlobalSearch />
            <AppRoutes />
          </AlertasProvider>
        </ConfirmProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}
