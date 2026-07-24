import { defineConfig } from 'vite';

export default defineConfig({
  root: '.',
  base: './',
  server: {
    host: true,
  },
  build: {
    outDir: 'dist',
    target: 'es2022',
  },
});
