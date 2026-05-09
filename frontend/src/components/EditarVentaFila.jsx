import { useEffect, useMemo, useState } from "react";
import api from "../api/client";
import { useConfirm } from "./ConfirmDialog";
import Icon from "./Icon";

/**
 * Editor inline de venta. Espera datos de la venta y la lista de cajas.
 * Si `cajasDisponibles` viene vacío, lo carga solo.
 */
export default function EditarVentaFila({ venta, cajasDisponibles, onCancel, onSaved }) {
  const confirmar = useConfirm();
  const [cliente, setCliente] = useState(venta.cliente || venta.venta_cliente || "");
  const [vendedor, setVendedor] = useState(venta.vendedor || venta.venta_vendedor || "");
  const [total, setTotal] = useState(String(venta.total || venta.venta_total || 0));
  const [caja1, setCaja1] = useState(venta.caja1 || venta.venta_caja1 || "");
  const [monto1, setMonto1] = useState(String(venta.monto_pago1 || venta.venta_monto_pago1 || ""));
  const [pagoV1, setPagoV1] = useState(venta.pago_v1 ?? venta.venta_pago_v1 ?? false);
  const [caja2, setCaja2] = useState(venta.caja2 || venta.venta_caja2 || "");
  const [monto2, setMonto2] = useState(String(venta.monto_pago2 || venta.venta_monto_pago2 || ""));
  const [pagoV2, setPagoV2] = useState(venta.pago_v2 ?? venta.venta_pago_v2 ?? false);
  const [esCtaCte, setEsCtaCte] = useState(venta.es_cuenta_corriente ?? venta.venta_es_cuenta_corriente ?? false);
  const [cajas, setCajas] = useState(cajasDisponibles || []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!cajasDisponibles || cajasDisponibles.length === 0) {
      api.get("/api/caja-diaria/sugerencias").then((r) => setCajas(r.data.cajas || []));
    }
  }, []);

  const cajasOrd = useMemo(
    () => [...cajas].sort((a, b) => a.nombre_display.localeCompare(b.nombre_display)),
    [cajas]
  );

  const displayDe = (norm) =>
    cajas.find((c) => c.nombre_normalizado === norm)?.nombre_display || norm || "";

  async function guardar(forzar = false) {
    setBusy(true);
    setError(null);
    try {
      const payload = {
        cliente: cliente || null,
        vendedor: vendedor || null,
        total: Number(total),
        caja1: caja1 ? caja1 : "",
        monto_pago1: monto1 ? Number(monto1) : 0,
        pago_v1: !!pagoV1,
        caja2: caja2 ? caja2 : "",
        monto_pago2: monto2 ? Number(monto2) : 0,
        pago_v2: !!pagoV2,
        limpiar_caja2: !caja2,
      };
      // primero la venta
      await api.patch(`/api/ventas/${encodeURIComponent(venta.id_pedido || venta.ref_id)}`, payload);
      // si cambió el flag cta cte, llamar al endpoint dedicado (que tiene el guard de C3)
      const ctaActual = venta.es_cuenta_corriente ?? venta.venta_es_cuenta_corriente ?? false;
      if (esCtaCte !== ctaActual) {
        try {
          await api.post(
            `/api/cuentas-corrientes/venta/${encodeURIComponent(venta.id_pedido || venta.ref_id)}/marcar-cta-cte`,
            { es_cuenta_corriente: esCtaCte, forzar }
          );
        } catch (e) {
          if (e.response?.status === 409) {
            const ok = await confirmar({
              titulo: "Confirmar cambio",
              mensaje: e.response.data.detail + "\n\n¿Forzar igualmente?",
              labelOk: "Forzar",
              peligroso: true,
            });
            if (ok) return guardar(true);
          } else throw e;
        }
      }
      onSaved();
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ padding: 14 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        <Field label="Cliente" width={180} value={cliente} onChange={setCliente} />
        <Field label="Vendedor" width={140} value={vendedor} onChange={setVendedor} />
        <Field label="Total" width={110} value={total} onChange={setTotal} type="number" num />

        <SelectCaja label="Caja 1" width={160} value={displayDe(caja1)} onChange={setCaja1} cajas={cajasOrd} />
        <Field label="Monto 1" width={110} value={monto1} onChange={setMonto1} type="number" num />
        <CheckField label="Verif. 1" checked={pagoV1} onChange={setPagoV1} />

        <SelectCaja label="Caja 2" width={160} value={displayDe(caja2)} onChange={setCaja2} cajas={cajasOrd} permiteVacio />
        <Field label="Monto 2" width={110} value={monto2} onChange={setMonto2} type="number" num />
        <CheckField label="Verif. 2" checked={pagoV2} onChange={setPagoV2} />

        <CheckField label="Cuenta corriente" checked={esCtaCte} onChange={setEsCtaCte} />
      </div>
      <div style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
        <button className="btn" disabled={busy} onClick={() => guardar()}>
          {busy ? <span className="spinner" /> : "Guardar cambios"}
        </button>
        <button className="btn-ghost btn" onClick={onCancel}>Cancelar</button>
        {error && (
          <span style={{ color: "#f87171", fontSize: 13, display: "inline-flex", alignItems: "center", gap: 4 }}>
            <Icon name="x" size={14} label="Error" /> {error}
          </span>
        )}
      </div>
    </div>
  );
}

function Field({ label, value, onChange, width, type = "text", num }) {
  return (
    <div style={{ width }}>
      <label style={{ fontSize: 11, color: "#94a3b8", display: "block" }}>{label}</label>
      <input
        type={type}
        step={type === "number" ? "0.01" : undefined}
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: "100%", textAlign: num ? "right" : "left", fontVariantNumeric: num ? "tabular-nums" : "normal" }}
      />
    </div>
  );
}

function SelectCaja({ label, value, onChange, cajas, width, permiteVacio }) {
  return (
    <div style={{ width }}>
      <label style={{ fontSize: 11, color: "#94a3b8", display: "block" }}>{label}</label>
      <select value={value || ""} onChange={(e) => onChange(e.target.value)} style={{ width: "100%" }}>
        <option value="">{permiteVacio ? "— sin caja 2 —" : "— elegí —"}</option>
        {cajas.map((c) => (
          <option key={c.nombre_normalizado} value={c.nombre_display}>{c.nombre_display}</option>
        ))}
      </select>
    </div>
  );
}

function CheckField({ label, checked, onChange }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", justifyContent: "flex-end", paddingBottom: 5 }}>
      <label style={{ fontSize: 11, color: "#94a3b8" }}>{label}</label>
      <input type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)} style={{ width: 18, height: 18 }} />
    </div>
  );
}
