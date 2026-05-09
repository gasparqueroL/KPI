# Review — Seguridad

## Resumen ejecutivo

La app está construida con asunciones razonables para un entorno **localhost de un único usuario** (sin auth, CORS limitado, ORM en lugar de SQL raw). Para ese contexto, el riesgo activo de "compromiso de datos por terceros" es bajo siempre que la PC no esté comprometida y `0.0.0.0` no esté bindeado.

El problema serio aparece cuando se quiebra cualquiera de tres premisas:

1. **El bind cambia de `127.0.0.1` a `0.0.0.0`** (típico cuando alguien quiere acceder desde el celular en la LAN). Sin auth, cualquiera en la red doméstica/oficina tiene acceso CRUD total a la BD financiera real: editar ventas, borrar movimientos, mergear cajas, restaurar backups, exportar el extracto de cualquier cliente, generar carga arbitraria con CSVs de hasta GBs (no hay límite de tamaño).
2. **El frontend dev server (Vite) se expone en LAN.** Mismo escenario.
3. **Se ejecuta cualquier otra app web en `localhost` que el navegador del usuario visite**: gracias a `allow_credentials=True` + el origin de Vite, un sitio malicioso que el usuario abra en otra pestaña podría intentar CSRF (mitigado parcialmente porque CORS sí restringe origins, pero hay matices abajo).

El código defensivo más importante (path traversal en `eliminar_backup`, ORM-only, validación de regex en parámetros de período) está bien hecho. Las grietas concretas son: ausencia total de autenticación en endpoints destructivos, ausencia de límite de tamaño en upload de CSV, exposición de paths internos en `/api/admin/info`, y stack traces que podrían filtrarse vía logs si éstos quedan accesibles.

## Modelo de amenazas asumido

**Esto SÍ protege contra:**
- Path traversal en el endpoint de borrado de backups (validado).
- SQL injection (uso correcto de SQLAlchemy ORM en todo el codebase, sin `text()` ni queries crudas).
- Filtrado masivo de stack traces en respuestas HTTP (handler global devuelve 500 genérico).
- CORS desde orígenes arbitrarios en navegador (lista cerrada de 2 orígenes).

**Esto NO protege contra:**
- Cualquiera con acceso físico/RDP/SSH a la PC: control total.
- Otro usuario en la misma LAN si el server bindea a `0.0.0.0`: control total.
- Malware local que lea `backend/data/kpi.db` directamente: no hay cifrado at-rest.
- Un sitio web malicioso ejecutándose en `http://localhost:OTRO_PUERTO` que el usuario visite: no puede leer respuestas (CORS bloquea), pero **sí podría disparar requests POST/DELETE no preflighted** si encuentra vectores (mitigado por content-type JSON que sí gatilla preflight; ver Important #3).
- Pérdida/robo de la PC: BD en claro, backups en claro, mismo directorio.
- Un CSV malicioso de muchos GB que llene RAM/disco: no hay rate limit ni size cap.

## Strengths

- **No hay SQL raw**: todos los queries pasan por SQLAlchemy ORM con parámetros tipados. Inmune a SQL injection incluso en endpoints con búsqueda por texto libre (`ventas_router.py:49`, `kpis/cuentas_corrientes.py:202` — usan `ilike(f"%{q}%")` pero el `%{q}%` se pasa como **parámetro**, no se concatena en SQL).
- **Path traversal en borrado de backups bien defendido** (`admin_router.py:53-65`): validación de prefijo + sufijo + comparación de `resolve().parent` contra `BACKUPS_DIR.resolve()`. Es un patrón correcto.
- **CORS limitado a dos orígenes explícitos** (`core/config.py:10-13`), no `*`.
- **Handler global de excepciones** (`main.py:40-51`) devuelve 500 genérico al cliente y loguea el traceback solo localmente. No filtra paths internos en respuestas HTTP.
- **Validación de parámetros de período con regex** (`kpis_comerciales.py:26`, `kpis_caja.py:35`, `kpis_caja.py:48`): `regex="^(dia|semana|mes|anio)$"` evita inyectar valores arbitrarios en branches de lógica.
- **Validación de rangos numéricos en `Query(...)`**: `ge=1, le=500` en limits, evita DoS por `limite=999999999`.
- **Pydantic `BaseModel` en todos los POST/PUT/PATCH**: tipado estricto, no `dict` libre (excepto `casos_revisar.py:130`, ver abajo).
- **`monto: float = Field(gt=0)`** en `caja_diaria_router.py:32`: rechaza montos negativos y cero.
- **El `Caja.normalizar()`** (`models/caja.py:23-27`) usa lowercase + strip + colapso de espacios — entrada arbitraria de usuario queda determinística y no rompe el FK.
- **No se usa `eval`, `exec`, `pickle`, `subprocess`, `os.system`, `yaml.load`, `shell=True`** en ningún lado. CSV se lee con pandas que no tiene riesgo de deserialización insegura.

## Issues por severidad

### Critical (datos comprometibles AHORA en localhost)

Estrictamente bajo localhost de un único usuario, no hay un crítico explotable por terceros remotos. Lo crítico es **lo que se rompe en el momento exacto en que la app deja localhost** (ver Important). En la postura actual el único crítico real es:

**C1. Sin auth + CORS con `allow_credentials=True` + posible CSRF con form-encoded** (`main.py:31-37`).
- `allow_credentials=True` combinado con `allow_methods=["*"]` y `allow_headers=["*"]` permite a `localhost:5173` mandar cualquier verbo con cookies. El frontend no usa cookies (es API key-less), así que en práctica no hay sesión que robar. Pero **si en el futuro se agrega auth con cookies, cualquier sitio en `localhost:5173` tendría acceso completo**. Más urgente: el patrón actual (`allow_credentials=True`) + cualquier endpoint que acepte `application/x-www-form-urlencoded` o `multipart/form-data` (como `POST /api/import`) es vulnerable a CSRF "simple" sin preflight desde cualquier origen, porque los browsers permiten cross-origin POST con esos content-types sin preflight, **pero** la respuesta queda bloqueada por CORS. El atacante no lee la respuesta pero sí puede gatillar el side-effect (importar un CSV malicioso, llamar `POST /api/admin/backup`).
- **Mitigación**: `allow_credentials=False` (no se usan cookies igual) elimina el escenario CSRF-con-cookies pero NO elimina el scenario "atacante hace POST sin credenciales". Para eso hay que: o requerir un header custom en el frontend (gatilla preflight, CORS lo bloquea), o validar `Origin`/`Referer` en endpoints destructivos.

### Important (problemas serios al exponer fuera de localhost)

**I1. Cero autenticación en endpoints destructivos** (todos los routers).
- `DELETE /api/admin/backups/{archivo}` (`admin_router.py:53`)
- `DELETE /api/caja-diaria/movimiento/{id}` (`caja_diaria_router.py:108`)
- `PATCH /api/ventas/{id_pedido}` (`ventas_router.py:121`)
- `PATCH /api/caja-diaria/movimiento/{id}` (`caja_diaria_router.py:132`)
- `POST /api/config/cajas/merge` (`configuracion.py:158`) — **operación irreversible que mergea entidades**
- `PUT /api/config/categorias/{tipo_operacion}` (`configuracion.py:81`)
- `POST /api/admin/backup` (sin rate limit — alguien puede llenar el disco con backups)
- `POST /api/import` — sin auth, sin límite de tamaño (ver I2)
- `POST /api/casos-revisar/{id}/reintentar` con `dict[str, Any]` libre del Body (`casos_revisar.py:130`)

  Cualquiera que acceda a la API tiene control CRUD pleno sobre los datos financieros. En localhost-only es aceptable; al primer `--host 0.0.0.0` o tunnel, es game over. **Recomendación**: agregar middleware que valide un token estático cargado de `core/config.py` desde env var, aunque sea simple `X-API-Key` constante. Defensa minimal pero suficiente para casos accidentales.

**I2. Upload de CSV sin límite de tamaño ni de filas** (`import_router.py:21`).
- `contenido = await file.read()` carga todo en memoria. Un POST de 4 GB tira el proceso. Pandas además parsea todo el DataFrame en memoria.
- **Recomendación**: validar `request.headers.get("content-length")` antes del read, o leer con stream y cortar a, p.ej., 50 MB. Adicional: limitar `len(df)` a algo como 200k filas y rechazar antes del loop.

**I3. CORS con `allow_credentials=True` + `allow_methods=["*"]` + `allow_headers=["*"]`** (`main.py:31-37`).
- La spec CORS dice que cuando `allow_credentials=True`, no se pueden usar comodines en methods/headers. Starlette/FastAPI **expande los wildcards** internamente para que técnicamente sí permita la combinación, pero esto es un anti-patrón documentado. Si más adelante se agregan cookies de sesión, el wildcard expone más superficie de la necesaria.
- **Recomendación**: explicitar la lista mínima de métodos (`["GET","POST","PUT","PATCH","DELETE","OPTIONS"]`) y headers (`["Content-Type","Authorization"]`). Y poner `allow_credentials=False` mientras no haya sesiones, para reducir el blast radius del eventual CSRF.

**I4. `/api/admin/info` filtra el path absoluto del DB** (`admin_router.py:91`).
- `"db_path": str(DB_PATH)` devuelve algo como `C:\Users\HP ENVY\Desktop\KPI\backend\data\kpi.db`. Filtra el username del SO, layout del filesystem y la ruta exacta del archivo más sensible. Útil para reconnaissance si la app queda expuesta.
- **Recomendación**: devolver solo `db_path: "data/kpi.db"` (relativo) o quitar el campo.

**I5. Stack traces COMPLETOS van a `logger`** (`main.py:43-47`).
- El handler global devuelve mensaje genérico al cliente (bien), pero loguea el traceback completo. Por defecto FastAPI loguea a stdout/stderr, así que termina en consola. Si en algún momento se redirige stdout a un archivo accesible vía web (ej. servir `data/` por error), filtra paths e identidades. Riesgo bajo pero defensa-en-profundidad pide truncar info sensible o estructurar logs JSON con campos curados.

**I6. `casos_revisar.py:130` acepta `dict[str, Any]` arbitrario que se pasa a `pd.DataFrame`** y de ahí al importer.
- El usuario puede meter columnas arbitrarias (no rompe nada porque el importer solo lee `row.get(...)` de columnas conocidas), pero no hay límite de tamaño del dict. Un payload con miles de keys serializa muchos megabytes y queda guardado en `c.correccion = json.dumps(...)`. Riesgo bajo en localhost; problema serio si se expone.
- **Recomendación**: definir un Pydantic model por fuente con los campos esperados, o al menos cap del tamaño del JSON corregido.

**I7. `id_cliente_relacionado` de `caja_diaria_router.py` no valida que el cliente exista** (`caja_diaria_router.py:90, 173`).
- En el endpoint de asignar (`cuentas_corrientes_router.py:103`) sí se valida. En crear/editar movimiento, no. Permite crear movimientos asociados a `id_cliente_relacionado=99999999` que no existe. No es un compromiso de seguridad pero sí de integridad referencial.

### Minor (defense in depth)

**M1. `Decimal(str(data.total))` con `float` previo** (`ventas_router.py:140`, `caja_diaria_router.py:49,153`).
- El parse a `float` antes de pasar a `Decimal` permite valores como `Infinity` o `NaN` desde Pydantic v2 (Pydantic en general los rechaza, pero `float` permite valores extremos). El `> 0` filtra negativos pero no detecta `inf`. Bajo riesgo.

**M2. Backup automático en startup sin protección concurrencia** (`main.py:23`, `admin_router.py:68`).
- Si el proceso reinicia rápidamente dos veces se podrían generar dos backups. Idempotente por día, así que riesgo es nulo. Mencionado solo por completitud.

**M3. `admin_router.py:23` usa `datetime.now()` (local time) para nombres de archivo**.
- Si la PC cambia de zona horaria los timestamps quedan inconsistentes. Cosmético.

**M4. `Caja.normalizar` no aplica Unicode normalization (NFC/NFKC)**.
- `"Café"` (con acento NFC) y `"Café"` (con acento descompuesto NFD) producen claves distintas y rompen el FK. Improbable en práctica pero seguro de cubrir con `unicodedata.normalize("NFC", ...)`.

**M5. `extracto_csv` (`cuentas_corrientes_router.py:30-59`)**: el nombre del cliente entra al `Content-Disposition` filename después de un `replace(" ","_").replace("/","_")[:50]`. Falta sanitizar `"`, `\r`, `\n`, `\\`. Header injection en HTTP es difícil pero técnicamente posible si un nombre de cliente contiene CRLF.

**M6. `client.js` baseURL hardcoded a `http://localhost:8000`** (`frontend/src/api/client.js:4`).
- HTTP en claro. En localhost no importa, pero si en algún momento se mueve a una IP de la LAN, las credenciales hipotéticas y los datos viajan en claro.

**M7. El timeout de axios es 600000 ms (10 minutos)** (`client.js:5`).
- Permite que requests cuelguen mucho tiempo. Si un endpoint pesado se atasca, el cliente queda atorado. No es seguridad estricta, pero sí availability.

**M8. Permisos de archivos**: la BD `data/kpi.db` y `data/backups/*.db` heredan los permisos default del usuario de Windows. En una PC personal con un solo usuario es OK; en una PC compartida (cuenta de invitado, multi-user), todos los usuarios locales con permiso de lectura sobre `Desktop/KPI/backend/data/` ven los datos financieros. Recomendable mover `data/` a `%APPDATA%/KPI/` o `%LOCALAPPDATA%/KPI/` con ACLs restringidas al usuario.

**M9. `BACKUPS_DIR.glob("kpi_*.db")` en `info_sistema`** (`admin_router.py:87`): si el directorio crece a miles de backups, cada call al endpoint enumera todos. Trivial DoS local. Cap en `len(backups)` o `LIMIT N`.

**M10. `_cache` global en `alertas_router.py:17`**: thread-safety está OK por el GIL para reads/writes simples de dict. Si en algún momento se mueve a workers async multi-proceso (uvicorn con `--workers > 1`), el cache se duplica y la invalidación deja de funcionar entre workers. No es vulnerabilidad, sí gotcha.

**M11. `pd.read_csv` con `dtype=str`**: bien. Si en el futuro se cambia a inferencia automática, abre puerta a "CSV injection" donde celdas que empiezan con `=`, `+`, `-`, `@` ejecutan fórmulas si Excel abre el archivo. Aplicable a `extracto_csv`: si un cliente se llama `=cmd|'/c calc'!A1`, abrir el CSV en Excel ejecuta. **Recomendación**: en `extracto_csv` (`cuentas_corrientes_router.py:45-52`), prefijar con `'` cualquier celda que empiece con `=+-@\t\r`.

## Plan de hardening priorizado

Top 5 ordenadas por costo/beneficio en el contexto localhost-only:

1. **Bindear explícitamente uvicorn a `127.0.0.1`** y documentarlo en el README/script de arranque. Este cambio de una línea es la defensa más alta-impacto: cierra de raíz todos los Important. Sin esto, cualquier hardening posterior es paliativo.
2. **Cap de tamaño en el upload de CSV** (`import_router.py`): rechazar `>50 MB` o `>200k filas`. Una línea de código, evita un foot-gun común.
3. **Mitigar CSRF en endpoints destructivos**: la receta más barata es `allow_credentials=False` en CORS (no se usan cookies igual) + requerir un header custom (`X-Requested-With: kpi-frontend`) en cada request del frontend, validado por dependencia FastAPI. Esto fuerza preflight y CORS bloquea cualquier cross-origin POST. Cinco líneas de código y elimina C1.
4. **Sacar el path absoluto de la BD en `/api/admin/info`** y truncar/curar lo que se loguea en el handler global. Trivial y reduce reconnaissance si la app se filtra.
5. **Mover `data/` a `%LOCALAPPDATA%/KPI/`** con ACLs restringidas al usuario. Cubre el escenario "PC compartida" y "malware con permisos del usuario regular" sin tocar código de aplicación, solo `core/config.py`.

Como bonus implícito: si en algún momento aparece un sexto ítem para hacer, el más recomendable es **agregar un `X-API-Key` estático** leído de variable de entorno y validado por dependencia compartida en todos los routers. Es la diferencia entre "expuesto en LAN = compromiso total" y "expuesto en LAN = atacante necesita el secreto". Cuesta 30 líneas en total.
