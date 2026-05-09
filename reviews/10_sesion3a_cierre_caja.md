# Review — Sesión 3A: Cierre de caja

## Resumen
3 críticos / 5 importantes / 6 menores

---

## Strengths

- **Modelo limpio y conciso** (`app/models/cierre_caja.py`): `UniqueConstraint("fecha","caja")` previene duplicados a nivel DB; FK a `cajas.nombre_normalizado` mantiene integridad referencial. Buena docstring que explica la semántica.
- **Snapshot opcional vs calculado**: el endpoint `POST /api/cierres` permite tanto pasar `saldo_cierre` explícito como dejar que se calcule (`kpi_cierres.saldo_caja_al`). Buena flexibilidad.
- **Doble verificación en `editar_movimiento`** (`caja_diaria_router.py:157` y `:188`): se valida estado actual y estado nuevo, lo que previene "mover" un movimiento desde una fecha cerrada hacia otra (o viceversa). Esto es correcto y muestra atención al detalle.
- **Validación `404` de caja inexistente** en `POST /api/cierres` (`cierres_router.py:52`) y en `GET /api/cierres/saldo-actual` (`cierres_router.py:36`).
- **Test de no-regresión** (`test_caja_diaria.py:80` `test_movimiento_posterior_al_cierre_se_puede_editar`): valida explícitamente que movimientos posteriores al cierre siguen siendo editables. Bien pensado.
- **UI con confirm dialogs** y mensajes claros sobre el efecto de cerrar/reabrir.

---

## Critical

### C1 — `saldo_caja_al` mezcla `datetime` y `date` en filtros: la suma de ventas usa `<= datetime(fecha 23:59:59.999999)` pero los movimientos usan `<= fecha` (date)

**Archivo**: `app/kpis/cierres.py:17-30`

**Bug**: La función calcula `fin = datetime.combine(fecha, time.max)` y lo usa para filtrar `Venta.fecha <= fin` (correcto, porque `Venta.fecha` es `DateTime`). Pero en los `MovimientoCaja` filtra `MovimientoCaja.fecha <= fecha` pasando un `date`. Esto resulta inconsistente *si* en algún momento `MovimientoCaja.fecha` se cambia a `DateTime`, o si dos código-paths leen el modelo distinto. Más importante: **cuando se calcula el "saldo del día N", incluye movimientos del día N (date `<=` date funciona inclusive), pero la lógica conceptual queda fragmentada y susceptible a bugs futuros**.

Más crítico aún: la docstring dice "Saldo … al CIERRE del día (incluye ese día)" — funciona hoy porque `MovimientoCaja.fecha` es `Date`. Pero **ese contrato no está testeado para la frontera exacta del día**: ningún test cubre un movimiento cuya `fecha == fecha_cierre`. El test actual (`test_cierres.py:31`) usa `date(2026, 4, 15)` y movs en `4, 12` — no toca el borde.

**Reproducción**: imaginemos que mañana alguien migra `MovimientoCaja.fecha` a `DateTime` (por ejemplo para soportar hora del cobro). Las consultas con `fecha <= date(2026,4,12)` ahora excluirán todo lo que pasó en `2026-04-12` (porque `datetime(2026,4,12,X,Y) > date(2026,4,12)` por coerción). Esto silenciosamente **subestimaría el saldo de cierre**.

**Fix**:
```python
def saldo_caja_al(db: Session, caja: str, fecha: date) -> Decimal:
    fin_dt = datetime.combine(fecha, time.max)
    # Aplicar el mismo "fin de día" a ambos modelos para inmunidad ante refactors.
    ing_v1 = ...filter(Venta.fecha <= fin_dt)
    ing_mov = ...filter(MovimientoCaja.fecha <= fecha)  # OK por ahora
    # ...
```
y agregar test:
```python
def test_saldo_incluye_movimientos_del_dia_de_cierre(db):
    # Mov con fecha == fecha_cierre debe contar
```

Sobre el comentario en el foco: `time.max` es `23:59:59.999999`. **No es seguro contra zonas horarias** porque `Venta.fecha` se guarda como UTC naive (no hay tzinfo en el modelo). Si algún día se introduce tz-aware, esta comparación va a romper. Pero hoy es consistente con el resto del codebase (`kpis/caja.py:22`, `kpis/comerciales.py:20`).

---

### C2 — `DELETE /api/cierres/{id}` no valida cierres POSTERIORES en cascada: deja agujero de bloqueo

**Archivo**: `app/routers/cierres_router.py:85-93`

**Bug**: `caja_esta_bloqueada` (`kpis/cierres.py:42-45`) usa `fecha_ultimo_cierre` (que es `MAX(fecha)` para esa caja). Si una caja tiene cierres en `2026-04-30`, `2026-05-15` y `2026-05-31`, y reabro el del **30 de abril**, el bloqueo se mantiene porque el último cierre sigue siendo `2026-05-31`. **Resultado**: el usuario reabre creyendo que puede editar movimientos de abril, pero sigue bloqueado. Mensaje confuso al editar.

Inversamente: si reabre el del **31 de mayo** (el último), ahora `fecha_ultimo_cierre` baja al `2026-05-15`, lo que **deja editables movimientos del 16-31 de mayo aunque haya un cierre intermedio en mayo 15**. Eso *parece* correcto pero el snapshot del cierre del 30/abr y el del 15/may **ya quedaron desactualizados** porque no contemplaban ediciones futuras (ver C3).

**Reproducción** (caso 1, bloqueo fantasma):
1. Crear cierres caja `cl` en `2026-04-30` y `2026-05-31`.
2. `DELETE /api/cierres/{id_de_30_abr}` → responde `{"ok": true}`.
3. `PATCH /api/caja-diaria/movimiento/{m_de_abril}` → `403 Caja cerrada hasta una fecha posterior`. Pero no hay cierre en abril.

**Reproducción** (caso 2, cascada inconsistente):
1. Cierres en `2026-04-30` (saldo=1000) y `2026-05-31` (saldo=2000).
2. `DELETE` el del 31/mayo. Editar un movimiento de mayo (cambio monto).
3. El cierre del 30/abr no cambió (correcto), pero ahora el "saldo real" de la caja al 31/mayo no coincide con ningún snapshot. Si después se vuelve a cerrar el 31/mayo, el snapshot que se calcule será diferente al original — sin auditoría.

**Fix sugerido**: rechazar reabrir cuando hay cierres posteriores **o** reabrirlos en cascada con confirmación explícita:

```python
@router.delete("/{cierre_id}")
def reabrir(cierre_id: int, cascada: bool = Query(False), db: Session = Depends(get_db)):
    c = db.get(CierreCaja, cierre_id)
    if c is None:
        raise HTTPException(404, "Cierre no encontrado")
    posteriores = db.query(CierreCaja).filter(
        CierreCaja.caja == c.caja,
        CierreCaja.fecha > c.fecha,
    ).count()
    if posteriores > 0 and not cascada:
        raise HTTPException(409,
            f"Hay {posteriores} cierre(s) posteriores en '{c.caja}'. "
            f"Reabrí esos primero, o usá ?cascada=true para borrarlos todos.")
    if cascada:
        db.query(CierreCaja).filter(
            CierreCaja.caja == c.caja, CierreCaja.fecha >= c.fecha
        ).delete()
    else:
        db.delete(c)
    db.commit()
    return {"ok": True}
```

---

### C3 — Snapshot vs realidad: no hay forma de detectar inconsistencias después de un reabrir+editar

**Archivos**: `app/models/cierre_caja.py`, `app/kpis/cierres.py`, `app/routers/cierres_router.py`

**Bug**: El `saldo_cierre` se snapshotea al momento del cierre. Si el usuario después reabre, edita movimientos viejos, y vuelve a cerrar (o no), el snapshot anterior y la realidad **divergen silenciosamente**. No hay:

- Campo `saldo_cierre_recalculado` o `obsoleto: bool` en `CierreCaja` para marcar este caso.
- Endpoint `/api/cierres/{id}/verificar` que recalcule y compare.
- Log/auditoría de quién/cuándo se reabrió.

**Reproducción**:
1. Cierre `2026-04-30` con `saldo_cierre=1000`.
2. Reabrir → editar mov del `2026-04-15` (monto 100 → 500) → cerrar de nuevo `2026-04-30` con saldo recalculado `1400`. **Histórico se pisa**, no queda rastro del 1000 original.

Esto es un problema de **integridad contable**: cierres son típicamente inmutables o auditables. El diseño actual los trata como mutables sin huella.

**Fix mínimo** (no rompe nada, sólo agrega visibilidad):

1. Agregar columna `saldo_recalculado` y endpoint `GET /api/cierres/{id}/diff` que devuelve `(saldo_cierre, saldo_caja_al(...))`. Si difieren, el frontend muestra warning rojo en el historial.
2. Agregar logging (no `print`, sino logger estructurado) cuando se reabre un cierre.
3. Considerar columnas `created_at_user` y `reopened_at_log` (jsonb) en sesiones futuras.

---

## Important

### I1 — `_verificar_no_bloqueado` con transferencias: si UNA caja está cerrada, bloquea TODO el movimiento, sin opción de editar sólo la otra punta

**Archivo**: `app/routers/caja_diaria_router.py:30-39`

**Comportamiento actual**: si un movimiento es transferencia `caja_origen=cl_cerrada → caja_destino=cl_abierta`, **se bloquea el edit completo** (correcto desde el punto de vista contable: no podés mover plata de una caja cerrada).

**Bug sutil**: el chequeo se hace sobre el `m` actual (post-edit en el segundo `_verificar_no_bloqueado`), pero **no se chequea el `m` ORIGINAL antes del cambio** si el usuario cambia `caja_origen` de "cerrada" a "abierta". Es decir: un movimiento cuyo origen original era una caja cerrada, no debería ser editable para "sacar" plata de esa caja sin reabrirla. El primer `_verificar_no_bloqueado(db, m)` en `caja_diaria_router.py:157` corre **antes** de aplicar cambios — bien — y atrapa este caso. ✓

Pero el segundo (`:188`) corre **después** de re-asignar `caja_origen`. Si el usuario cambia origen `cl_cerrada → cl_abierta`, el primer check ya bloqueó. ✓ OK realmente.

**Caso real problemático**: `caja_origen=None, caja_destino=cl_cerrada` (un ingreso a caja cerrada): el código bloquea (correcto). Pero si el usuario quiere **agregar** un movimiento `caja_destino=cl_abierta` con misma fecha que el cierre... no es un edit, es un POST nuevo. **El POST `/api/caja-diaria/movimiento` NO llama `_verificar_no_bloqueado`** (`caja_diaria_router.py:52-118`).

**Reproducción**:
1. Crear cierre en `cl` para `2026-04-30`.
2. `POST /api/caja-diaria/movimiento` con `fecha=2026-04-15, caja_destino=cl, monto=100`.
3. Devuelve `200 OK`. **Bug crítico**: acabas de meter un movimiento en una caja cerrada, lo que **invalida el snapshot del cierre**.

Esto debería ser un bloqueo `403`. Promoción a Critical en realidad — lo dejo como Important porque es razonablemente fácil de arreglar:

**Fix**:
```python
@router.post("/movimiento")
def crear_movimiento(...):
    # ... después de resolver origen_norm/destino_norm:
    fake_m = type("M", (), {"fecha": fecha, "caja_origen": origen_norm, "caja_destino": destino_norm})()
    _verificar_no_bloqueado(db, fake_m)
    # o mejor: extraer la lógica a helper que reciba (caja, fecha) sin requerir m.
```

### I2 — `_verificar_no_bloqueado` se ejecuta sobre el modelo `m` tras `flush` parcial pero ANTES de `commit`: rollback inconsistente

**Archivo**: `app/routers/caja_diaria_router.py:188-220`

Si el segundo `_verificar_no_bloqueado` levanta `403`, los cambios al `m` **ya están en la sesión** (modificaste atributos de Python directamente). FastAPI captura la `HTTPException`, pero **el `db` queda con cambios pendientes que no se commiteean**. Si en otro endpoint posterior dentro de la misma sesión se hace commit, podría persistir los cambios indebidos.

En la práctica, `Depends(get_db)` da una sesión por request y se descarta al final, así que el riesgo concreto es bajo. Pero **conceptualmente** debería hacer `db.rollback()` antes de re-raisear.

**Fix**:
```python
try:
    _verificar_no_bloqueado(db, m)
except HTTPException:
    db.rollback()
    raise
```

### I3 — Tests faltantes para edge cases del bloqueo de transferencias

`test_caja_diaria.py` cubre los casos básicos pero no:
- Transferencia entre dos cajas, una cerrada y otra no.
- Editar `fecha` de un movimiento para "moverlo" desde fecha abierta a cerrada (debería bloquear).
- Editar `caja_origen` para "moverlo" hacia/desde caja cerrada.
- POST nuevo movimiento en caja cerrada (ver I1, no se testea ni se valida).

### I4 — `GET /api/cierres/saldo-actual` no valida fechas futuras o muy antiguas

**Archivo**: `app/routers/cierres_router.py:28-39`

Se acepta cualquier `date`, incluso `2099-12-31` o `1900-01-01`. El cálculo va a devolver el saldo actual (porque no hay movs con esas fechas). No es bug serio, pero sería razonable rechazar fechas futuras (`fecha > date.today()`) con `400`.

### I5 — `CierreCaja.created_at` usa `datetime.utcnow` (deprecated en Python 3.12+) y no se setea con `func.now()` en DB

**Archivo**: `app/models/cierre_caja.py:28`

`datetime.utcnow` está deprecated en Python 3.12. Mejor usar `datetime.now(timezone.utc)` o, idealmente, `server_default=func.now()` para que la DB ponga el timestamp y se use el reloj del servidor (consistente entre apps). El resto del codebase ya tiene este mismo patrón en otros modelos (`venta.py:45`), así que es deuda existente, no nueva.

---

## Minor

### M1 — Frontend `CerrarDiaPanel.cerrar()` (`CajaDiaria.jsx:596`) sólo busca por `nombre_display`, no por `nombre_normalizado`

```js
const cajaNorm = cajas.find((c) => c.nombre_display === caja)?.nombre_normalizado || caja;
```

vs. `calcularSaldo` (`:578`) que sí busca por ambos:
```js
const cajaNorm = cajas.find((c) => c.nombre_display === caja || c.nombre_normalizado === caja)?.nombre_normalizado || caja;
```

Es inconsistente. En `cerrar()` el `caja` viene del `<select value={caja}>` (`:622`) cuyas opciones tienen `value={c.nombre_display}`, así que en práctica funciona — pero si en algún refactor cambias el `<select>` para usar `nombre_normalizado`, se rompe silenciosamente. **Unificá ambos lookups** (extraer a un helper `displayANormalizado(cajas, valor)`).

Sobre la pregunta del foco "edge case donde nombre_display sea ambiguo": teóricamente sí. El backend no fuerza unicidad de `nombre_display` (sólo `nombre_normalizado` es PK). Si dos cajas tienen mismo display (ej. "Caja Local" y "CAJA LOCAL " con espacio) y normalizan igual… el `find` devuelve la primera. Es muy improbable pero no está blindado.

### M2 — `CierresHistorial` (`CajaDiaria.jsx:652-698`) no muestra warning si el cierre tiene `posteriores`

Ligado a C2: el frontend no advierte al usuario antes de reabrir un cierre con cierres posteriores. Mejor mostrar badge "tiene cierres posteriores" o desactivar el botón.

### M3 — `CierresHistorial.recargar={recientes.length}` (`CajaDiaria.jsx:82`) es fragil

Usa `recientes.length` como key para recargar el historial cuando se crea un movimiento. Pero si se crea uno y se borra otro, `length` queda igual y el historial no se recarga aunque algo cambió. Mejor pasar un callback o un counter monotónico (ej. `setReloadKey(k => k + 1)`).

### M4 — `cierres()` (`kpis/cierres.py:48-62`) hardcodea formatos en el dict pero podría usar `JSONResponse` model

Mejor que la función devuelva objetos del ORM o un dataclass, y serialices en el router. Acopla la lógica con el formato de transporte. Cosmético.

### M5 — `saldo_caja_al` recorre 4 queries separadas; podría ser 1 con `union_all` o subquery

Performance es ok porque las cajas filtradas tienen pocos rows, pero si esto se llama desde un loop (ej. saldo de todas las cajas a una fecha) sería N×4 queries. No es el caso hoy, pero vale la pena como nota futura.

### M6 — `NuevoCierre.saldo_cierre: float | None` permite `0` válido pero el branching `if data.saldo_cierre is not None` es correcto

Está bien, pero podría documentarse que `saldo_cierre=0` es distinto de `saldo_cierre=None` (uno fuerza el snapshot a 0, el otro lo calcula). Hoy no hay docstring del modelo Pydantic.

---

## Tests faltantes

1. **C1**: `saldo_caja_al` con movimiento cuya `fecha == fecha_cierre`. Validar que cuenta.
2. **C2**: reabrir cierre antiguo cuando hay cierres posteriores → debería fallar (después del fix) o al menos test que documenta el comportamiento actual.
3. **C3**: snapshot vs realidad — crear cierre con `saldo=1000`, editar movs viejos (vía reabrir), recerrar, verificar que el snapshot original no se pisa silenciosamente.
4. **I1**: `POST /api/caja-diaria/movimiento` con caja cerrada → debería ser `403`. Hoy es `200`.
5. **I3**: edit que cambia `fecha` desde abierta → cerrada (bloquear). Edit que cambia `caja_origen` cerrada → abierta (bloquear primer check).
6. **Transferencia entre dos cajas** (origen cerrada, destino abierta): debería bloquear.
7. **`/api/cierres/saldo-actual`** con caja inexistente → `404`. Sin caja (param requerido) → `422`.
8. **Concurrencia**: dos `POST /api/cierres` simultáneos misma fecha+caja → uno gana, otro `409`. Idealmente test con threading o pytest-asyncio.
9. **Endpoint `DELETE /api/cierres/{id}`** con id inexistente → `404`. Falta test directo.
10. **Frontend (`CerrarDiaPanel`)**: caja `nombre_display` con tildes/mayúsculas/espacios; verificar que el lookup encuentra y manda `nombre_normalizado` correcto.

---

## Recomendaciones específicas

1. **Bloquear `POST /api/caja-diaria/movimiento` en caja cerrada** (I1). Es el agujero más serio: hoy se pueden crear movimientos retroactivos en cajas cerradas, invalidando snapshots. Fix de 5 líneas.

2. **Validar reabrir con cierres posteriores** (C2). Implementar el patrón con `?cascada=true` o rechazar con `409`. Mostrar en el frontend qué cierres se afectarían.

3. **Agregar auditoría mínima a `CierreCaja`**:
   - `reabierto_en: datetime | None` (si NULL, está vigente; si tiene valor, fue reabierto y es histórico).
   - O bien: tabla `cierre_caja_log` con eventos `created/reopened` y timestamps.
   - Logger estructurado en `reabrir()`: `logger.warning("Cierre reabierto", extra={"id": id, "fecha": ..., "caja": ...})`.

4. **Extraer helper `_es_caja_fecha_bloqueada(db, caja, fecha)`** para usarlo desde POST y desde `_verificar_no_bloqueado` (DRY). Hoy `_verificar_no_bloqueado` requiere un `m` con atributos, lo que dificulta llamarlo desde el POST sin armar un objeto fake.

5. **Unificar lookup display↔normalizado en frontend** (M1) y exponer un helper en `api/client.js`:
   ```js
   export function cajaToNormalizado(cajas, valor) {
     return cajas.find(c => c.nombre_display === valor || c.nombre_normalizado === valor)?.nombre_normalizado || valor;
   }
   ```

6. **Documentar en `cierre_caja.py` la semántica del snapshot**: que es informativo y NO se recalcula automáticamente; que la integridad contable depende de no reabrir+editar sin recerrar; y que `caja_esta_bloqueada` mira `MAX(fecha)` (no la presencia de un cierre exacto).

7. **Considerar agregar `db.rollback()`** en el `_verificar_no_bloqueado` post-edición (I2) por defensividad, aunque hoy no causa bugs visibles.

8. **Sesión futura**: tabla `cierre_caja_diff` o columna calculada que en un cron diario verifique `saldo_cierre` vs `saldo_caja_al(fecha)` y marque desviaciones — daría auditoría barata sin reescribir nada.
