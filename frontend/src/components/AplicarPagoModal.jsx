import { useEffect, useMemo, useState } from "react";
import api, { fmtMoney } from "../api/client";
import Modal from "./Modal";
import { useToast } from "./Toast";

/**
 * Modal para aplicar (parcialmente) un movimiento de cobranza a una venta
 * específica del cliente. Usa el endpoint POST /api/pagos-aplicados.
 *
 * Props:
 * - movimiento: { id, monto, fecha, descripcion, ref_id }
 * - ventasPendientes: [{ id_pedido, descripcion, saldo, fecha }]
 * - onClose(): cerrar sin cambios
 * - onAplicado(): aplicación exitosa (refrescar ledger)
 */
export default function AplicarPagoModal({ movimiento, ventasPendientes, onClose, onAplicado }) {
  const toast = useToast();
  const [disponible, setDisponible] = useState(null);
  const [idVenta, setIdVenta] = useState("");
  const [montoCustom, setMontoCustom] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!movimiento?.id) return;
    api.get(`/api/pagos-aplicados/movimiento/${movimiento.id}`, { silent: true })
      .then((r) => setDisponible(r.data.disponible))
      .catch(() => setDisponible(0));
  }, [movimiento?.id]);

  const ventaSeleccionada = useMemo(
    () => ventasPendientes.find((v) => v.id_pedido === idVenta),
    [ventasPendientes, idVenta],
  );

  const montoSugerido = useMemo(() => {
    if (disponible == null || !ventaSeleccionada) return 0;
    return Math.min(disponible, ventaSeleccionada.saldo);
  }, [disponible, ventaSeleccionada]);

  async function aplicar() {
    if (!idVenta) {
      toast.push("Elegí una venta a la que aplicar el pago", "error");
      return;
    }
    setBusy(true);
    try {
      const monto = montoCustom ? Number(montoCustom) : null;
      await api.post("/api/pagos-aplicados", {
        id_pedido: idVenta,
        id_movimiento: movimiento.id,
        monto,
      });
      toast.push("Pago aplicado correctamente", "success");
      onAplicado();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error al aplicar el pago", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={!!movimiento} onClose={onClose} title="Aplicar pago a venta" width={560}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ background: "#0f172a", padding: 12, borderRadius: 8 }}>
          <div style={{ fontSize: 12, color: "#94a3b8" }}>Movimiento</div>
          <div style={{ fontWeight: 600 }}>{movimiento.descripcion}</div>
          <div style={{ fontSize: 13, color: "#cbd5e1" }}>
            Total: {fmtMoney(movimiento.monto)} · Disponible:{" "}
            <b style={{ color: disponible > 0 ? "#34d399" : "#f87171" }}>
              {disponible == null ? "..." : fmtMoney(disponible)}
            </b>
          </div>
        </div>

        <div>
          <label style={{ fontSize: 12, color: "#94a3b8", display: "block", marginBottom: 4 }}>
            Aplicar a venta
          </label>
          <select
            value={idVenta}
            onChange={(e) => setIdVenta(e.target.value)}
            style={{ width: "100%" }}
          >
            <option value="">— elegí una venta —</option>
            {ventasPendientes.map((v) => (
              <option key={v.id_pedido} value={v.id_pedido}>
                {v.descripcion} — saldo {fmtMoney(v.saldo)}
              </option>
            ))}
          </select>
          {ventasPendientes.length === 0 && (
            <div style={{ color: "#94a3b8", fontSize: 12, marginTop: 4 }}>
              Este cliente no tiene ventas con saldo pendiente.
            </div>
          )}
        </div>

        <div>
          <label style={{ fontSize: 12, color: "#94a3b8", display: "block", marginBottom: 4 }}>
            Monto a aplicar (vacío = cubrir mínimo entre disponible y saldo: <b>{fmtMoney(montoSugerido)}</b>)
          </label>
          <input
            type="number"
            step="0.01"
            value={montoCustom}
            onChange={(e) => setMontoCustom(e.target.value)}
            placeholder={String(montoSugerido)}
            style={{ width: "100%" }}
          />
        </div>

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 6 }}>
          <button className="btn-ghost btn" onClick={onClose} disabled={busy}>Cancelar</button>
          <button
            className="btn"
            onClick={aplicar}
            disabled={busy || !idVenta || (disponible != null && disponible <= 0)}
          >
            {busy ? <span className="spinner" /> : "Aplicar"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
