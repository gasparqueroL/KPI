# Proveedores + Cuentas a Pagar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Espejo de Cuentas Corrientes pero del lado proveedor. Catálogo de proveedores, facturas con vencimiento, vinculación de pagos (egresos de caja) a facturas, ledger por proveedor con saldo running.

**Architecture:** 2 modelos nuevos (`Proveedor`, `FacturaProveedor`). Reutilizo el patrón de `id_cliente_relacionado` agregando `id_factura_proveedor` a `MovimientoCaja` para vincular egresos a facturas. Pantalla nueva `/proveedores` con listado de proveedores → ledger por proveedor (estilo extracto bancario inverso).

**Tech Stack:** Existente.

---

## Task 1: Modelos + migración

**Files:**
- Create: `backend/app/models/proveedor.py`
- Modify: `backend/app/models/movimiento_caja.py` (agregar columna)
- Modify: `backend/app/models/__init__.py`
- Generate: migración Alembic

- [ ] **Step 1: Crear `backend/app/models/proveedor.py`**

```python
from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from app.db import Base


class Proveedor(Base):
    """Catálogo de proveedores (espejo de clientes para deuda comercial)."""

    __tablename__ = "proveedores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String, nullable=False, index=True)
    cuit = Column(String, nullable=True, index=True)
    contacto = Column(String, nullable=True)  # tel/email/quien atiende
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    facturas = relationship("FacturaProveedor", back_populates="proveedor", cascade="all, delete-orphan")


class FacturaProveedor(Base):
    """Factura emitida por un proveedor a la empresa. Pendiente o pagada."""

    __tablename__ = "facturas_proveedor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    id_proveedor = Column(Integer, ForeignKey("proveedores.id"), nullable=False, index=True)
    numero = Column(String, nullable=True)  # número de factura del proveedor
    fecha_emision = Column(Date, nullable=False, index=True)
    fecha_vencimiento = Column(Date, nullable=True, index=True)
    total = Column(Numeric(14, 2), nullable=False)
    descripcion = Column(String, nullable=True)
    observaciones = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    proveedor = relationship("Proveedor", back_populates="facturas")
```

- [ ] **Step 2: Agregar columna `id_factura_proveedor` a `MovimientoCaja`**

En `backend/app/models/movimiento_caja.py`, después de `id_cliente_relacionado`, agregar:

```python
    # Para egresos: factura del proveedor que se está pagando.
    # Permite armar el ledger del proveedor vinculando facturas con pagos.
    id_factura_proveedor = Column(
        Integer, ForeignKey("facturas_proveedor.id"), nullable=True, index=True
    )
```

- [ ] **Step 3: Registrar en `__init__.py`**

Agregar import y `"Proveedor"`, `"FacturaProveedor"` al `__all__`.

- [ ] **Step 4: Generar y aplicar migración**

```bash
cd "C:/Users/HP ENVY/Desktop/KPI/backend" && source .venv/Scripts/activate
alembic revision --autogenerate -m "proveedores_y_facturas"
```

Revisar el archivo generado: debería crear `proveedores`, `facturas_proveedor`, y agregar `id_factura_proveedor` a `movimientos_caja`. Si no hay otros cambios accidentales:

```bash
alembic upgrade head
```

- [ ] **Step 5: Verificar**

```bash
python -c "from app.db import engine; from sqlalchemy import inspect; t=inspect(engine).get_table_names(); print('proveedores:', 'proveedores' in t); print('facturas_proveedor:', 'facturas_proveedor' in t)"
```
Esperado: ambos `True`.

---

## Task 2: KPI helpers + tests

**Files:**
- Create: `backend/app/kpis/proveedores.py`
- Create: `backend/tests/test_proveedores.py`

- [ ] **Step 1: Crear módulo `kpis/proveedores.py`**

```python
"""KPIs de proveedores y cuentas a pagar."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor


def _to_float(v) -> float:
    return float(v) if v is not None else 0.0


def proveedores_con_saldo(db: Session) -> list[dict[str, Any]]:
    """Lista de proveedores con su saldo (facturado - pagado).
    Incluye proveedores con saldo > 0 ó actividad reciente."""
    facturado = dict(
        db.query(
            FacturaProveedor.id_proveedor,
            func.coalesce(func.sum(FacturaProveedor.total), 0),
        ).group_by(FacturaProveedor.id_proveedor).all()
    )

    pagado = dict(
        db.query(
            MovimientoCaja.id_factura_proveedor,
            func.coalesce(func.sum(MovimientoCaja.monto), 0),
        ).filter(
            MovimientoCaja.id_factura_proveedor.isnot(None),
            MovimientoCaja.caja_origen.isnot(None),
        ).group_by(MovimientoCaja.id_factura_proveedor).all()
    )

    # Mapear pagos a proveedor via factura
    facturas_a_proveedor = dict(
        db.query(FacturaProveedor.id, FacturaProveedor.id_proveedor).all()
    )
    pagado_por_proveedor: dict = {}
    for fact_id, monto in pagado.items():
        p = facturas_a_proveedor.get(fact_id)
        if p is not None:
            pagado_por_proveedor[p] = pagado_por_proveedor.get(p, Decimal(0)) + Decimal(str(monto))

    out = []
    for p in db.query(Proveedor).order_by(Proveedor.nombre).all():
        f = Decimal(str(facturado.get(p.id, 0)))
        pa = Decimal(str(pagado_por_proveedor.get(p.id, 0)))
        saldo = f - pa
        out.append({
            "id": p.id,
            "nombre": p.nombre,
            "cuit": p.cuit,
            "contacto": p.contacto,
            "activo": p.activo,
            "facturado_total": _to_float(f),
            "pagado_total": _to_float(pa),
            "saldo": _to_float(saldo),
        })
    out.sort(key=lambda r: r["saldo"], reverse=True)
    return out


def ledger_proveedor(db: Session, id_proveedor: int) -> dict[str, Any]:
    """Extracto del proveedor: facturas (DEBE) + pagos vinculados (HABER)."""
    p = db.get(Proveedor, id_proveedor)
    if p is None:
        return {"id": id_proveedor, "nombre": "(no encontrado)", "eventos": []}

    facturas = db.query(FacturaProveedor).filter(
        FacturaProveedor.id_proveedor == id_proveedor
    ).order_by(FacturaProveedor.fecha_emision).all()

    pagos = db.query(MovimientoCaja).join(
        FacturaProveedor, FacturaProveedor.id == MovimientoCaja.id_factura_proveedor
    ).filter(
        FacturaProveedor.id_proveedor == id_proveedor,
        MovimientoCaja.caja_origen.isnot(None),
    ).order_by(MovimientoCaja.fecha).all()

    eventos = []
    for f in facturas:
        eventos.append({
            "fecha": f.fecha_emision.isoformat(),
            "tipo": "factura",
            "descripcion": f"Factura {f.numero or '(sin nro)'}{' - ' + f.descripcion if f.descripcion else ''}",
            "vencimiento": f.fecha_vencimiento.isoformat() if f.fecha_vencimiento else None,
            "debe": float(f.total),
            "haber": 0.0,
            "ref_id": f.id,
            "ref_tipo": "factura",
        })
    for m in pagos:
        eventos.append({
            "fecha": m.fecha.isoformat(),
            "tipo": "pago",
            "descripcion": f"{m.tipo_operacion}: {m.detalle or ''}",
            "vencimiento": None,
            "debe": 0.0,
            "haber": float(m.monto),
            "ref_id": m.id,
            "ref_tipo": "movimiento",
            "caja": m.caja_origen,
        })

    eventos.sort(key=lambda e: (e["fecha"][:10], 0 if e["tipo"] == "factura" else 1))

    saldo = Decimal(0)
    for e in eventos:
        saldo += Decimal(str(e["debe"])) - Decimal(str(e["haber"]))
        e["saldo"] = float(saldo)

    total_debe = sum(e["debe"] for e in eventos)
    total_haber = sum(e["haber"] for e in eventos)

    return {
        "id": p.id,
        "nombre": p.nombre,
        "cuit": p.cuit,
        "contacto": p.contacto,
        "saldo_actual": float(saldo),
        "total_debe": total_debe,
        "total_haber": total_haber,
        "eventos": eventos,
    }


def vencimientos_proximos(
    db: Session,
    dias_ventana: int = 30,
) -> list[dict[str, Any]]:
    """Facturas con vencimiento en los próximos N días que NO están totalmente pagadas."""
    from datetime import timedelta
    hoy = date.today()
    limite = hoy + timedelta(days=dias_ventana)

    facturas = db.query(FacturaProveedor).filter(
        FacturaProveedor.fecha_vencimiento.isnot(None),
        FacturaProveedor.fecha_vencimiento <= limite,
    ).order_by(FacturaProveedor.fecha_vencimiento).all()

    # Pagos por factura
    pagado_por_factura = dict(
        db.query(
            MovimientoCaja.id_factura_proveedor,
            func.coalesce(func.sum(MovimientoCaja.monto), 0),
        ).filter(
            MovimientoCaja.id_factura_proveedor.isnot(None),
            MovimientoCaja.caja_origen.isnot(None),
        ).group_by(MovimientoCaja.id_factura_proveedor).all()
    )

    out = []
    for f in facturas:
        pagado = Decimal(str(pagado_por_factura.get(f.id, 0)))
        pendiente = Decimal(str(f.total)) - pagado
        if pendiente <= 0:
            continue  # totalmente pagada
        dias_para_vencer = (f.fecha_vencimiento - hoy).days
        out.append({
            "id_factura": f.id,
            "id_proveedor": f.id_proveedor,
            "proveedor": f.proveedor.nombre,
            "numero": f.numero,
            "fecha_emision": f.fecha_emision.isoformat(),
            "fecha_vencimiento": f.fecha_vencimiento.isoformat(),
            "dias_para_vencer": dias_para_vencer,
            "vencida": dias_para_vencer < 0,
            "total": float(f.total),
            "pagado": _to_float(pagado),
            "pendiente": _to_float(pendiente),
        })
    return out
```

- [ ] **Step 2: Tests**

`backend/tests/test_proveedores.py`:

```python
"""Tests del módulo proveedores."""
from datetime import date
from decimal import Decimal

from app.kpis.proveedores import ledger_proveedor, proveedores_con_saldo, vencimientos_proximos
from app.models.caja import Caja
from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor


def _setup(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    p = Proveedor(nombre="Insumos SA", cuit="30-12345678-9")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_proveedor_sin_facturas_tiene_saldo_cero(db):
    p = _setup(db)
    out = proveedores_con_saldo(db)
    assert len(out) == 1
    assert out[0]["nombre"] == "Insumos SA"
    assert out[0]["saldo"] == 0.0


def test_factura_genera_saldo_pendiente(db):
    p = _setup(db)
    db.add(FacturaProveedor(
        id_proveedor=p.id, numero="A-001",
        fecha_emision=date(2026, 4, 1),
        total=Decimal("10000"),
    ))
    db.commit()

    out = proveedores_con_saldo(db)
    assert out[0]["saldo"] == 10000.0
    assert out[0]["facturado_total"] == 10000.0
    assert out[0]["pagado_total"] == 0.0


def test_pago_vinculado_reduce_saldo(db):
    p = _setup(db)
    f = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=date(2026, 4, 1),
        total=Decimal("10000"),
    )
    db.add(f)
    db.commit()
    db.refresh(f)

    db.add(MovimientoCaja(
        fecha=date(2026, 4, 15),
        tipo_operacion="Materia Prima",
        monto=Decimal("3000"),
        caja_origen="cl",
        id_factura_proveedor=f.id,
        hash_dedupe="hp1",
    ))
    db.commit()

    out = proveedores_con_saldo(db)
    assert out[0]["pagado_total"] == 3000.0
    assert out[0]["saldo"] == 7000.0

    led = ledger_proveedor(db, p.id)
    assert led["saldo_actual"] == 7000.0
    assert led["total_debe"] == 10000.0
    assert led["total_haber"] == 3000.0
    assert len(led["eventos"]) == 2
    assert led["eventos"][0]["tipo"] == "factura"
    assert led["eventos"][1]["tipo"] == "pago"


def test_vencimientos_proximos_filtra_pagadas(db):
    from datetime import timedelta
    p = _setup(db)
    hoy = date.today()
    db.add(FacturaProveedor(
        id_proveedor=p.id, fecha_emision=hoy,
        fecha_vencimiento=hoy + timedelta(days=10),
        total=Decimal("5000"),
    ))
    f_pagada = FacturaProveedor(
        id_proveedor=p.id, fecha_emision=hoy,
        fecha_vencimiento=hoy + timedelta(days=5),
        total=Decimal("2000"),
    )
    db.add(f_pagada)
    db.commit()
    db.refresh(f_pagada)
    db.add(MovimientoCaja(
        fecha=hoy, tipo_operacion="Materia Prima", monto=Decimal("2000"),
        caja_origen="cl", id_factura_proveedor=f_pagada.id, hash_dedupe="hp2",
    ))
    db.commit()

    out = vencimientos_proximos(db, dias_ventana=30)
    assert len(out) == 1, "la factura pagada no debe aparecer"
    assert out[0]["pendiente"] == 5000.0
```

- [ ] **Step 3: Correr tests**

```bash
pytest tests/test_proveedores.py -v
```
Esperado: 4 passed.

- [ ] **Step 4: Suite completa**

```bash
pytest
```
Esperado: 67+ passed.

---

## Task 3: Endpoints (CRUD proveedores + facturas + ledger)

**Files:**
- Create: `backend/app/routers/proveedores_router.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Crear `backend/app/routers/proveedores_router.py`**

```python
"""Endpoints de proveedores y cuentas a pagar."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import proveedores as kpi_prov
from app.models.movimiento_caja import MovimientoCaja
from app.models.proveedor import FacturaProveedor, Proveedor
from app.routers._cache_helpers import invalida_alertas

router = APIRouter(prefix="/api/proveedores", tags=["proveedores"])


# ===== Listado y ledger =====

@router.get("")
def listar(db: Session = Depends(get_db)):
    return kpi_prov.proveedores_con_saldo(db)


@router.get("/vencimientos-proximos")
def vencimientos(
    dias: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return kpi_prov.vencimientos_proximos(db, dias_ventana=dias)


@router.get("/{id_proveedor}/ledger")
def ledger(id_proveedor: int, db: Session = Depends(get_db)):
    return kpi_prov.ledger_proveedor(db, id_proveedor)


# ===== CRUD proveedor =====

class NuevoProveedor(BaseModel):
    nombre: str
    cuit: str | None = None
    contacto: str | None = None


@router.post("")
@invalida_alertas
def crear_proveedor(data: NuevoProveedor, db: Session = Depends(get_db)):
    if not data.nombre.strip():
        raise HTTPException(400, "Nombre es obligatorio")
    p = Proveedor(
        nombre=data.nombre.strip(),
        cuit=(data.cuit or "").strip() or None,
        contacto=(data.contacto or "").strip() or None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"ok": True, "id": p.id}


class EditarProveedor(BaseModel):
    nombre: str | None = None
    cuit: str | None = None
    contacto: str | None = None
    activo: bool | None = None


@router.patch("/{id_proveedor}")
@invalida_alertas
def editar_proveedor(id_proveedor: int, data: EditarProveedor, db: Session = Depends(get_db)):
    p = db.get(Proveedor, id_proveedor)
    if p is None:
        raise HTTPException(404, "Proveedor no encontrado")
    if data.nombre is not None:
        p.nombre = data.nombre.strip() or p.nombre
    if data.cuit is not None:
        p.cuit = data.cuit.strip() or None
    if data.contacto is not None:
        p.contacto = data.contacto.strip() or None
    if data.activo is not None:
        p.activo = data.activo
    db.commit()
    return {"ok": True}


# ===== CRUD factura =====

class NuevaFactura(BaseModel):
    id_proveedor: int
    numero: str | None = None
    fecha_emision: date
    fecha_vencimiento: date | None = None
    total: float
    descripcion: str | None = None
    observaciones: str | None = None


@router.post("/factura")
@invalida_alertas
def crear_factura(data: NuevaFactura, db: Session = Depends(get_db)):
    if data.total <= 0:
        raise HTTPException(400, "total debe ser > 0")
    if db.get(Proveedor, data.id_proveedor) is None:
        raise HTTPException(404, "Proveedor no encontrado")
    f = FacturaProveedor(
        id_proveedor=data.id_proveedor,
        numero=(data.numero or "").strip() or None,
        fecha_emision=data.fecha_emision,
        fecha_vencimiento=data.fecha_vencimiento,
        total=Decimal(str(data.total)),
        descripcion=(data.descripcion or "").strip() or None,
        observaciones=(data.observaciones or "").strip() or None,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return {"ok": True, "id": f.id}


@router.delete("/factura/{id_factura}")
@invalida_alertas
def eliminar_factura(id_factura: int, db: Session = Depends(get_db)):
    f = db.get(FacturaProveedor, id_factura)
    if f is None:
        raise HTTPException(404, "Factura no encontrada")
    # Si tiene pagos vinculados, primero hay que desvincularlos
    n_pagos = db.query(MovimientoCaja).filter(
        MovimientoCaja.id_factura_proveedor == id_factura
    ).count()
    if n_pagos > 0:
        raise HTTPException(
            409,
            f"La factura tiene {n_pagos} pagos vinculados. Desvinculá primero "
            "esos movimientos antes de borrar."
        )
    db.delete(f)
    db.commit()
    return {"ok": True}


# ===== Vincular movimiento a factura =====

class VincularPago(BaseModel):
    id_factura: int


@router.post("/movimiento/{movimiento_id}/vincular")
@invalida_alertas
def vincular_movimiento(movimiento_id: int, data: VincularPago, db: Session = Depends(get_db)):
    m = db.get(MovimientoCaja, movimiento_id)
    if m is None:
        raise HTTPException(404, "Movimiento no encontrado")
    if m.caja_origen is None:
        raise HTTPException(
            400,
            "Solo se pueden vincular EGRESOS (movimientos con caja_origen presente).",
        )
    if db.get(FacturaProveedor, data.id_factura) is None:
        raise HTTPException(404, "Factura no encontrada")
    m.id_factura_proveedor = data.id_factura
    db.commit()
    return {"ok": True}


@router.post("/movimiento/{movimiento_id}/desvincular")
@invalida_alertas
def desvincular_movimiento(movimiento_id: int, db: Session = Depends(get_db)):
    m = db.get(MovimientoCaja, movimiento_id)
    if m is None:
        raise HTTPException(404, "Movimiento no encontrado")
    m.id_factura_proveedor = None
    db.commit()
    return {"ok": True}


# ===== Movimientos sin asignar =====

@router.get("/movimientos-sin-asignar")
def movimientos_sin_asignar(
    busqueda: str | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Egresos que NO están vinculados a ninguna factura. Para asignar."""
    q = db.query(MovimientoCaja).filter(
        MovimientoCaja.caja_origen.isnot(None),
        MovimientoCaja.id_factura_proveedor.is_(None),
    )
    if busqueda:
        q = q.filter(MovimientoCaja.detalle.ilike(f"%{busqueda}%"))
    q = q.order_by(MovimientoCaja.fecha.desc()).limit(limite)
    return [
        {
            "id": m.id,
            "fecha": m.fecha.isoformat(),
            "tipo_operacion": m.tipo_operacion,
            "detalle": m.detalle,
            "monto": float(m.monto),
            "caja_origen": m.caja_origen,
        }
        for m in q.all()
    ]
```

- [ ] **Step 2: Registrar router en `main.py`**

Agregar `proveedores_router` al import (en orden alfabético) y `app.include_router(proveedores_router.router)`.

- [ ] **Step 3: Smoke test**

```bash
cd "C:/Users/HP ENVY/Desktop/KPI/backend" && source .venv/Scripts/activate && python -c "from app.main import app; print('OK', len(app.routes))"
```

- [ ] **Step 4: Suite completa**

```bash
pytest
```

---

## Task 4: Frontend — pantalla Proveedores

**Files:**
- Create: `frontend/src/pages/Proveedores.jsx`
- Modify: `frontend/src/App.jsx` (route)
- Modify: `frontend/src/components/Layout.jsx` (link en sidebar)

- [ ] **Step 1: Crear `frontend/src/pages/Proveedores.jsx`**

```jsx
import { Fragment, useEffect, useState } from "react";
import api, { fmtMoney, fmtNum } from "../api/client";
import { useConfirm } from "../components/ConfirmDialog";
import KpiCard from "../components/KpiCard";
import SortableTable from "../components/SortableTable";
import { useToast } from "../components/Toast";

export default function Proveedores() {
  const toast = useToast();
  const [proveedores, setProveedores] = useState([]);
  const [vencimientos, setVencimientos] = useState([]);
  const [filtro, setFiltro] = useState("");
  const [seleccionado, setSeleccionado] = useState(null);
  const [showAlta, setShowAlta] = useState(false);

  async function cargar() {
    const [p, v] = await Promise.all([
      api.get("/api/proveedores"),
      api.get("/api/proveedores/vencimientos-proximos", { params: { dias: 30 } }),
    ]);
    setProveedores(p.data);
    setVencimientos(v.data);
  }

  useEffect(() => { cargar(); }, []);

  const filtrados = proveedores.filter((p) =>
    (p.nombre || "").toLowerCase().includes(filtro.toLowerCase()) ||
    (p.cuit || "").includes(filtro)
  );

  const totalSaldo = proveedores.reduce((s, p) => s + p.saldo, 0);
  const conSaldo = proveedores.filter((p) => p.saldo > 0).length;
  const vencidas = vencimientos.filter((v) => v.vencida).length;

  return (
    <>
      <h2>Proveedores / Cuentas a pagar</h2>
      <p style={{ color: "#94a3b8", marginTop: -10 }}>
        Catálogo de proveedores con saldos pendientes y vencimientos próximos. Vinculá pagos (egresos de caja) a facturas para llevar la cta cte por proveedor.
      </p>

      <div className="kpi-grid">
        <KpiCard label="Proveedores con saldo" value={fmtNum(conSaldo)} sub={`de ${proveedores.length} totales`} />
        <KpiCard label="Total a pagar" value={fmtMoney(totalSaldo)} tone="amber" />
        <KpiCard label="Vencen en 30 días" value={fmtNum(vencimientos.length)} sub={vencidas > 0 ? `${vencidas} ya vencidas` : "ninguna vencida"} tone={vencidas > 0 ? "red" : undefined} />
      </div>

      {seleccionado ? (
        <DetalleProveedor
          idProveedor={seleccionado}
          onClose={() => { setSeleccionado(null); cargar(); }}
        />
      ) : (
        <>
          {vencimientos.length > 0 && (
            <div className="panel">
              <h3>Vencimientos próximos (30 días)</h3>
              <table>
                <thead><tr><th>Vence</th><th>Proveedor</th><th>Factura</th><th className="num">Pendiente</th><th>Estado</th></tr></thead>
                <tbody>
                  {vencimientos.map((v) => (
                    <tr key={v.id_factura}>
                      <td>{v.fecha_vencimiento}</td>
                      <td><a href="#" onClick={(e) => { e.preventDefault(); setSeleccionado(v.id_proveedor); }}>{v.proveedor}</a></td>
                      <td>{v.numero || "(sin nro)"}</td>
                      <td className="num" style={{ fontWeight: 600 }}>{fmtMoney(v.pendiente)}</td>
                      <td>
                        {v.vencida
                          ? <span className="badge err">vencida {Math.abs(v.dias_para_vencer)}d</span>
                          : v.dias_para_vencer <= 7
                            ? <span className="badge warn">{v.dias_para_vencer}d</span>
                            : <span className="badge muted">{v.dias_para_vencer}d</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <h3 style={{ margin: 0 }}>Proveedores</h3>
              <button className="btn" onClick={() => setShowAlta(true)}>+ Nuevo proveedor</button>
            </div>
            <input
              placeholder="Buscar por nombre o CUIT..."
              value={filtro}
              onChange={(e) => setFiltro(e.target.value)}
              style={{ marginBottom: 12, width: 280 }}
            />
            <SortableTable
              rowKey={(p) => p.id}
              rows={filtrados}
              initialSort={{ key: "saldo", dir: "desc" }}
              columns={[
                { key: "nombre", label: "Nombre", render: (p) => (
                  <a href="#" onClick={(e) => { e.preventDefault(); setSeleccionado(p.id); }}>{p.nombre}</a>
                )},
                { key: "cuit", label: "CUIT" },
                { key: "facturado_total", label: "Facturado", num: true, render: (p) => fmtMoney(p.facturado_total) },
                { key: "pagado_total", label: "Pagado", num: true, render: (p) => fmtMoney(p.pagado_total) },
                { key: "saldo", label: "Saldo", num: true, render: (p) => (
                  <span style={{ color: p.saldo > 0 ? "#fbbf24" : "#94a3b8", fontWeight: 600 }}>{fmtMoney(p.saldo)}</span>
                )},
              ]}
            />
            {filtrados.length === 0 && <div className="empty">No hay proveedores que coincidan.</div>}
          </div>

          {showAlta && <AltaProveedor onClose={() => setShowAlta(false)} onSaved={() => { setShowAlta(false); cargar(); }} />}
        </>
      )}
    </>
  );
}

function AltaProveedor({ onClose, onSaved }) {
  const toast = useToast();
  const [nombre, setNombre] = useState("");
  const [cuit, setCuit] = useState("");
  const [contacto, setContacto] = useState("");
  const [busy, setBusy] = useState(false);

  async function guardar() {
    if (!nombre.trim()) { toast.push("Nombre es obligatorio", "error"); return; }
    setBusy(true);
    try {
      await api.post("/api/proveedores", { nombre, cuit: cuit || null, contacto: contacto || null });
      toast.push("Proveedor creado", "success");
      onSaved();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error", "error");
    } finally { setBusy(false); }
  }

  return (
    <div className="panel" style={{ marginTop: 12 }}>
      <h3>Nuevo proveedor</h3>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 2fr auto auto", gap: 10, alignItems: "end" }}>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Nombre *</label>
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>CUIT</label>
          <input value={cuit} onChange={(e) => setCuit(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Contacto</label>
          <input value={contacto} onChange={(e) => setContacto(e.target.value)} placeholder="tel/email/quien atiende" style={{ width: "100%" }} />
        </div>
        <button className="btn" disabled={busy} onClick={guardar}>{busy ? <span className="spinner" /> : "Guardar"}</button>
        <button className="btn-ghost btn" onClick={onClose}>Cancelar</button>
      </div>
    </div>
  );
}

function DetalleProveedor({ idProveedor, onClose }) {
  const confirmar = useConfirm();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [showAltaFact, setShowAltaFact] = useState(false);
  const [sinAsignar, setSinAsignar] = useState([]);
  const [busqueda, setBusqueda] = useState("");
  const [vinculando, setVinculando] = useState(null);

  async function cargar() {
    const { data } = await api.get(`/api/proveedores/${idProveedor}/ledger`);
    setData(data);
  }
  async function cargarSinAsignar(b) {
    const { data } = await api.get("/api/proveedores/movimientos-sin-asignar", {
      params: b ? { busqueda: b, limite: 50 } : { limite: 30 },
    });
    setSinAsignar(data);
  }
  useEffect(() => { cargar(); }, [idProveedor]);
  useEffect(() => {
    const t = setTimeout(() => cargarSinAsignar(busqueda), 300);
    return () => clearTimeout(t);
  }, [busqueda, idProveedor]);

  async function vincularA(movId, idFactura) {
    await api.post(`/api/proveedores/movimiento/${movId}/vincular`, { id_factura: idFactura });
    toast.push("Pago vinculado", "success");
    cargar(); cargarSinAsignar(busqueda); setVinculando(null);
  }
  async function desvincular(movId) {
    await api.post(`/api/proveedores/movimiento/${movId}/desvincular`);
    cargar(); cargarSinAsignar(busqueda);
  }

  if (!data) return <div className="empty">Cargando...</div>;

  const facturasParaVincular = data.eventos.filter((e) => e.ref_tipo === "factura");

  return (
    <>
      <div className="toolbar">
        <button className="btn-ghost btn" onClick={onClose}>← Volver</button>
        <span style={{ fontSize: 16, color: "#f1f5f9", marginLeft: 16, flex: 1 }}>
          <b>{data.nombre}</b>
          {data.cuit && <span style={{ color: "#94a3b8", marginLeft: 8 }}>CUIT {data.cuit}</span>}
          {data.contacto && <span style={{ color: "#94a3b8", marginLeft: 12 }}>· {data.contacto}</span>}
        </span>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Saldo actual" value={fmtMoney(data.saldo_actual)} tone={data.saldo_actual > 0 ? "amber" : "green"} />
        <KpiCard label="Total facturado" value={fmtMoney(data.total_debe)} />
        <KpiCard label="Total pagado" value={fmtMoney(data.total_haber)} />
        <KpiCard label="Eventos" value={fmtNum(data.eventos.length)} />
      </div>

      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Extracto cronológico</h3>
          <button className="btn" onClick={() => setShowAltaFact(true)}>+ Nueva factura</button>
        </div>
        {showAltaFact && (
          <AltaFactura
            idProveedor={idProveedor}
            onClose={() => setShowAltaFact(false)}
            onSaved={() => { setShowAltaFact(false); cargar(); }}
          />
        )}
        {data.eventos.length === 0 && <div className="empty">Sin eventos.</div>}
        {data.eventos.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Tipo</th>
                <th>Descripción</th>
                <th>Vence</th>
                <th className="num">Debe</th>
                <th className="num">Haber</th>
                <th className="num">Saldo</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.eventos.map((e) => (
                <tr key={`${e.ref_tipo}-${e.ref_id}`}>
                  <td>{e.fecha?.slice(0, 10)}</td>
                  <td><span className={`badge ${e.tipo === "factura" ? "warn" : "ok"}`}>{e.tipo}</span></td>
                  <td>{e.descripcion}</td>
                  <td style={{ color: "#94a3b8", fontSize: 12 }}>{e.vencimiento || "-"}</td>
                  <td className="num" style={{ color: e.debe > 0 ? "#fbbf24" : "#475569" }}>{e.debe > 0 ? fmtMoney(e.debe) : "-"}</td>
                  <td className="num" style={{ color: e.haber > 0 ? "#34d399" : "#475569" }}>{e.haber > 0 ? fmtMoney(e.haber) : "-"}</td>
                  <td className="num" style={{ fontWeight: 600 }}>{fmtMoney(e.saldo)}</td>
                  <td>
                    {e.ref_tipo === "movimiento" && (
                      <button className="btn-ghost btn" onClick={() => desvincular(e.ref_id)}>Desvincular</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h3>Egresos sin vincular — asignar a este proveedor</h3>
        <input
          placeholder={`Buscar en detalle... (ej. "${data.nombre.split(" ")[0]}")`}
          value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)}
          style={{ marginBottom: 12, width: 360 }}
        />
        {sinAsignar.length === 0 && <div className="empty">No hay egresos sin vincular.</div>}
        {sinAsignar.length > 0 && (
          <table>
            <thead><tr><th>Fecha</th><th>Categoría</th><th>Detalle</th><th>Caja</th><th className="num">Monto</th><th></th></tr></thead>
            <tbody>
              {sinAsignar.map((m) => (
                <tr key={m.id}>
                  <td>{m.fecha}</td>
                  <td><span className="badge muted">{m.tipo_operacion}</span></td>
                  <td>{m.detalle}</td>
                  <td>{m.caja_origen}</td>
                  <td className="num">{fmtMoney(m.monto)}</td>
                  <td>
                    {vinculando === m.id ? (
                      <select
                        autoFocus
                        onChange={(e) => e.target.value && vincularA(m.id, Number(e.target.value))}
                        onBlur={() => setVinculando(null)}
                      >
                        <option value="">— elegir factura —</option>
                        {facturasParaVincular.map((f) => (
                          <option key={f.ref_id} value={f.ref_id}>
                            {f.descripcion} — {fmtMoney(f.debe)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <button className="btn" disabled={facturasParaVincular.length === 0} onClick={() => setVinculando(m.id)}>
                        Vincular →
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function AltaFactura({ idProveedor, onClose, onSaved }) {
  const toast = useToast();
  const [numero, setNumero] = useState("");
  const [fechaEmision, setFechaEmision] = useState(new Date().toISOString().slice(0, 10));
  const [fechaVencimiento, setFechaVencimiento] = useState("");
  const [total, setTotal] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [busy, setBusy] = useState(false);

  async function guardar() {
    if (!total || Number(total) <= 0) { toast.push("Total inválido", "error"); return; }
    setBusy(true);
    try {
      await api.post("/api/proveedores/factura", {
        id_proveedor: idProveedor,
        numero: numero || null,
        fecha_emision: fechaEmision,
        fecha_vencimiento: fechaVencimiento || null,
        total: Number(total),
        descripcion: descripcion || null,
      });
      toast.push("Factura creada", "success");
      onSaved();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error", "error");
    } finally { setBusy(false); }
  }

  return (
    <div style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, padding: 14, marginBottom: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 2fr auto auto", gap: 10, alignItems: "end" }}>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Nº factura</label>
          <input value={numero} onChange={(e) => setNumero(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Emisión *</label>
          <input type="date" value={fechaEmision} onChange={(e) => setFechaEmision(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Vencimiento</label>
          <input type="date" value={fechaVencimiento} onChange={(e) => setFechaVencimiento(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Total *</label>
          <input type="number" step="0.01" value={total} onChange={(e) => setTotal(e.target.value)} style={{ width: "100%", textAlign: "right" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Descripción</label>
          <input value={descripcion} onChange={(e) => setDescripcion(e.target.value)} style={{ width: "100%" }} />
        </div>
        <button className="btn" disabled={busy} onClick={guardar}>{busy ? <span className="spinner" /> : "Crear"}</button>
        <button className="btn-ghost btn" onClick={onClose}>Cancelar</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Agregar route en App.jsx**

```jsx
import Proveedores from "./pages/Proveedores";
// ...
<Route path="/proveedores" element={<Proveedores />} />
```

- [ ] **Step 3: Agregar link en sidebar (Layout.jsx)**

Después de `<NavLink to="/cuentas-corrientes">Cuentas corrientes</NavLink>`, agregar:
```jsx
          <NavLink to="/proveedores">Proveedores</NavLink>
```

- [ ] **Step 4: Verificar HMR sin errores**

```bash
tail -5 "C:/Users/HPENVY~1/AppData/Local/Temp/claude/C--Users-HP-ENVY-Desktop-KPI/9da45c74-2b57-441c-8041-3eb27c7f88dd/tasks/bag8xbw7i.output" 2>&1
```

NO commit.

---

## Resumen

| Task | Foco | Tiempo |
|------|------|--------|
| 1 | Modelos + migración | 15 min |
| 2 | KPIs + 4 tests | 30 min |
| 3 | 9 endpoints | 25 min |
| 4 | Pantalla completa | 40 min |

Total ~110 min.
