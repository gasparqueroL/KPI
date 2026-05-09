# Review — Funcionalidad

## Resumen ejecutivo

La app cubre razonablemente bien el "frente comercial + caja descriptiva": permite importar CSVs, ver ventas y márgenes, vigilar saldos por caja, hacer cuentas corrientes con extracto running, conciliar facturado vs cobrado, marcar cobros verificados y cargar movimientos a mano. Eso ya es más de lo que muchas planillas tienen.

Pero como reemplazo integral de una planilla de finanzas, **todavía es media app**. Le faltan tres cosas estructurales que en una empresa real son no-negociables:

1. **Cierre de caja diario y mensual con bloqueo** — hoy todo es editable retroactivamente, no hay "saldo cerrado al 30/04" que sirva como punto de verdad para arrancar mayo.
2. **Compras / proveedores y cuentas a pagar** — solo hay egresos sueltos como movimientos de caja; no hay obligación pendiente, vencimientos, ni quién debo pagar mañana.
3. **Stock e impuestos** — sin inventario es imposible controlar el costo real, y sin tratamiento de IVA / percepciones no sirve para conciliar con el contador.

Una empresa que mueve 14k ventas/año y 1.2k movimientos/año en 148 cajas con 4360 clientes necesita las tres. Sin ellas, sigue trabajando en la planilla en paralelo para esos pedazos. Mi estimación: **cubre ~45-55% de lo que la planilla hace**, principalmente la parte descriptiva ("qué pasó") y bastante poco de la parte operativa ("qué tengo que hacer hoy y a qué fecha cierro").

---

## Lo que está cubierto

- Import de CSVs (ventas, detalle de ventas, movimientos de caja) con dedupe por hash y panel de "Casos a revisar" para filas inválidas.
- Saldos por caja en tiempo real (148 cajas) con clasificación operativa vs FC empleados.
- Flujo de caja agregable por día/semana/mes/año, excluyendo transferencias y categorías marcadas.
- Composición de gastos por familia/categoría con flags de exclusión por categoría.
- Top gastos individuales del período.
- KPIs comerciales: ventas totales, ticket promedio, clientes únicos, clientes nuevos, margen bruto $ y %, ventas en cta cte, discrepancias.
- Serie temporal de ventas + comparativa contra período anterior automática.
- Top productos (por margen / ingresos / cantidad), top clientes, top vendedores con margen por vendedor.
- Productos vendidos a pérdida (margen agregado < 0).
- Tasa de recompra y frecuencia promedio de pedidos.
- Análisis de cohortes de retención mensual.
- Mix de formas de pago (cajas usadas en ventas).
- Conciliación: facturado vs cobrado en caja vs cobranzas posteriores, con cobertura % y listas de "ventas sin cobro" + "discrepancias de pago".
- Cuentas corrientes por cliente con ledger tipo extracto bancario, saldo running, exportable a CSV.
- Asignar/desasignar cobranzas huérfanas a clientes.
- Carga manual de movimientos diarios con autocompletes, edición y borrado.
- Verificación de cobros (pago_v1 / pago_v2) en bulk por caja.
- Configuración de categorías (familia, flags transferencia/retiro/ingreso operativo/excluir flujo).
- Merge de cajas duplicadas y rename.
- Backup de la BD on-demand y backup diario automático al startup.
- Dashboard ejecutivo "Dirección" con deltas vs período anterior y panel de alertas automáticas (caída de ventas, caída de margen, cobertura baja, cajas en negativo, productos a pérdida, casos pendientes).

---

## Gaps por severidad

### Critical (sin esto NO reemplaza la planilla)

#### 1. Cierre de caja diario / mensual con bloqueo
Hoy no existe el concepto de "cierre". Cualquiera puede editar un movimiento de hace 6 meses y el saldo histórico cambia retroactivamente. Una empresa real necesita:
- Hacer arqueo al final del día (saldo teórico por caja vs lo que hay físicamente o en el banco).
- Registrar la diferencia como "ajuste de caja" si la hay.
- **Bloquear el período cerrado** — los movimientos anteriores al cierre no se pueden editar/borrar; solo se puede crear un movimiento nuevo de ajuste con fecha posterior.
- Idem cierre mensual: una vez cerrado abril, los KPIs de abril ya no cambian.

Sin esto, los reportes que se mandan al contador o que se mira la dirección **no son confiables porque mutan**. Es el problema #1 para reemplazar Excel: en Excel el dueño "congela" los meses copiando y pegando como valores; acá no hay equivalente.

#### 2. Compras, proveedores y cuentas a pagar
Hoy solo hay egresos sueltos como `MovimientoCaja`. No hay:
- Entidad **Proveedor** (con CUIT, condición de IVA, plazo de pago, datos bancarios).
- **Factura de compra** con fecha emisión, fecha vencimiento, monto, IVA discriminado, número de comprobante.
- **Saldo pendiente por proveedor** (las cuentas corrientes son solo de clientes).
- **Vencimientos próximos** ("¿qué tengo que pagar esta semana?").
- **Pagos parciales** que descuenten del saldo del proveedor.

La empresa de productos de limpieza compra mercadería, paga fletes, paga sueldos, paga servicios — todo eso entra hoy como egreso plano sin contraparte. Si Excel tenía una hoja "Proveedores" o "Cuentas a pagar" (y casi todas la tienen), esta app no la reemplaza.

#### 3. Manejo de IVA / impuestos
Cero tratamiento. Los importes son brutos. No hay:
- IVA débito fiscal (de las ventas) ni IVA crédito fiscal (de las compras).
- Percepciones / retenciones (IIBB, Ganancias, IVA — particularmente fuertes en AR).
- Reporte mensual de IVA para la DDJJ.
- Diferenciación entre comprobantes A/B/C/E.

Sin esto, el contador no puede usar nada de la app: tiene que pedir los CSVs originales de Tango/factura electrónica. La app sirve solo para gestión interna informal.

#### 4. Stock / inventario y costo real
Hoy el "costo" viene del CSV de detalle_ventas (campo `cst`) — es el costo *registrado en el momento de la venta*. No hay:
- **Stock actual por producto**.
- Quiebres / faltantes.
- Costo promedio ponderado o FIFO/LIFO actualizado por compras nuevas.
- Rotación de inventario.
- Alerta de "stock bajo" para reponer.

Para una empresa de productos físicos esto es central. El KPI "Productos a pérdida" hoy solo detecta lo que se vendió por debajo del costo *de ese momento*, pero si el costo subió entre la última compra y la venta y no se actualizó el `cst` del CSV, la app no se entera.

#### 5. Cierre/arqueo bancario y conciliación con extracto
Las cajas hoy son una abstracción mixta: efectivos + cuentas bancarias + tarjetas + Mercado Pago + etc. Pero no hay:
- **Carga / import del extracto bancario** (CSV del banco) y matcheo automático contra movimientos.
- **Conciliación bancaria mensual** ("estos 142 movimientos del banco coinciden con estos 138 movimientos del sistema; estos 4 están solo en el banco").
- **Saldo del banco vs saldo en sistema** con la diferencia explicada.

La "Conciliación" actual es facturado-vs-cobrado, no banco-vs-libros. Son cosas distintas y la segunda es la que pide el contador.

#### 6. Liquidación de tarjetas / billeteras virtuales
Cuando un cliente paga con tarjeta o Mercado Pago, el dinero entra al banco días después, con comisión descontada y a veces en cuotas. Hoy no se modela:
- Diferencia entre "cobro registrado" y "acreditado en banco".
- Comisión de la procesadora como gasto separado.
- Cuotas pendientes de acreditación.
- Conciliación con la liquidación del agregador.

Para una empresa que cobra con varios medios electrónicos esto es un agujero grande — el "saldo de la caja Mercado Pago" no es real porque parte está pendiente de acreditación.

---

### Important (falta para uso completo de gestión)

#### 7. Gastos recurrentes / suscripciones / cargos automáticos
No hay manera de decir "el alquiler son $X el día 5 de cada mes" ni "el ABL son $Y bimestral" para que se proyecten o se alerten. Hoy hay que cargar cada mes a mano.

#### 8. Flujo de caja proyectado (cash-flow forecast)
El PDF lo pide explícitamente ("Flujo de caja proyectado") y no está. Solo hay flujo histórico. Una empresa real necesita ver: con los cobros previstos de cta cte + ventas estimadas + pagos comprometidos, **¿voy a estar en negativo el 15 del mes que viene?**

#### 9. Punto de equilibrio
Pedido en el PDF. Requiere clasificar gastos en fijos vs variables (las familias actuales no distinguen) y tener costo de mercadería (sí está). Es un cálculo derivable pero no implementado.

#### 10. Vencimientos / antigüedad de cuentas a cobrar (aging)
El ledger del cliente muestra el saldo, pero no:
- Antigüedad de la deuda (0-30 / 31-60 / 61-90 / +90 días).
- Días promedio de cobro (DSO) — pedido en el PDF como "Días de cuentas por cobrar".
- Índice de morosidad — pedido en el PDF.
- Alertas por cliente moroso ("Cliente X tiene $Y vencido hace +60 días").

Sin aging es imposible priorizar a quién llamar primero para cobrar.

#### 11. Reportes para contador (export contable)
Hay export CSV solo del extracto de cliente. Falta:
- Libro Diario / Mayor exportable.
- Resumen mensual con totales por familia/categoría listo para cargar a un sistema contable.
- Subdiario de IVA ventas y compras.
- Export en formato compatible con AFIP / Tango / sistema del contador.

#### 12. Cuenta corriente de proveedores (espejo de la de clientes)
El modelo está pero solo para clientes. Sin proveedores, no hay DPO ("Días de cuentas por pagar" — pedido en el PDF).

#### 13. Multi-moneda
Nada. Para una PyME argentina hoy es habitual manejar al menos ARS y USD (proveedor de import, ahorros en dólar, precios dolarizados). Saldo en USD, cotización del día, ajustes por diferencia de cambio.

#### 14. Auditoría / histórico de cambios
Cualquiera edita una venta o un movimiento y no queda rastro de qué cambió, cuándo ni quién. Para finanzas serias es indispensable un audit log.

#### 15. Comparativas interanuales
Hoy se compara contra "período anterior" (los 30 días previos). Falta el clásico:
- Mes actual vs mismo mes año pasado (estacionalidad).
- YTD vs YTD anterior.
- Misma semana del año pasado.

Para detectar tendencias estacionales (el negocio de limpieza tiene picos estacionales: verano, fin de año) la comparación contra "los 30 días previos" engaña.

#### 16. Reportes para vendedores
Top vendedores existe en el dashboard, pero no hay vista "para el vendedor": su ranking, su comisión calculada, sus clientes pendientes de cobro, su pipeline. El PDF pide "Tasa de cierre", "Pipeline", "Ciclo de venta" — no implementados (probable: no hay datos de oportunidades, solo de pedidos cerrados).

#### 17. Presupuestos / metas
No se puede definir "objetivo de ventas mensual = $X" ni "presupuesto de gasto en logística = $Y" para comparar real vs presupuestado. Es de las primeras cosas que un dueño lleva en Excel.

#### 18. Liquidación de comisiones
Si los vendedores cobran por comisión sobre cobranza efectiva (común en empresas de productos), la app tiene los datos (margen por vendedor, cobranzas por cliente, asignación de cobranzas a vendedor del pedido), pero no calcula la comisión.

#### 19. Notas de crédito / devoluciones
No hay un workflow explícito para devolución de mercadería que reverse una venta y eventualmente devuelva la plata al cliente. Probablemente hoy se hace como "movimiento manual de egreso", lo cual no descuenta de los KPIs comerciales (sigue contando como venta).

#### 20. Sucursales / centros de costo
Si el negocio tiene más de un punto de venta o quiere ver el P&L por sucursal o por línea de producto, hoy no se puede segmentar.

---

### Minor (nice to have)

- Cheques en cartera y al día de pago (pedido común en finanzas argentinas).
- Caja chica con rendición.
- Importar resumen de tarjeta de crédito empresarial y categorizar gastos.
- Recordatorios / tareas ("llamar al cliente X mañana", "vence el seguro en 7 días").
- Adjuntar comprobantes (foto del ticket, PDF de la factura) a cada movimiento.
- Cálculo automático de CAC / LTV (pedido en PDF — requiere cargar costo de marketing, hoy ausente).
- Pipeline / embudo de ventas (pedido en PDF — requiere modelar oportunidades antes del pedido).
- KPIs de Operaciones / Logística del PDF (Entregas a tiempo, costo por viaje, km productivos): requeriría modelar viajes/rutas, fuera del alcance actual de los datos.
- KPIs de RRHH del PDF (Rotación, Ausentismo, eNPS): requeriría módulo de empleados.
- KPIs de Marketing del PDF (Leads, CAC, ROMI): requeriría conectar con Google Analytics / Meta Ads o cargar campañas a mano.
- KPIs de Atención al cliente del PDF (NPS, tiempo de respuesta, churn): requeriría un módulo de tickets/encuestas.
- Multi-usuario con roles (dueño / admin / vendedor / contador).
- Dashboard configurable por usuario (cada uno arma sus widgets).
- Notificaciones por mail / WhatsApp de alertas críticas.

---

## Comparación con el PDF original de KPIs pedidos

### Dirección / Gerencia (10 KPIs pedidos)
| KPI | Estado |
|---|---|
| Rentabilidad neta (%) | Falta — requiere todos los gastos clasificados como fijos/variables y resultado neto. Hoy hay "margen bruto" solo. |
| Margen operativo | Falta — derivable de composición de gastos pero no calculado. |
| Crecimiento de ingresos (%) | Cubierto (delta vs período anterior). Falta interanual. |
| EBITDA | Falta. |
| Flujo de caja | Cubierto (histórico). Falta proyectado. |
| Punto de equilibrio | Falta. |
| ROI | Falta — no hay registro de inversiones. |
| ROA | Falta — no hay activos modelados. |
| ROE | Falta — no hay patrimonio modelado. |
| Índice de crecimiento sostenido | Falta. |

**Cobertura: ~1.5 / 10**

### Comercial / Ventas (10 KPIs pedidos)
| KPI | Estado |
|---|---|
| Ventas totales | Cubierto. |
| Crecimiento de ventas (%) | Cubierto. |
| Tasa de cierre (%) | Falta — no hay leads/oportunidades. |
| Ticket promedio | Cubierto. |
| Nuevos clientes | Cubierto. |
| CAC | Falta — no hay costo de marketing. |
| LTV | Falta — calculable a futuro con cohortes + ticket. |
| Pipeline / Embudo | Falta. |
| Ciclo de venta (días) | Falta. |
| Tasa de recompra | Cubierto. |

**Cobertura: 5 / 10** (la mejor área)

### Administración / Finanzas (7 KPIs pedidos)
| KPI | Estado |
|---|---|
| Días de cuentas por cobrar (DSO) | Falta — no hay aging. |
| Días de cuentas por pagar (DPO) | Falta — no hay proveedores. |
| Índice de morosidad | Falta. |
| Liquidez corriente | Falta — requiere balance. |
| Endeudamiento | Falta. |
| Capital de trabajo | Falta. |
| Flujo de caja proyectado | Falta. |

**Cobertura: 0 / 7** (área más desatendida vs el pedido explícito)

### Operaciones / Logística (9 KPIs)
**Cobertura: 0 / 9** — fuera del alcance del modelo de datos actual (no hay viajes/entregas).

### Recursos Humanos (8 KPIs)
**Cobertura: 0 / 8** — sin módulo de empleados.

### Marketing (7 KPIs)
**Cobertura: 0 / 7** — sin tracking de campañas/leads.

### Atención al Cliente (8 KPIs)
**Cobertura: 0 / 8** — sin módulo de tickets/NPS.

### Sistemas / IT (6 KPIs)
**Cobertura: 0 / 6** — meta-KPIs de la app misma, no aplicables al negocio core.

### Compras / Abastecimiento (6 KPIs)
| KPI | Estado |
|---|---|
| Costo de compras | Parcial — sale como egreso pero no agrupado como "compras". |
| Tiempo de reposición | Falta. |
| Nivel de stock | Falta. |
| Rotación de inventario | Falta. |
| Quiebres de stock | Falta. |
| Dependencia de proveedores | Falta. |

**Cobertura: 0.5 / 6**

**Cobertura global del PDF: ~7 / 71 KPIs explícitos (~10%)**, concentrados en Comercial. Las áreas que el dueño priorizaría primero (Dirección + Administración + Compras = 23 KPIs) están casi vacías.

> Nota importante: el PDF es ambicioso y muchos KPIs (RRHH, Marketing, Atención) requieren módulos que probablemente quedaron fuera del alcance acordado del MVP. Pero los de Administración / Finanzas y Compras son centrales para "reemplazar la planilla" y deberían entrar.

---

## Plan de funcionalidades a agregar

Top 5 features ordenadas por valor para gestión real (impacto / esfuerzo):

### 1. Cierre de caja diario + mensual con bloqueo
**Por qué primero**: sin cierre, ningún reporte es confiable porque puede mutar. Es la base sobre la que se apoya todo lo demás. Permite además calcular saldo de apertura del día siguiente y arqueo.
**Qué incluye**:
- Modelo `CierreCaja(fecha, tipo=diario|mensual, saldos_por_caja, ajustes, cerrado_por, cerrado_at)`.
- Vista "Cierre del día": muestra saldo teórico por caja, input para saldo real, registra diferencia como ajuste.
- Bloqueo en backend: rechazar PATCH/DELETE de movimientos con fecha ≤ último cierre (salvo ajuste explícito).
- Indicador visual en cada pantalla: "Datos cerrados hasta: 30/04/2026".

### 2. Módulo de Proveedores + Cuentas a Pagar (espejo de Cta Cte clientes)
**Por qué**: Una empresa de productos físicos compra mercadería todo el tiempo. Sin esto, la mitad financiera del negocio (la deuda comercial) no existe en el sistema.
**Qué incluye**:
- Entidad `Proveedor`, `FacturaCompra` con vencimiento, ledger DEBE/HABER por proveedor.
- Vista "Vencimientos próximos" (qué pagar esta semana / mes).
- Aging de proveedores y cálculo de DPO.
- Vincular pagos (egresos de caja) a una factura de compra (idéntico al matching cobranza-cliente actual).
- Categorización automática del egreso a partir de la factura.

### 3. Aging de cuentas a cobrar + DSO + alertas de morosidad
**Por qué**: Con 4360 clientes y cuenta corriente, el dueño necesita saber a quién llamar HOY. El "saldo total a cobrar" actual no prioriza.
**Qué incluye**:
- En el ledger del cliente, calcular antigüedad de cada cargo y saldo por bucket (0-30 / 31-60 / 61-90 / +90).
- Tabla de cuentas corrientes con columnas de aging.
- Cálculo de DSO global y por vendedor.
- Alerta automática "Cliente X debe $Y vencido hace +Z días".
- Configurable: el plazo de pago default por cliente o por venta.

### 4. Conciliación bancaria con import de extracto + liquidación de tarjetas
**Por qué**: Hoy las cajas "Banco X" o "Mercado Pago" son una ficción interna que nadie verifica contra la realidad bancaria. En el momento que el dueño quiera comparar saldo real vs sistema, hay un gap inexplicable.
**Qué incluye**:
- Import de CSV del extracto bancario (al menos los 2-3 bancos más usados en AR).
- Match automático por monto + fecha + tolerancia, manual para el resto.
- Vista "Movimientos solo en banco" / "Movimientos solo en sistema".
- Modelo de liquidación de tarjeta/MP: cuándo entra cada cobro, qué comisión, qué cuotas pendientes.

### 5. Tratamiento de IVA + Familias fijas/variables + Resultado neto
**Por qué**: Es un combo que desbloquea Rentabilidad Neta, Margen Operativo, Punto de Equilibrio, EBITDA y Subdiario IVA. Datos ya están casi todos; falta clasificación adicional y cálculos derivados.
**Qué incluye**:
- En `CategoriaCaja` agregar flags `es_costo_fijo` / `es_costo_variable` / `es_impuesto`.
- En `Venta` y eventual `FacturaCompra`, descomponer `total = neto + iva + percepciones`.
- KPIs derivados: Resultado neto $ y %, Margen operativo, Punto de equilibrio, EBITDA simplificado.
- Subdiario IVA Ventas + IVA Compras exportable a CSV/Excel para el contador.
- Esto sí responde a "Administración / Finanzas" del PDF y al pedido del contador.

---

### Bonus a considerar luego (orden 6-10)

6. **Stock + alerta de quiebres** — requiere import inicial y carga de compras vinculada a productos.
7. **Flujo de caja proyectado** — combinable con #2 (vencimientos) y #3 (aging) para un forecast a 30/60/90 días.
8. **Comparativa interanual + presupuestos** — tabla de "objetivo vs real" por mes y comparar contra mismo mes año anterior.
9. **Audit log** — log de cambios en ventas y movimientos, accesible desde la UI.
10. **Notas de crédito / devoluciones** — workflow explícito que ajuste KPIs comerciales correctamente.
