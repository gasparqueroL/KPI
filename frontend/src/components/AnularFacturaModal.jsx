import { useState } from "react";
import api, { fmtMoney } from "../api/client";
import Modal from "./Modal";
import { useToast } from "./Toast";

/**
 * Modal de confirmación para anular (soft-delete) una factura de proveedor.
 * - Soft-delete: la factura no se borra, queda con `anulada=true` y se
 *   excluye de saldo/aging/vencimientos.
 * - Los pagos vinculados quedan automáticamente desvinculados (vuelven a
 *   "egresos sin asignar") en el backend.
 *
 * Props:
 * - factura: { ref_id, descripcion, debe, vencimiento }
 * - onClose(): cerrar sin cambios
 * - onAnulada(): anulación exitosa (refrescar ledger)
 */
export default function AnularFacturaModal({ factura, onClose, onAnulada }) {
  const toast = useToast();
  const [motivo, setMotivo] = useState("");
  const [busy, setBusy] = useState(false);

  async function anular() {
    setBusy(true);
    try {
      await api.post(`/api/proveedores/factura/${factura.ref_id}/anular`, {
        motivo: motivo.trim() || null,
      });
      toast.push("Factura anulada", "success");
      onAnulada();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error al anular la factura", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={!!factura} onClose={onClose} title="Anular factura" width={560}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ background: "#0f172a", padding: 12, borderRadius: 8 }}>
          <div style={{ fontSize: 12, color: "#94a3b8" }}>Factura</div>
          <div style={{ fontWeight: 600 }}>{factura.descripcion}</div>
          <div style={{ fontSize: 13, color: "#cbd5e1" }}>
            Total: {fmtMoney(factura.debe)}
            {factura.vencimiento && <> · Vence: {factura.vencimiento}</>}
          </div>
        </div>

        <div style={{ background: "#422006", border: "1px solid #92400e", padding: 12, borderRadius: 8, fontSize: 13, color: "#fde68a" }}>
          La factura se marcará como <b>anulada</b> y dejará de contar para el saldo,
          aging y vencimientos. Los pagos que estuvieran vinculados quedarán como
          <b> egresos sin asignar</b>. Esta acción se puede revertir editando la base.
        </div>

        <div>
          <label style={{ fontSize: 12, color: "#94a3b8", display: "block", marginBottom: 4 }}>
            Motivo (opcional, queda en observaciones)
          </label>
          <input
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            placeholder="Ej: carga duplicada, error de monto, factura corregida..."
            style={{ width: "100%" }}
          />
        </div>

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 6 }}>
          <button className="btn-ghost btn" onClick={onClose} disabled={busy}>Cancelar</button>
          <button
            className="btn"
            style={{ background: "#dc2626" }}
            onClick={anular}
            disabled={busy}
          >
            {busy ? <span className="spinner" /> : "Anular factura"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
