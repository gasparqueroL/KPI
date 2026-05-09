/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    // jsdom: csvExport.js usa Blob/URL/document para trigger del download.
    // Tests que solo testean lógica pura no necesitan jsdom pero el costo
    // marginal de levantarlo siempre es chico.
    environment: 'jsdom',
    globals: true,
  },
  build: {
    rollupOptions: {
      output: {
        // Separamos las libs pesadas en chunks vendor propios:
        // - recharts es ~300KB y solo se usa en Direccion/Analisis,
        //   pero como Direccion es eager se cargaba siempre. Ahora
        //   queda en su propio chunk con cache de larga duración.
        // - react/react-router/axios cambian poco entre releases →
        //   chunk separado = mejor cache hit en deploys siguientes.
        manualChunks(id) {
          // rolldown normaliza paths a `/` en todas las plataformas, así que
          // los matches con forward slash funcionan también en Windows.
          if (id.includes('node_modules')) {
            if (id.includes('recharts') || id.includes('d3-')) return 'recharts';
            if (id.includes('react-router')) return 'react';
            if (id.includes('/react/') || id.includes('/react-dom/') || id.includes('/scheduler/')) return 'react';
            // axios cambia poco entre releases — sin esta línea termina
            // duplicado en cada chunk lazy de página.
            if (id.includes('/axios/')) return 'react';
          }
        },
      },
    },
  },
})
