import { useState } from "react";
import api from "../api/client";
import { useConfirm } from "./ConfirmDialog";
import Modal from "./Modal";
import { useToast } from "./Toast";

/**
 * Modal de edición de factura proveedor. El campo `total` solo se puede
 * editar si la factura no tiene pagos vinculados (el backend rechaza con
 * 409 si los hay). El resto de los campos son metadata segura.
 *
 * Props:
 * - factura: evento del ledger con campos estructurados
 *   { ref_id, numero, factura_descripcion, fecha, vencimiento,
 *     total, observaciones, tiene_pagos }
 * - onClose(): cerrar sin cambios
 * - onGuardado(): guardado exitoso (refrescar ledger)
 */
export default function EditarFacturaModal({ factura, onClose, onGuardado }) {
  const toast = useToast();
  const confirmar = useConfirm();
  const tienePagos = !!factura.tiene_pagos;
  const totalOriginal = Number(factura.total ?? factura.debe ?? 0);
  // Snapshots iniciales para detectar dirty state al cerrar.
  const orig = {
    numero: factura.numero || "",
    descripcion: factura.factura_descripcion || "",
    fechaEmision: factura.fecha?.slice(0, 10) || "",
    fechaVencimiento: factura.vencimiento || "",
    total: String(totalOriginal || ""),
    observaciones: factura.observaciones || "",
  };
  const [numero, setNumero] = useState(orig.numero);
  const [descripcion, setDescripcion] = useState(orig.descripcion);
  const [fechaEmision, setFechaEmision] = useState(orig.fechaEmision);
  const [fechaVencimiento, setFechaVencimiento] = useState(orig.fechaVencimiento);
  const [total, setTotal] = useState(orig.total);
  const [observaciones, setObservaciones] = useState(orig.observaciones);
  const [busy, setBusy] = useState(false);

  // Comparación por JSON: si más adelante alguien agrega un campo al modal,
  // basta agregarlo a `orig` y a `actual` (más abajo) — la comparación
  // detecta el cambio sin enumerar manualmente cada campo en isDirty.
  function isDirty() {
    const actual = { numero, descripcion, fechaEmision, fechaVencimiento, total, observaciones };
    return JSON.stringify(actual) !== JSON.stringify(orig);
  }

  async function intentarCerrar() {
    if (!isDirty()) {
      onClose();
      return;
    }
    const ok = await confirmar({
      titulo: "Descartar cambios",
      mensaje: "Editaste la factura pero no guardaste. ¿Querés salir y perder los cambios?",
      labelOk: "Descartar",
      peligroso: true,
    });
    if (ok) onClose();
  }

  async function guardar() {
    setBusy(true);
    try {
      // Semántica del PATCH (decidida por jurado): null = limpiar, ausente
      // = no tocar. Mandamos los campos editados explícitamente: si el input
      // quedó vacío, mandamos null para que el backend limpie el campo.
      const body = {
        numero: numero.trim() || null,
        descripcion: descripcion.trim() || null,
        fecha_emision: fechaEmision || null,
        fecha_vencimiento: fechaVencimiento || null,
        observaciones: observaciones.trim() || null,
      };
      // Solo incluyo total si cambió y la factura no tiene pagos —
      // mandar el mismo total a una con pagos dispararía 409 innecesario.
      if (!tienePagos && Number(total) !== totalOriginal) {
        body.total = Number(total);
      }
      await api.patch(`/api/proveedores/factura/${factura.ref_id}`, body);
      toast.push("Factura actualizada", "success");
      onGuardado();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error al guardar", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={!!factura} onClose={intentarCerrar} title="Editar factura" width={560}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Nº factura">
            <input value={numero} onChange={(e) => setNumero(e.target.value)} style={{ width: "100%" }} />
          </Field>
          <Field label="Total">
            <input
              type="number"
              step="0.01"
              value={total}
              onChange={(e) => setTotal(e.target.value)}
              disabled={tienePagos}
              style={{ width: "100%", textAlign: "right" }}
              title={tienePagos ? "Tiene pagos vinculados — desvinculá primero o anulá la factura" : ""}
            />
          </Field>
          <Field label="Fecha emisión">
            <input type="date" value={fechaEmision} onChange={(e) => setFechaEmision(e.target.value)} style={{ width: "100%" }} />
          </Field>
          <Field label="Fecha vencimiento">
            <input type="date" value={fechaVencimiento} onChange={(e) => setFechaVencimiento(e.target.value)} style={{ width: "100%" }} />
          </Field>
        </div>
        <Field label="Descripción">
          <input value={descripcion} onChange={(e) => setDescripcion(e.target.value)} style={{ width: "100%" }} />
        </Field>
        <Field label="Observaciones">
          <textarea
            value={observaciones}
            onChange={(e) => setObservaciones(e.target.value)}
            rows={2}
            style={{ width: "100%", resize: "vertical" }}
          />
        </Field>

        {tienePagos && (
          <div style={{ background: "#1e3a8a", border: "1px solid #3b82f6", padding: 10, borderRadius: 6, fontSize: 12, color: "#bfdbfe" }}>
            Esta factura tiene pagos vinculados. El total no se puede cambiar
            sin desvincular o anular la factura.
          </div>
        )}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 6 }}>
          <button className="btn-ghost btn" onClick={intentarCerrar} disabled={busy}>Cancelar</button>
          <button className="btn" onClick={guardar} disabled={busy}>
            {busy ? <span className="spinner" /> : "Guardar"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label style={{ fontSize: 11, color: "#94a3b8", display: "block", marginBottom: 4 }}>{label}</label>
      {children}
    </div>
  );
}
