import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss(), svelte()],
  server: {
    // Entwicklung: API vom lokal laufenden Backend durchreichen
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: { target: 'es2022', sourcemap: false },
});
