import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Bản build nằm trong static/app để FastAPI phục vụ luôn, không cần cài Node khi chỉ chạy ứng dụng.
// Khi phát triển giao diện: chạy uvicorn ở cổng 8000, rồi `npm run dev` (cổng 5173, tự chuyển /api sang 8000).
export default defineConfig(({ command }) => ({
  plugins: [react()],
  // Bản build được FastAPI phục vụ tại /static/app/; khi `npm run dev` chạy ở gốc để đường dẫn /pos, /reports hoạt động
  base: command === 'build' ? '/static/app/' : '/',
  build: { outDir: '../static/app', emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:8000', '/uploads': 'http://localhost:8000', '/static/img': 'http://localhost:8000' },
  },
}))
