import { defineConfig } from 'vite'
import { resolve } from 'path';


// https://vitejs.dev/config/
export default defineConfig({
    base: '/static/',
    build: {
      outDir: resolve('./static/'),
      assetsDir: 'dist',
      manifest: 'manifest_svraster_webgl_demo.json',
      emptyOutDir: false,
      rollupOptions: {
        input: {
          main: resolve('svraster-webgl/src/main.ts'),
        },
      },
    },
    root: resolve('./svraster-webgl'),
    server: {
      host: true,
      watch: {
        usePolling: true,
      },
      cors: {
        origin: 'http://localhost:8000',
        methods: ['GET'],
        credentials: true
      },
      port: 5174,
      origin: "http://localhost:5174",
      headers: {
        "Cross-Origin-Embedder-Policy": "require-corp",
        "Cross-Origin-Opener-Policy": "same-origin"
      },
     },
  })
  