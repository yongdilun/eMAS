import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const testArtifactWatchIgnores = [
  '**/playwright-output/**',
  '**/playwright-report/**',
  '**/test-results/**',
  '**/.playwright-artifacts-*/**',
]

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    watch: {
      ignored: testArtifactWatchIgnores,
    },
  },
})

