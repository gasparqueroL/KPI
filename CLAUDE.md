# Reglas operativas para Claude en este proyecto

Este archivo es la fuente de verdad sobre cómo Claude trabaja en este repo. Se lee antes de cualquier tarea.

---

## 1. Toma de decisiones con jurado adversarial

Cuando aparece una **decisión NO trivial** durante el trabajo, Claude debe:

1. **Identificar** la decisión y al menos 2 alternativas concretas.
2. **Despachar 2 subagentes en paralelo** (vía Agent tool, `subagent_type: general-purpose`) con framings totalmente opuestos:
   - **Agente A — Postura conservadora / estricta / orientada a integridad.** Defiende la opción que minimiza riesgos de datos malos, errores silenciosos o complejidad técnica.
   - **Agente B — Postura pragmática / flexible / orientada a velocidad y UX.** Defiende la opción que reduce fricción, acelera entregas o simplifica el modelo mental del usuario.

   Cada subagente recibe el mismo contexto y debe responder en ~10 líneas: postura, ventajas, riesgos de la opción contraria, escenario donde su recomendación es la mejor.

3. **Leer ambos argumentos**, evaluar contra el contexto del proyecto y las preferencias ya expresadas por el usuario.
4. **Tomar la decisión final** Claude mismo. No "votar" mecánicamente — sintetizar.
5. **Comunicar al usuario en 2-3 líneas**: qué decidió y por qué (mencionando que se consultaron las dos posturas opuestas).
6. **Continuar con la implementación**.

### Cuándo aplicar el jurado

✅ Aplicar a:
- Decisiones de arquitectura (estructura de módulos, separación back/front)
- Modelado de datos (qué entidad es central, qué FK, qué denormalizar)
- Políticas de validación (qué rechazar, qué aceptar con flag)
- Algoritmos con tradeoffs reales (estrategias de idempotencia, dedupe, matching)
- Tradeoffs de UX (estricto vs tolerante, sincronía vs background)
- Manejo de errores y casos límite con impacto en el usuario
- Decisiones de seguridad o privacidad

❌ NO aplicar a:
- Parseo de tipos, conversión de formatos (decisiones mecánicas)
- Refactors triviales (renombrar variable, extraer función obvia)
- Bugs con fix evidente
- Cualquier cosa que el usuario ya decidió explícitamente
- Naming, indentación, formato de comentarios

### Anti-patrones

- ❌ Convocar el jurado solo para "cumplir" — si la decisión es obvia, no se usa.
- ❌ Esconderse detrás del jurado — Claude decide, no los subagentes.
- ❌ Convocar el jurado para postergar implementación.

---

## 2. Idioma

Toda comunicación con el usuario en **español**. Comentarios en código en español también. Términos técnicos universales (PK, FK, hash, endpoint, framework) se mantienen en inglés.

---

## 3. Reglas de negocio del dominio

Antes de modelar datos, calcular KPIs o validar imports, leer:
- `~/.claude/projects/C--Users-HP-ENVY-Desktop-KPI/memory/project_reglas_negocio.md`

Resumen no-negociable:
- **Cajas son la entidad central** del modelo financiero.
- **Solo entra al sistema lo válido** — el resto va a "Casos a revisar".
- Las tablas `ventas` / `detalle_ventas` / `movimientos_caja` **NO tienen relación 1:1** entre totales — diferencias son esperables.
