import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // 5180 by default, not 5173-5175: those are used by the author's other local projects.
    // FRONTEND_PORT lets several stacks (e.g. one per git worktree) run side by side.
    port: Number(process.env.FRONTEND_PORT ?? 5180),
    strictPort: true,
    // Bind mounts on Windows do not propagate file events, so the watcher has to poll.
    watch: { usePolling: true },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
