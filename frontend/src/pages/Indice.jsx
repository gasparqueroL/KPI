import { useState } from "react";
import { Link } from "react-router-dom";

// Mapeo de KPIs del PDF "KPIs por Área de Empresa" a su ubicación en la app.
// Estado: ok (implementado), parcial (proxy o subset), pendiente (no hay datos
// fuente o no se construyó todavía). Cuando un KPI está implementado, `ruta`
// + `donde` te lleva a la card/panel exacto.
//
// Mantener esta lista alineada con los routers reales: si se agrega un KPI,
// actualizar acá. Si se renombra un panel, actualizar `donde`.
const KPIS = [
  // ===== Dirección / Gerencia =====
  { area: "Dirección / Gerencia", nombre: "Rentabilidad neta (%)", estado: "ok",
    ruta: "/kpis-manuales", donde: "KPI derivado 'Margen neto %' por mes" },
  { area: "Dirección / Gerencia", nombre: "Margen operativo", estado: "ok",
    ruta: "/kpis-manuales", donde: "KPI derivado 'Margen operativo' por mes" },
  { area: "Dirección / Gerencia", nombre: "Crecimiento de ingresos (%)", estado: "ok",
    ruta: "/direccion", donde: "KPI 'Ingresos' con delta vs período anterior" },
  { area: "Dirección / Gerencia", nombre: "EBITDA", estado: "parcial",
    ruta: "/kpis-manuales", donde: "KPI derivado 'EBITDA (aprox)'",
    nota: "Sin amortizaciones cargadas, equivale a margen operativo." },
  { area: "Dirección / Gerencia", nombre: "Flujo de caja", estado: "ok",
    ruta: "/caja", donde: "Gráfico de flujo mensual + tabla de movimientos" },
  { area: "Dirección / Gerencia", nombre: "Punto de equilibrio", estado: "ok",
    ruta: "/config", donde: "Marcá categorías como `es_costo_fijo` → endpoint /api/kpis/financieros/punto-equilibrio computa PE",
    nota: "PE = costos_fijos / margen_contribucion%. Con cobertura% para ver si ya se superó." },
  { area: "Dirección / Gerencia", nombre: "ROI", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'capital_invertido' → KPI derivado ROI" },
  { area: "Dirección / Gerencia", nombre: "ROA (retorno sobre activos)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'activos_totales' → KPI derivado ROA" },
  { area: "Dirección / Gerencia", nombre: "ROE (retorno sobre patrimonio)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'patrimonio_neto' → KPI derivado ROE" },
  { area: "Dirección / Gerencia", nombre: "Índice de crecimiento sostenido", estado: "ok",
    ruta: "/direccion", donde: "Endpoint /api/kpis/financieros/crecimiento-sostenido (próximo: card en /direccion)",
    nota: "Promedio mensual de crecimiento de ingresos en últimos 12 meses + tasa anualizada." },

  // ===== Comercial / Ventas =====
  { area: "Comercial / Ventas", nombre: "Ventas totales", estado: "ok",
    ruta: "/direccion", donde: "KPI 'Ingresos' (también en /comercial)" },
  { area: "Comercial / Ventas", nombre: "Crecimiento de ventas (%)", estado: "ok",
    ruta: "/direccion", donde: "KPI 'Ingresos' delta vs período anterior" },
  { area: "Comercial / Ventas", nombre: "Tasa de cierre (%)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar `leads_cerrados_mes` + `leads_ganados_mes` → tasa derivada",
    nota: "Manual: contar leads cerrados (ganados+perdidos) y los ganados en el mes." },
  { area: "Comercial / Ventas", nombre: "Ticket promedio", estado: "ok",
    ruta: "/direccion", donde: "KPI 'Ticket promedio'" },
  { area: "Comercial / Ventas", nombre: "Nuevos clientes", estado: "ok",
    ruta: "/direccion", donde: "KPI 'Clientes nuevos'" },
  { area: "Comercial / Ventas", nombre: "CAC (costo adquisición de clientes)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'gasto_marketing' → CAC = gasto / clientes_nuevos" },
  { area: "Comercial / Ventas", nombre: "LTV (LifeTime Value)", estado: "parcial",
    ruta: "/kpis-manuales", donde: "KPI derivado 'LTV (proxy mensual)'",
    nota: "Proxy: ingresos / clientes_nuevos. Versión completa requiere datos de cohortes." },
  { area: "Comercial / Ventas", nombre: "Pipeline / Embudo de Ventas (%)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar `leads_calientes_actuales` → pipeline derivado",
    nota: "Cuenta de oportunidades vivas (sin etapas detalladas — eso requiere CRM)." },
  { area: "Comercial / Ventas", nombre: "Ciclo de venta (días)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar `ciclo_venta_dias` (input mensual)",
    nota: "Días promedio entre primer contacto del lead y cobro de la venta." },
  { area: "Comercial / Ventas", nombre: "Tasa de recompra", estado: "ok",
    ruta: "/comercial", donde: "Panel 'Recompra' / cohortes en /analisis" },

  // ===== Operaciones / Logística =====
  { area: "Operaciones / Logística", nombre: "Entregas a tiempo (%)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar `entregas_a_tiempo_mes` + `entregas_total_mes` → % derivado" },
  { area: "Operaciones / Logística", nombre: "Nivel de cumplimiento (%)", estado: "parcial",
    ruta: "/kpis-manuales", donde: "Mismo que Entregas a tiempo en este negocio (no es transporte)",
    nota: "El rubro del PDF sugería transporte; reusamos entregas_a_tiempo." },
  { area: "Operaciones / Logística", nombre: "Costo por viaje", estado: "no_aplica",
    nota: "Específico de transporte — no aplica al rubro de la empresa." },
  { area: "Operaciones / Logística", nombre: "Km productivos vs improductivos", estado: "no_aplica",
    nota: "Específico de transporte — no aplica al rubro." },
  { area: "Operaciones / Logística", nombre: "Índice de incidentes", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar `incidentes_operativos_mes`" },
  { area: "Operaciones / Logística", nombre: "Tiempo de carga/descarga", estado: "no_aplica",
    nota: "Específico de logística pesada — no aplica." },
  { area: "Operaciones / Logística", nombre: "Productividad por unidad", estado: "parcial",
    ruta: "/kpis-manuales", donde: "`productividad_por_empleado` (RRHH) cubre el caso para servicios." },
  { area: "Operaciones / Logística", nombre: "Tiempo de inactividad", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar `horas_inactividad_mes` + `horas_productivas_mes` → % derivado" },
  { area: "Operaciones / Logística", nombre: "Eficiencia operativa (%)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar `eficiencia_operativa_pct` (input mensual 0-100%)" },

  // ===== Administración / Finanzas =====
  { area: "Administración / Finanzas", nombre: "Días de cuentas por cobrar (DSO)", estado: "ok",
    ruta: "/cuentas-corrientes", donde: "KPI 'DSO' arriba a la derecha" },
  { area: "Administración / Finanzas", nombre: "Días de cuentas por pagar (DPO)", estado: "ok",
    ruta: "/proveedores", donde: "KPI 'DPO (días promedio de pago)' en cards arriba" },
  { area: "Administración / Finanzas", nombre: "Índice de morosidad", estado: "ok",
    ruta: "/cuentas-corrientes", donde: "Aging de cobros (clientes con saldo vencido)" },
  { area: "Administración / Finanzas", nombre: "Liquidez corriente", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'activos_corrientes' + 'pasivos_corrientes' → ratio derivado" },
  { area: "Administración / Finanzas", nombre: "Endeudamiento", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'pasivos_totales' + 'activos_totales' → % derivado" },
  { area: "Administración / Finanzas", nombre: "Capital de trabajo", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar activos/pasivos corrientes → derivado" },
  { area: "Administración / Finanzas", nombre: "Flujo de caja proyectado", estado: "ok",
    ruta: "/direccion", donde: "Panel 'Proyección del mes' (lineal según ritmo del mes)" },

  // ===== RRHH =====
  { area: "RRHH", nombre: "Rotación (%)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'bajas_mes' + empleados_inicio/fin → % derivado" },
  { area: "RRHH", nombre: "Ausentismo (%)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'dias_ausencia' + 'dias_laborables' → % derivado" },
  { area: "RRHH", nombre: "Clima laboral", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar score de encuesta interna" },
  { area: "RRHH", nombre: "Productividad por empleado", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'empleados_*' → ingresos/empleados derivado" },
  { area: "RRHH", nombre: "Tiempo de cobertura", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'dias_cobertura_vacante' por mes" },
  { area: "RRHH", nombre: "Índice de accidentabilidad", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'accidentes_mes' + empleados → ‰ derivado" },
  { area: "RRHH", nombre: "Satisfacción del empleado (eNPS)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'enps' por mes" },
  { area: "RRHH", nombre: "Antigüedad promedio", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'antiguedad_promedio_anios'" },

  // ===== Marketing =====
  { area: "Marketing", nombre: "Leads generados", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'leads_generados' por mes" },
  { area: "Marketing", nombre: "Costo por lead", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar gasto_marketing + leads → derivado" },
  { area: "Marketing", nombre: "Tasa de conversión", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'leads_generados' → conversión derivada" },
  { area: "Marketing", nombre: "Tráfico web", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'trafico_web' (sesiones de Google Analytics)" },
  { area: "Marketing", nombre: "ROMI", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'gasto_marketing' → ROMI derivado" },
  { area: "Marketing", nombre: "Costo por adquisición (CAC)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Mismo que CAC (Comercial)" },
  { area: "Marketing", nombre: "Alcance de campañas", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'alcance_campanas' (impresiones)" },

  // ===== Atención al Cliente =====
  { area: "Atención al Cliente", nombre: "NPS", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'nps' por mes" },
  { area: "Atención al Cliente", nombre: "Tiempo de respuesta", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'tiempo_respuesta_promedio_horas'" },
  { area: "Atención al Cliente", nombre: "Tasa de reclamos", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'reclamos_mes' → tasa derivada" },
  { area: "Atención al Cliente", nombre: "Tasa de retención", estado: "ok",
    ruta: "/analisis", donde: "Cohortes de retención" },
  { area: "Atención al Cliente", nombre: "Churn / clientes perdidos", estado: "ok",
    ruta: "/comercial", donde: "Panel 'Clientes perdidos'" },
  { area: "Atención al Cliente", nombre: "Tiempo de resolución", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'tiempo_resolucion_promedio_horas'" },
  { area: "Atención al Cliente", nombre: "Reclamos recurrentes", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'reclamos_recurrentes_mes' + 'reclamos_mes' → % derivado",
    nota: "Recurrente = mismo cliente reclamó 2+ veces en el mes." },
  { area: "Atención al Cliente", nombre: "Satisfacción post-servicio", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'satisfaccion_post_servicio' (1-10)" },

  // ===== Sistemas / IT =====
  { area: "Sistemas / IT", nombre: "Tiempo de resolución de incidencias", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar horas_resolucion + incidentes → promedio derivado" },
  { area: "Sistemas / IT", nombre: "Cantidad de incidentes", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'incidentes_it_mes' por mes" },
  { area: "Sistemas / IT", nombre: "Tiempo de caída", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'horas_downtime'" },
  { area: "Sistemas / IT", nombre: "Usuarios activos", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'usuarios_activos'" },
  { area: "Sistemas / IT", nombre: "Nivel de digitalización", estado: "parcial",
    ruta: "/kpis-manuales", donde: "Cargar 'procesos_total' + 'procesos_automatizados'",
    nota: "Mismo cálculo que automatización: % de procesos digitalizados." },
  { area: "Sistemas / IT", nombre: "Automatización de procesos (%)", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar procesos_total + procesos_automatizados → % derivado" },

  // ===== Compras / Abastecimiento =====
  { area: "Compras / Abastecimiento", nombre: "Costo de compras", estado: "ok",
    ruta: "/proveedores", donde: "Total facturas + aging de proveedores" },
  { area: "Compras / Abastecimiento", nombre: "Tiempo de reposición", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'tiempo_reposicion_dias' por mes" },
  { area: "Compras / Abastecimiento", nombre: "Nivel de stock", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar `stock_promedio_ars` (valuación al cierre del mes)" },
  { area: "Compras / Abastecimiento", nombre: "Rotación de inventario", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar `costo_mercaderia_vendida_mes` + `stock_promedio_ars` → CMV/stock" },
  { area: "Compras / Abastecimiento", nombre: "Quiebres de stock", estado: "ok",
    ruta: "/kpis-manuales", donde: "Cargar 'quiebres_stock' (cantidad mensual)" },
  { area: "Compras / Abastecimiento", nombre: "Dependencia de proveedores", estado: "ok",
    ruta: "/proveedores", donde: "Card 'Concentración top 1 proveedor' + tabla 'Dependencia de proveedores'" },

  // ===== Extras implementados (no estaban en el PDF original) =====
  { area: "Extras (no en PDF)", nombre: "Saldos por caja en tiempo real", estado: "ok",
    ruta: "/caja", donde: "Tabla 'Saldos por caja'" },
  { area: "Extras (no en PDF)", nombre: "Conciliación facturado vs cobrado", estado: "ok",
    ruta: "/conciliacion", donde: "Tabs sin-cobro / discrepancias / cta-cte emitidas" },
  { area: "Extras (no en PDF)", nombre: "Composición de gastos por familia", estado: "ok",
    ruta: "/caja", donde: "Pie chart 'Composición de gastos'" },
  { area: "Extras (no en PDF)", nombre: "Top productos / clientes / vendedores", estado: "ok",
    ruta: "/comercial", donde: "Tablas de rankings" },
  { area: "Extras (no en PDF)", nombre: "Análisis ABC de productos", estado: "ok",
    ruta: "/comercial", donde: "Tabla ABC con clase A/B/C" },
  { area: "Extras (no en PDF)", nombre: "Productos a pérdida (margen negativo)", estado: "ok",
    ruta: "/comercial", donde: "Panel 'Productos a pérdida'" },
  { area: "Extras (no en PDF)", nombre: "Movimientos atípicos (montos altos)", estado: "ok",
    ruta: "/caja", donde: "Panel 'Movimientos atípicos'" },
  { area: "Extras (no en PDF)", nombre: "Concentración de clientes (top 1/3/5)", estado: "ok",
    ruta: "/direccion", donde: "Cards 'Top 1/Top 3/Top 5 clientes'" },
  { area: "Extras (no en PDF)", nombre: "Cierres de caja diaria + auditoría", estado: "ok",
    ruta: "/caja-diaria", donde: "Tabla de cierres + panel de auditoría con discrepancias" },
];

const ESTADOS = {
  ok: { label: "Implementado", color: "#34d399", bg: "#064e3b" },
  parcial: { label: "Parcial", color: "#fbbf24", bg: "#78350f" },
  pendiente: { label: "Pendiente", color: "#94a3b8", bg: "#1e293b" },
  // "no aplica" = decisión consciente de NO implementar (KPI específico
  // de otro rubro). Se excluye del denominador de cobertura.
  no_aplica: { label: "No aplica", color: "#64748b", bg: "#0f172a" },
};

export default function Indice() {
  const [filtroArea, setFiltroArea] = useState("");
  const [filtroEstado, setFiltroEstado] = useState("");
  const [busqueda, setBusqueda] = useState("");

  const areas = [...new Set(KPIS.map((k) => k.area))];
  const filtrados = KPIS.filter((k) => {
    if (filtroArea && k.area !== filtroArea) return false;
    if (filtroEstado && k.estado !== filtroEstado) return false;
    if (busqueda && !k.nombre.toLowerCase().includes(busqueda.toLowerCase())) return false;
    return true;
  });

  // Resumen por estado
  const totales = KPIS.reduce((acc, k) => {
    acc[k.estado] = (acc[k.estado] || 0) + 1;
    return acc;
  }, {});
  // Excluir "no_aplica" del denominador: son decisiones explícitas de
  // NO implementar (rubro distinto). Sin esto, 4 KPIs de transporte
  // bajan la cobertura artificialmente del 100% al 94%.
  const esPedidoAplicable = (k) =>
    !k.area.startsWith("Extras") && k.estado !== "no_aplica";
  const totalPedidos = KPIS.filter(esPedidoAplicable).length;
  const okPedidos = KPIS.filter((k) => esPedidoAplicable(k) && k.estado === "ok").length;
  const parcialPedidos = KPIS.filter((k) => esPedidoAplicable(k) && k.estado === "parcial").length;
  const noAplicaPedidos = KPIS.filter((k) => k.estado === "no_aplica").length;

  return (
    <>
      <h2>Índice de KPIs</h2>
      <p style={{ color: "#94a3b8", marginTop: -10 }}>
        Mapa de los KPIs del PDF original a su ubicación actual en el dashboard.
        Los marcados como <b>parcial</b> tienen un proxy razonable pero no la fórmula completa
        (típicamente faltan datos de balance contable). Los <b>pendientes</b> requieren
        cargar datos nuevos al sistema (RRHH, marketing, leads, etc.).
      </p>

      <div className="kpi-grid">
        <div className="kpi-card green">
          <div className="label">Implementados (PDF)</div>
          <div className="value">{okPedidos} / {totalPedidos}</div>
          <div className="sub">{Math.round(okPedidos / totalPedidos * 100)}% del pedido original</div>
        </div>
        <div className="kpi-card amber">
          <div className="label">Parciales</div>
          <div className="value">{parcialPedidos}</div>
          <div className="sub">Tienen proxy / fórmula simplificada</div>
        </div>
        <div className="kpi-card muted">
          <div className="label">Pendientes</div>
          <div className="value">{(totales.pendiente || 0)}</div>
          <div className="sub">Esperan datos fuente</div>
        </div>
        <div className="kpi-card">
          <div className="label">Extras (no pedidos)</div>
          <div className="value">{KPIS.filter((k) => k.area.startsWith("Extras")).length}</div>
          <div className="sub">Bonus tracks del dashboard</div>
        </div>
      </div>

      <div className="toolbar">
        <label>Área</label>
        <select value={filtroArea} onChange={(e) => setFiltroArea(e.target.value)}>
          <option value="">Todas</option>
          {areas.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <label>Estado</label>
        <select value={filtroEstado} onChange={(e) => setFiltroEstado(e.target.value)}>
          <option value="">Todos</option>
          <option value="ok">Implementados</option>
          <option value="parcial">Parciales</option>
          <option value="pendiente">Pendientes</option>
        </select>
        <input
          type="search"
          placeholder="Buscar KPI..."
          value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)}
          style={{ flex: 1, minWidth: 200 }}
        />
      </div>

      <div className="panel">
        <h3>{filtrados.length} KPI{filtrados.length === 1 ? "" : "s"}</h3>
        <table>
          <thead>
            <tr>
              <th style={{ width: 200 }}>Área</th>
              <th>KPI</th>
              <th style={{ width: 110 }}>Estado</th>
              <th style={{ width: 280 }}>Dónde verlo</th>
              <th style={{ width: 120 }}>Ir</th>
            </tr>
          </thead>
          <tbody>
            {filtrados.map((k, i) => {
              const e = ESTADOS[k.estado];
              return (
                <tr key={i}>
                  <td style={{ color: "#94a3b8", fontSize: 12 }}>{k.area}</td>
                  <td>
                    <div style={{ fontWeight: 500 }}>{k.nombre}</div>
                    {k.nota && (
                      <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                        {k.nota}
                      </div>
                    )}
                  </td>
                  <td>
                    <span
                      className="badge"
                      style={{ background: e.bg, color: e.color, border: `1px solid ${e.color}40` }}
                    >
                      {e.label}
                    </span>
                  </td>
                  <td style={{ fontSize: 12, color: "#cbd5e1" }}>
                    {k.donde || <span style={{ color: "#475569" }}>—</span>}
                  </td>
                  <td>
                    {k.ruta ? (
                      <Link to={k.ruta} className="btn-ghost btn" style={{ fontSize: 12 }}>
                        Ver →
                      </Link>
                    ) : (
                      <span style={{ color: "#475569", fontSize: 12 }}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
