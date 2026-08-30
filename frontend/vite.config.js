import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server runs on 5180 and proxies /api -> FastAPI on 8001, so the
// frontend never needs an absolute backend URL. Both defaults avoid the
// common 5173/8000 ports, which other local projects often occupy.
export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.FRONTEND_PORT) || 5180,
    strictPort: true,      // fail loudly instead of silently moving ports
    proxy: {
      '/api': {
        // Port 8000 is often taken by other local PHP/Node projects, so the
        // backend defaults to 8001. Override with VITE_API_TARGET if needed.
        target: process.env.VITE_API_TARGET || 'http://localhost:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
