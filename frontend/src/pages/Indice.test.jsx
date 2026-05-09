import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Indice from "./Indice";

function renderIndice() {
  return render(
    <MemoryRouter>
      <Indice />
    </MemoryRouter>
  );
}

describe("Indice (página /indice)", () => {
  it("renderiza el título y el resumen de KPIs", () => {
    renderIndice();
    expect(screen.getByText(/Índice de KPIs/i)).toBeTruthy();
    expect(screen.getByText(/Implementados \(PDF\)/i)).toBeTruthy();
    expect(screen.getAllByText(/Parciales/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Pendientes/i).length).toBeGreaterThan(0);
  });

  it("muestra al menos un KPI por área principal", () => {
    renderIndice();
    expect(screen.getAllByText(/Dirección \/ Gerencia/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Comercial \/ Ventas/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/RRHH/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Marketing/i).length).toBeGreaterThan(0);
  });

  it("filtrar por estado 'pendiente' reduce la lista", () => {
    renderIndice();
    // Capturar contador inicial: "X KPIs" en el header del panel.
    const tituloInicial = screen.getByText(/^\d+ KPIs?$/);
    const totalInicial = parseInt(tituloInicial.textContent.match(/(\d+)/)[1], 10);
    expect(totalInicial).toBeGreaterThan(20);

    // Click el select de Estado y seleccionar pendiente.
    // El select tiene labels "Implementados", "Parciales", "Pendientes"
    // — buscamos el `<select>` que tenga la opción "Pendientes".
    const selects = document.querySelectorAll("select");
    let estadoSelect = null;
    for (const s of selects) {
      const opciones = [...s.options].map((o) => o.textContent);
      if (opciones.includes("Pendientes")) { estadoSelect = s; break; }
    }
    expect(estadoSelect).toBeTruthy();
    fireEvent.change(estadoSelect, { target: { value: "pendiente" } });

    // Total después del filtro debe ser MENOR
    const tituloPost = screen.getByText(/^\d+ KPIs?$/);
    const totalPost = parseInt(tituloPost.textContent.match(/(\d+)/)[1], 10);
    expect(totalPost).toBeLessThan(totalInicial);
  });

  it("búsqueda libre filtra por nombre", () => {
    renderIndice();
    const search = screen.getByPlaceholderText(/Buscar KPI/i);
    fireEvent.change(search, { target: { value: "rotacion" } });
    // El total se reduce a 1 (solo Rotación coincide)
    const tituloPost = screen.getByText(/^\d+ KPIs?$/);
    const totalPost = parseInt(tituloPost.textContent.match(/(\d+)/)[1], 10);
    expect(totalPost).toBeLessThanOrEqual(2);  // Rotación + posible match parcial
  });
});
