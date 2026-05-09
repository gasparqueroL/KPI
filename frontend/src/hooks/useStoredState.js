import { useEffect, useState } from "react";

/**
 * useState con persistencia en sessionStorage.
 *
 * Ámbito: la sesión (se limpia al cerrar la pestaña). Útil para filtros
 * que la dueña no quiere re-tipear al navegar entre páginas, pero que
 * tampoco deberían sobrevivir un día completo (ej: si abrió ayer con un
 * date range del mes pasado, hoy quiere arrancar limpio).
 *
 * Convención de keys: "<page>:<filtro>" (ej: "comercial:dateRange").
 *
 * **CONTRATO**: `key` debe ser ESTABLE durante el ciclo de vida del
 * componente. El initializer corre solo una vez en mount; si `key`
 * cambiara en runtime, el state quedaría con el valor de la key vieja
 * y el effect siguiente sobreescribiría sessionStorage[keyNueva] con
 * ese valor — perdiendo lo que estaba guardado para keyNueva. Si
 * necesitás keys dinámicas (ej: `caja:${idCaja}`), montá/desmontá el
 * componente con `key=` prop de React para forzar un mount nuevo.
 *
 * @param {string} key - clave única ESTABLE en sessionStorage.
 * @param {*} initial - valor default si no hay nada guardado o falla parse.
 */
export function useStoredState(key, initial) {
  const [state, setState] = useState(() => {
    try {
      const raw = sessionStorage.getItem(key);
      if (raw == null) return initial;
      return JSON.parse(raw);
    } catch (e) {
      // JSON corrupto o formato viejo: fallback transparente a initial.
      console.warn(`[useStoredState] No se pudo parsear ${key}, usando initial:`, e);
      return initial;
    }
  });

  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify(state));
    } catch (e) {
      // sessionStorage llena o deshabilitada (modo incógnito en algunos
      // browsers). El filtro sigue funcionando en memoria, solo no persiste.
      console.warn(`[useStoredState] No se pudo guardar ${key}:`, e);
    }
  }, [key, state]);

  return [state, setState];
}
