import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const target = process.env.MUSIC_IR_API || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': { target, changeOrigin: true, rewrite: path => path.replace(/^\/api/, '') } },
  },
  preview: {
    proxy: { '/api': { target, changeOrigin: true, rewrite: path => path.replace(/^\/api/, '') } },
  },
})
