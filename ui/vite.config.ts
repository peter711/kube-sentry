import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: '/ui/',
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/ask': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
      '/conversations': 'http://localhost:8080',
      '/repair': 'http://localhost:8080',
      '/operations': 'http://localhost:8080',
      '/audit': 'http://localhost:8080',
    },
  },
})
