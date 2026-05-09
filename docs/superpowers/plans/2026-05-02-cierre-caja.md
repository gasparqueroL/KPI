# Cierre de caja con bloqueo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Permitir cerrar la caja por día y caja, snapshoteando el saldo. Movimientos de fechas cerradas no se pueden editar/borrar a menos que se reabra el cierre. Habilita arqueos confiables y cierres mensuales.

**Architecture:** Nueva tabla `cierre_caja(id, fecha, caja, saldo_cierre, observaciones, created_at)`. Lógica de bloqueo en `editar_movimiento` y `eliminar_movimiento`: rechaza si la fecha del movimiento es <= último cierre de su caja. UI en CajaDiaria con botón "Cerrar día" + nueva pestaña "Cierres" para historial.

**Tech Stack:** Existente. Sin nuevas dependencias.

---

## Task 1: Modelo + migración + seed

**Files:**
- Create: `backend/app/models/cierre_caja.py`
- Modify: `backend/app/models/__init__.py`
- Generate: `backend/alembic/versions/<auto>_cierre_caja.py`

- [ ] **Step 1: Crear modelo**

`backend/app/models/cierre_caja.py`:

```python
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint

from app.db import Base


class CierreCaja(Base):
    """Cierre diario por caja: snapshot del saldo y bloqueo de movimientos.

    Una vez cerrada una fecha+caja, los movimientos de esa caja con
    fecha <= cierre.fecha NO se pueden editar ni borrar (a menos que
    se reabra el cierre).
    """

    __tablename__ = "cierres_caja"
    __table_args__ = (
        UniqueConstraint("fecha", "caja", name="uq_cierre_fecha_caja"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(Date, nullable=False, index=True)
    caja = Column(
        String, ForeignKey("cajas.nombre_normalizado"), nullable=False, index=True
    )
    saldo_cierre = Column(Numeric(14, 2), nullable=False)
    observaciones = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 2: Registrar el modelo en `__init__.py`**

En `backend/app/models/__init__.py`, agregar:
```python
from app.models.cierre_caja import CierreCaja
```

Y agregar `"CierreCaja"` al `__all__`.

- [ ] **Step 3: Generar migración**

```bash
cd "C:/Users/HP ENVY/Desktop/KPI/backend" && source .venv/Scripts/activate && alembic revision --autogenerate -m "cierre_caja"
```

- [ ] **Step 4: Aplicar**

```bash
alembic upgrade head
```

Esperado: `Running upgrade ... -> ..., cierre_caja`.

- [ ] **Step 5: Verificar**

```bash
python -c "from app.db import engine; from sqlalchemy import inspect; print('cierres_caja:' in str(inspect(engine).get_table_names()), inspect(engine).get_table_names())"
```
Esperado: contiene `'cierres_caja'`.

---

## Task 2: KPI helper para saldo por caja en una fecha + bloqueo

**Files:**
- Create: `backend/app/kpis/cierres.py`
- Test: `backend/tests/test_cierres.py`

- [ ] **Step 1: Crear el módulo `kpis/cierres.py`**

```python
"""Lógica de cierre de caja: cálculo de saldo histórico y verificación de bloqueo."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.cierre_caja import CierreCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def saldo_caja_al(db: Session, caja: str, fecha: date) -> Decimal:
    """Saldo de una caja al CIERRE del día `fecha` (incluye ese día)."""
    fin = datetime.combine(fecha, time.max)

    ing_v1 = db.query(func.coalesce(func.sum(Venta.monto_pago1), 0)).filter(
        Venta.caja1 == caja, Venta.fecha <= fin
    ).scalar()
    ing_v2 = db.query(func.coalesce(func.sum(Venta.monto_pago2), 0)).filter(
        Venta.caja2 == caja, Venta.fecha <= fin
    ).scalar()
    ing_mov = db.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)).filter(
        MovimientoCaja.caja_destino == caja, MovimientoCaja.fecha <= fecha
    ).scalar()
    egr_mov = db.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)).filter(
        MovimientoCaja.caja_origen == caja, MovimientoCaja.fecha <= fecha
    ).scalar()

    return Decimal(str(ing_v1 or 0)) + Decimal(str(ing_v2 or 0)) \
        + Decimal(str(ing_mov or 0)) - Decimal(str(egr_mov or 0))


def fecha_ultimo_cierre(db: Session, caja: str) -> date | None:
    """Devuelve la fecha del último cierre para esa caja, o None si no hay."""
    res = db.query(func.max(CierreCaja.fecha)).filter(CierreCaja.caja == caja).scalar()
    return res


def caja_esta_bloqueada(db: Session, caja: str, fecha: date) -> bool:
    """Si hay un cierre cuya fecha >= `fecha` para esa caja, está bloqueada."""
    ult = fecha_ultimo_cierre(db, caja)
    return ult is not None and ult >= fecha


def cierres(db: Session, caja: str | None = None, limite: int = 100) -> list[dict[str, Any]]:
    q = db.query(CierreCaja).order_by(CierreCaja.fecha.desc(), CierreCaja.id.desc())
    if caja:
        q = q.filter(CierreCaja.caja == caja)
    return [
        {
            "id": c.id,
            "fecha": c.fecha.isoformat(),
            "caja": c.caja,
            "saldo_cierre": float(c.saldo_cierre),
            "observaciones": c.observaciones,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in q.limit(limite).all()
    ]
```

- [ ] **Step 2: Crear test**

`backend/tests/test_cierres.py`:

```python
"""Tests del módulo de cierre de caja."""
from datetime import date, datetime
from decimal import Decimal

from app.kpis.cierres import caja_esta_bloqueada, fecha_ultimo_cierre, saldo_caja_al
from app.models.caja import Caja
from app.models.cierre_caja import CierreCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def _setup(db):
    db.add(Caja(nombre_normalizado="cl", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.commit()


def test_saldo_caja_al_suma_ventas_y_movimientos(db):
    _setup(db)
    db.add(Venta(
        id_pedido="p1", id_venta="v1",
        fecha=datetime(2026, 4, 10, 12, 0),
        id_cliente=1, cliente="X", total=Decimal("1000"),
        monto_pago1=Decimal("1000"), caja1="cl",
    ))
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 12), tipo_operacion="Sueldo",
        monto=Decimal("300"), caja_origen="cl", hash_dedupe="h1",
    ))
    db.commit()

    assert saldo_caja_al(db, "cl", date(2026, 4, 15)) == Decimal("700")
    # Antes del egreso del 12: saldo es solo 1000
    assert saldo_caja_al(db, "cl", date(2026, 4, 11)) == Decimal("1000")


def test_caja_bloqueada_si_hay_cierre(db):
    _setup(db)
    db.add(CierreCaja(fecha=date(2026, 4, 30), caja="cl", saldo_cierre=Decimal("0")))
    db.commit()
    assert caja_esta_bloqueada(db, "cl", date(2026, 4, 15)) is True
    assert caja_esta_bloqueada(db, "cl", date(2026, 4, 30)) is True
    assert caja_esta_bloqueada(db, "cl", date(2026, 5, 1)) is False
    assert fecha_ultimo_cierre(db, "cl") == date(2026, 4, 30)
    assert fecha_ultimo_cierre(db, "otra") is None
```

- [ ] **Step 3: Correr tests**

```bash
cd "C:/Users/HP ENVY/Desktop/KPI/backend" && source .venv/Scripts/activate && pytest tests/test_cierres.py -v
```
Esperado: 2 passed.

- [ ] **Step 4: Suite completa**
```bash
pytest
```
Esperado: 60+ passed.

---

## Task 3: Endpoints de cierre

**Files:**
- Create: `backend/app/routers/cierres_router.py`
- Modify: `backend/app/main.py` (registrar router)

- [ ] **Step 1: Crear router**

`backend/app/routers/cierres_router.py`:

```python
"""Endpoints de cierre de caja."""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import cierres as kpi_cierres
from app.models.caja import Caja
from app.models.cierre_caja import CierreCaja
from app.routers._cache_helpers import invalida_alertas

router = APIRouter(prefix="/api/cierres", tags=["cierres"])


@router.get("")
def listar(
    caja: str | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return kpi_cierres.cierres(db, caja=caja, limite=limite)


@router.get("/saldo-actual")
def saldo_actual(
    caja: str = Query(..., description="nombre_normalizado de la caja"),
    fecha: date = Query(...),
    db: Session = Depends(get_db),
):
    """Calcula el saldo TEÓRICO al cierre de esa fecha. Útil para
    pre-llenar el form de cierre."""
    if db.get(Caja, caja) is None:
        raise HTTPException(404, f"Caja '{caja}' no existe")
    saldo = kpi_cierres.saldo_caja_al(db, caja, fecha)
    return {"caja": caja, "fecha": fecha.isoformat(), "saldo_calculado": float(saldo)}


class NuevoCierre(BaseModel):
    fecha: date
    caja: str
    saldo_cierre: float | None = None  # si None, usar el calculado
    observaciones: str | None = None


@router.post("")
@invalida_alertas
def cerrar(data: NuevoCierre, db: Session = Depends(get_db)):
    if db.get(Caja, data.caja) is None:
        raise HTTPException(404, f"Caja '{data.caja}' no existe")

    existente = db.query(CierreCaja).filter(
        CierreCaja.fecha == data.fecha, CierreCaja.caja == data.caja
    ).first()
    if existente is not None:
        raise HTTPException(
            409,
            f"Ya hay un cierre para {data.caja} en {data.fecha.isoformat()} "
            f"(saldo {existente.saldo_cierre}).",
        )

    saldo = (
        Decimal(str(data.saldo_cierre))
        if data.saldo_cierre is not None
        else kpi_cierres.saldo_caja_al(db, data.caja, data.fecha)
    )

    c = CierreCaja(
        fecha=data.fecha, caja=data.caja, saldo_cierre=saldo,
        observaciones=data.observaciones,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {
        "ok": True, "id": c.id,
        "saldo_cierre": float(c.saldo_cierre),
        "fecha": c.fecha.isoformat(),
    }


@router.delete("/{cierre_id}")
@invalida_alertas
def reabrir(cierre_id: int, db: Session = Depends(get_db)):
    """Borra el cierre — los movimientos vuelven a ser editables."""
    c = db.get(CierreCaja, cierre_id)
    if c is None:
        raise HTTPException(404, "Cierre no encontrado")
    db.delete(c)
    db.commit()
    return {"ok": True}
```

- [ ] **Step 2: Registrar router en `main.py`**

En `backend/app/main.py`, agregar al import de routers:
```python
from app.routers import alertas_router, caja_diaria_router, casos_revisar, cierres_router, conciliacion_router, configuracion, cuentas_corrientes_router, dashboard, import_router, kpis_caja, kpis_comerciales, ventas_router, admin_router
```

(Si tu línea ya tenía esos, solo agregá `cierres_router` en orden alfabético.)

Y abajo, junto con los otros include_router, agregar:
```python
app.include_router(cierres_router.router)
```

- [ ] **Step 3: Smoke test**

```bash
tasklist 2>/dev/null | grep -iE "uvicorn" | awk '{print $2}' | while read pid; do taskkill //PID $pid //F 2>&1; done; sleep 1
```

Reiniciar backend (en otra terminal o background):
```bash
cd "C:/Users/HP ENVY/Desktop/KPI/backend" && source .venv/Scripts/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000 &
sleep 3
curl -s "http://127.0.0.1:8000/api/cierres" | head -c 200
echo
curl -s "http://127.0.0.1:8000/api/cierres/saldo-actual?caja=cajalocal&fecha=2026-04-30" | head -c 200
```

Esperado: el primero `[]`, el segundo un JSON con saldo calculado.

---

## Task 4: Bloqueo en `editar_movimiento` y `eliminar_movimiento`

**Files:**
- Modify: `backend/app/routers/caja_diaria_router.py`
- Test: `backend/tests/test_caja_diaria.py`

- [ ] **Step 1: Agregar helper de chequeo en `caja_diaria_router.py`**

Agregar import al tope:
```python
from app.kpis.cierres import caja_esta_bloqueada
```

Crear helper interno (puede ir antes de `crear_movimiento`):
```python
def _verificar_no_bloqueado(db, m):
    """Si el movimiento toca una caja con cierre que cubre su fecha, raisea 403."""
    for caja in (m.caja_origen, m.caja_destino):
        if caja and caja_esta_bloqueada(db, caja, m.fecha):
            raise HTTPException(
                403,
                f"La caja '{caja}' está cerrada hasta una fecha posterior a la "
                f"del movimiento ({m.fecha.isoformat()}). Reabrí el cierre desde "
                "Cierres si necesitás editar movimientos viejos."
            )
```

- [ ] **Step 2: Llamar el helper en `editar_movimiento` y `eliminar_movimiento`**

En `eliminar_movimiento`, después de obtener `m` y verificar que existe, agregar:
```python
    _verificar_no_bloqueado(db, m)
```

En `editar_movimiento`, hacer lo mismo (después de validar que existe). Idealmente verificar tanto el movimiento original como el nuevo (por si la fecha cambia para entrar en período cerrado):

```python
    _verificar_no_bloqueado(db, m)  # antes de modificar — fecha actual
    # ... aplicar cambios ...
    _verificar_no_bloqueado(db, m)  # después — la nueva fecha también
```

(Hacé el segundo chequeo después de que `data.fecha`/`data.caja_*` ya están aplicados a `m`, antes del `db.flush()`.)

- [ ] **Step 3: Agregar tests**

Al final de `backend/tests/test_caja_diaria.py`:

```python
from datetime import date as _date

from app.models.cierre_caja import CierreCaja
from app.routers.caja_diaria_router import EditarMovimiento, editar_movimiento, eliminar_movimiento


def test_editar_movimiento_en_caja_cerrada_devuelve_403(db):
    _setup_basico(db)
    db.add(MovimientoCaja(
        fecha=_date(2026, 4, 1), tipo_operacion="Sueldo", detalle="x",
        monto=Decimal("100"), caja_origen="cajalocal", hash_dedupe="hX",
    ))
    db.add(CierreCaja(fecha=_date(2026, 4, 30), caja="cajalocal", saldo_cierre=Decimal("0")))
    db.commit()
    m = db.query(MovimientoCaja).first()

    with pytest.raises(HTTPException) as exc_info:
        editar_movimiento(m.id, EditarMovimiento(detalle="otro"), db)
    assert exc_info.value.status_code == 403
    assert "cerrada" in exc_info.value.detail.lower()


def test_eliminar_movimiento_en_caja_cerrada_devuelve_403(db):
    _setup_basico(db)
    db.add(MovimientoCaja(
        fecha=_date(2026, 4, 1), tipo_operacion="Sueldo", detalle="x",
        monto=Decimal("100"), caja_origen="cajalocal", hash_dedupe="hY",
    ))
    db.add(CierreCaja(fecha=_date(2026, 4, 30), caja="cajalocal", saldo_cierre=Decimal("0")))
    db.commit()
    m = db.query(MovimientoCaja).first()

    with pytest.raises(HTTPException) as exc_info:
        eliminar_movimiento(m.id, db)
    assert exc_info.value.status_code == 403


def test_movimiento_posterior_al_cierre_se_puede_editar(db):
    _setup_basico(db)
    db.add(MovimientoCaja(
        fecha=_date(2026, 5, 5), tipo_operacion="Sueldo", detalle="ok",
        monto=Decimal("100"), caja_origen="cajalocal", hash_dedupe="hZ",
    ))
    db.add(CierreCaja(fecha=_date(2026, 4, 30), caja="cajalocal", saldo_cierre=Decimal("0")))
    db.commit()
    m = db.query(MovimientoCaja).first()

    res = editar_movimiento(m.id, EditarMovimiento(detalle="cambiado"), db)
    assert res["ok"] is True
```

- [ ] **Step 4: Correr tests**
```bash
pytest tests/test_caja_diaria.py -v
```
Esperado: todos passed (incluye 3 nuevos).

- [ ] **Step 5: Suite completa**
```bash
pytest
```

---

## Task 5: Frontend — botón "Cerrar día" en CajaDiaria

**Files:**
- Modify: `frontend/src/pages/CajaDiaria.jsx`

Agregar un panel arriba de los Saldos en vivo o como tab nuevo: "Cerrar día / Cierres".

- [ ] **Step 1: Componente `CerrarDiaPanel`**

Al final de `CajaDiaria.jsx` (antes del último `}` de export), agregar un componente nuevo:

```jsx
function CerrarDiaPanel({ cajas, onCerrado }) {
  const confirmar = useConfirm();
  const toast = useToast();
  const [caja, setCaja] = useState("");
  const [fecha, setFecha] = useState(new Date().toISOString().slice(0, 10));
  const [saldoCalc, setSaldoCalc] = useState(null);
  const [observaciones, setObservaciones] = useState("");
  const [busy, setBusy] = useState(false);

  async function calcularSaldo() {
    if (!caja || !fecha) return;
    const cajaNorm = cajas.find((c) => c.nombre_display === caja || c.nombre_normalizado === caja)?.nombre_normalizado || caja;
    const { data } = await api.get("/api/cierres/saldo-actual", { params: { caja: cajaNorm, fecha } });
    setSaldoCalc(data.saldo_calculado);
  }

  async function cerrar() {
    if (!caja || !fecha) {
      toast.push("Elegí caja y fecha", "error");
      return;
    }
    const ok = await confirmar({
      titulo: "Cerrar día",
      mensaje: `Vas a cerrar la caja "${caja}" al ${fecha} con saldo ${saldoCalc != null ? "$" + saldoCalc.toLocaleString("es-AR") : "(calculado)"}.\n\nDespués del cierre los movimientos de ese día y anteriores en esta caja NO se podrán editar ni borrar.`,
      labelOk: "Cerrar día",
    });
    if (!ok) return;
    setBusy(true);
    try {
      const cajaNorm = cajas.find((c) => c.nombre_display === caja)?.nombre_normalizado || caja;
      await api.post("/api/cierres", {
        fecha, caja: cajaNorm,
        saldo_cierre: saldoCalc,
        observaciones: observaciones || null,
      });
      toast.push("Día cerrado correctamente", "success");
      setObservaciones("");
      setSaldoCalc(null);
      onCerrado?.();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error al cerrar", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h3>Cerrar día</h3>
      <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 12 }}>
        Snapshotea el saldo del día y bloquea ediciones de ese día (y anteriores) en la caja seleccionada.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 10, alignItems: "end" }}>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Caja</label>
          <select value={caja} onChange={(e) => { setCaja(e.target.value); setSaldoCalc(null); }} style={{ width: "100%" }}>
            <option value="">— elegí —</option>
            {cajas.map((c) => <option key={c.nombre_normalizado} value={c.nombre_display}>{c.nombre_display}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Fecha</label>
          <input type="date" value={fecha} onChange={(e) => { setFecha(e.target.value); setSaldoCalc(null); }} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Saldo calculado</label>
          <div style={{ padding: "6px 10px", background: "#0f172a", border: "1px solid #334155", borderRadius: 6, color: saldoCalc != null ? "#34d399" : "#64748b" }}>
            {saldoCalc != null ? `$${saldoCalc.toLocaleString("es-AR")}` : "—"}
          </div>
        </div>
        <button className="btn-ghost btn" onClick={calcularSaldo} disabled={!caja || !fecha}>Calcular</button>
      </div>
      <div style={{ marginTop: 10 }}>
        <label style={{ fontSize: 11, color: "#94a3b8" }}>Observaciones</label>
        <input value={observaciones} onChange={(e) => setObservaciones(e.target.value)} placeholder="opcional..." style={{ width: "100%" }} />
      </div>
      <div style={{ marginTop: 12 }}>
        <button className="btn" disabled={busy || !caja || !fecha} onClick={cerrar}>
          {busy ? <span className="spinner" /> : "Cerrar día"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Componente `CierresHistorial`**

Después del componente anterior, agregar:

```jsx
function CierresHistorial({ recargar }) {
  const confirmar = useConfirm();
  const toast = useToast();
  const [cierres, setCierres] = useState([]);

  async function cargar() {
    const { data } = await api.get("/api/cierres", { params: { limite: 30 } });
    setCierres(data);
  }
  useEffect(() => { cargar(); }, [recargar]);

  async function reabrir(c) {
    const ok = await confirmar({
      titulo: "Reabrir cierre",
      mensaje: `Caja "${c.caja}" del ${c.fecha}.\n\nSe eliminará el cierre y los movimientos de ese día y anteriores volverán a ser editables.`,
      labelOk: "Reabrir",
      peligroso: true,
    });
    if (!ok) return;
    await api.delete(`/api/cierres/${c.id}`);
    toast.push("Cierre reabierto", "info");
    cargar();
  }

  return (
    <div className="panel">
      <h3>Cierres recientes</h3>
      {cierres.length === 0 && <div className="empty">No hay cierres todavía.</div>}
      {cierres.length > 0 && (
        <table>
          <thead><tr><th>Fecha</th><th>Caja</th><th className="num">Saldo cierre</th><th>Observaciones</th><th></th></tr></thead>
          <tbody>
            {cierres.map((c) => (
              <tr key={c.id}>
                <td>{c.fecha}</td>
                <td>{c.caja}</td>
                <td className="num">{fmtMoney(c.saldo_cierre)}</td>
                <td style={{ color: "#94a3b8", fontSize: 12 }}>{c.observaciones || "-"}</td>
                <td><button className="btn-ghost btn btn-danger" onClick={() => reabrir(c)}>Reabrir</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Mostrar los componentes en CajaDiaria**

En el JSX principal de `CajaDiaria` (antes del `<div className="panel"><h3>Movimientos recientes</h3>...`), agregar:

```jsx
      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 20, marginBottom: 20 }}>
        <CerrarDiaPanel cajas={sugerencias.cajas} onCerrado={cargarTodo} />
        <CierresHistorial recargar={recientes.length} />
      </div>
```

(El prop `recargar={recientes.length}` es un truco para que se refresque cuando cambia el feed.)

- [ ] **Step 4: Smoke test**

Recargá http://localhost:5173/caja-diaria. Tienen que aparecer 2 paneles nuevos: "Cerrar día" y "Cierres recientes".

Probá:
1. Elegí caja "CAJA LOCAL" y fecha (ej. ayer). Click "Calcular" → muestra saldo.
2. Click "Cerrar día" → modal de confirmación → si confirmás, aparece toast "Día cerrado".
3. El cierre aparece en "Cierres recientes".
4. Andá a un movimiento de fecha cubierta por el cierre → editar → debería dar 403.
5. Click "Reabrir" en el cierre → vuelve a poder editar.

NO commit.

---

## Resumen

| Task | Foco | Tiempo | Tests añadidos |
|------|------|--------|---------------:|
| 1 | Modelo + migración | 10 min | — |
| 2 | KPI helpers + tests | 15 min | +2 |
| 3 | 4 endpoints | 15 min | smoke |
| 4 | Bloqueo + 3 tests | 20 min | +3 |
| 5 | UI panel cerrar + historial | 25 min | manual |

Total ~85 min. Después de esto, **podés cerrar el día y los movimientos de fechas cerradas son inmutables**. Es la base de confiabilidad para reportes mensuales y arqueos.
