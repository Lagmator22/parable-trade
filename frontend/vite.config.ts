import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const engine = process.env.PARABLE_API || 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': engine, '/paypal': engine } },
  test: { environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'] },
});
