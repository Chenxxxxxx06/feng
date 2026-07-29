import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 后端权威端口为 8000（与 启动风调预顺.bat 的 PORT、backend/launcher.py 的 uvicorn 绑定一致）。
// 如需改端口，请三处同步修改，否则开发模式下代理会打到空端口。
const apiTarget = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  build: {
    // The nested 3D engine is intentionally isolated and loaded only after the
    // drone route renders (about 256 kB gzip); all normal route chunks stay <500 kB.
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const moduleId = id.replaceAll('\\', '/');
          if (moduleId.includes('/node_modules/zrender/')) return 'vendor-zrender';
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/data': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
