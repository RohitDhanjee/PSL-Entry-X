import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'


// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    global: 'window',
  },
  server: {
    // host: true,
    // port: 5173,
    // allowedHosts: [
    //   'preliberally-preelemental-lasonya.ngrok-free.dev',
    //   'all'
    // ],
    proxy: {
      '/api': {
        target: process.env.ALLOWED_ORIGINS,
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
