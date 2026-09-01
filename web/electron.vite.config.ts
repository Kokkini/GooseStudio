import react from '@vitejs/plugin-react'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import path from 'node:path'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: { rollupOptions: { input: path.resolve('electron/main.ts') } },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: path.resolve('electron/preload.ts'),
        output: { format: 'cjs', entryFileNames: 'preload.cjs' },
      },
    },
  },
  renderer: {
    root: '.',
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 4173,
      strictPort: true,
      watch: { usePolling: true, interval: 200 },
    },
    build: { rollupOptions: { input: path.resolve('index.html') } },
  },
})
