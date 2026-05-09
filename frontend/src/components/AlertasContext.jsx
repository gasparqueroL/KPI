import { createContext, useContext, useEffect, useState } from "react";
import api from "../api/client";

const AlertasContext = createContext({
  alertas: [], total: 0, criticas: 0, atencion: 0, info: 0,
  error: null, recargar: () => {},
});

export function AlertasProvider({ children }) {
  const [data, setData] = useState({ alertas: [], total: 0, criticas: 0, atencion: 0, info: 0 });
  const [error, setError] = useState(null);

  // Race conocido: `recargar` y el polling de cada 60s pueden estar in-flight
  // simultáneamente. Si el response del polling llega DESPUÉS del de recargar,
  // pisa los datos "más nuevos" con los anteriores (último setData gana, no
  // el más reciente request). En la práctica para alertas de 60s el delta
  // entre fetches es chico y la ventana de overlap microscópica — decisión
  // deliberada de NO agregar cancel token / fetch ID. Si en el futuro recargar
  // se llama tras user actions (post-edit, post-delete) y la dueña ve datos
  // viejos por race, agregar AbortController + fetch ID acá.
  async function recargar() {
    try {
      const { data } = await api.get("/api/alertas");
      setData(data);
      setError(null);
    } catch (e) {
      console.error("Error cargando alertas", e);
      setError(e.message || "Error de conexión");
    }
  }

  useEffect(() => {
    recargar();
    const id = setInterval(recargar, 60000); // refresca cada 60s
    return () => clearInterval(id);
  }, []);

  return <AlertasContext.Provider value={{ ...data, error, recargar }}>{children}</AlertasContext.Provider>;
}

export function useAlertas() {
  return useContext(AlertasContext);
}
