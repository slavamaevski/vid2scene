import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { resolve } from 'path';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [svelte()],
  base: '/static/',
  build: {
    outDir: resolve('./static/'),
    assetsDir: 'dist',
    manifest: 'manifest.json',
    emptyOutDir: false,
    rollupOptions: {
      input: {
        main: resolve('static/src/main.ts'),
        sw: resolve('static/src/sw.js'),
      },
      output: {
        entryFileNames: (assetInfo) => {
          if (assetInfo.name === 'sw') return 'sw.js';
          return 'assets/[name]-[hash].js';
        },
      },
    },
  },
  root: resolve('.'),
  server: {
    // host: '0.0.0.0', // Listen on all interfaces for ADB forwarding
    // port: 5173,
    // strictPort: true, // Fail if port is already in use
    host: true,
    watch: {
      usePolling: true,
    },
    origin: "http://localhost:5173",
    headers: {
      "Cross-Origin-Embedder-Policy": "require-corp",
      "Cross-Origin-Opener-Policy": "same-origin",
      "Service-Worker-Allowed": "/"
    },
  },
  assetsInclude: ['**/*.wasm', "**/*.spz"],
})
