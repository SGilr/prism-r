import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

// PRISM-R static site. Output goes to site/dist for Cloudflare Pages.
export default defineConfig({
  output: 'static',
  outDir: './dist',
  integrations: [tailwind()],
});
