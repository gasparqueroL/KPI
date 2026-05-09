# Tablero de KPIs

Webapp para calcular y visualizar KPIs de la empresa a partir de exports CSV (ventas, detalle de ventas y movimientos de caja).

## Stack

- **Backend**: Python 3.13 + FastAPI + SQLAlchemy + SQLite
- **Frontend**: React + Vite + Recharts
- **Datos**: importación de CSV vía UI, persistencia en SQLite

## Estructura

```
KPI/
├── backend/         # API FastAPI
├── frontend/        # UI React
└── data sources/    # CSVs originales (no versionados)
```

## Cómo correr en desarrollo

### Backend

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate    # Windows bash / Git Bash
# .venv\Scripts\activate         # Windows cmd/powershell
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API en http://localhost:8000 — docs interactivos en http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

UI en http://localhost:5173

## Reglas clave del modelo

- Las **cajas** (formas de pago) son entidades centrales: cada venta entra a 1 o 2 cajas, los movimientos pueden mover plata entre cajas.
- **Solo entra al sistema lo válido**: filas inconsistentes van a la pestaña "Casos a revisar".
- Los totales de `ventas` y la suma de `detalle_ventas` **NO siempre coinciden** (redondeo, devoluciones, cuentas corrientes) — ver documentación interna.

## Migraciones de schema (Alembic)

Cuando cambies un modelo (agregar columna, cambiar tipo, agregar tabla), **NO borres la BD**. Generá una migración:

```bash
cd backend && source .venv/Scripts/activate

# 1. Generar migración auto-detectada desde los modelos
alembic revision --autogenerate -m "descripcion_corta_del_cambio"

# 2. Revisar el archivo generado en backend/alembic/versions/

# 3. Aplicar a la BD (preserva datos)
alembic upgrade head

# Otros comandos útiles:
alembic current              # qué versión está aplicada
alembic history              # histórico de migraciones
alembic downgrade -1         # revertir última migración
```

Si traés una BD existente sin Alembic configurado, marcala como "ya está al día":
```bash
alembic stamp head
```

## Tests

```bash
cd backend && source .venv/Scripts/activate && pytest
```

## Estado de los KPIs

Tests: `cd backend && source .venv/Scripts/activate && pytest`

Todos los tests pasando garantiza que:
- `parse_monto` distingue decimal de separador de miles
- `_filtro_fecha` incluye correctamente el día tope
- Cuentas corrientes no duplica clientes con typos
- Re-import de detalle_ventas es idempotente con cualquier orden
- Edición de movimiento detecta colisiones de hash
- Una fila inválida en import no revierte las anteriores aceptadas
- Cache de alertas se invalida tras toda mutación
- Seed de categorías respeta ediciones manuales
- Cierre de caja bloquea ediciones de movimientos previos
- Pagos parciales se aplican correctamente venta-por-venta
- CSV exports están protegidos contra inyección de fórmulas Excel
- Auth por API key opcional via env var KPI_API_KEY

## Hardening de seguridad

Por defecto el backend asume **uso localhost** (sin auth). Para exponerlo en LAN o más allá:

1. Bindear explícito a una interfaz: `uvicorn app.main:app --host 192.168.X.X` (o `0.0.0.0` con auth obligatoria).
2. Configurar API key via env var:
   ```bash
   export KPI_API_KEY="una-clave-larga-y-aleatoria"
   ```
   Cuando está seteada, todo cliente debe enviar header `X-API-Key: <valor>`. El frontend se puede modificar para enviarlo automáticamente.
3. Verificar status: `curl http://localhost:8000/api/admin/auth-status`
