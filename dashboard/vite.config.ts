import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Served from /insights/ on the CloudFront distribution, next to the data.json that the
// pipeline publishes, so every asset path is relative.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  // One chunk of about 250 KB gzipped, most of it the world map and chart libraries. A
  // single file is simpler to serve from S3 than splitting a page nobody navigates within.
  build: { chunkSizeWarningLimit: 900 },
})
