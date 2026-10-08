// Inlines the JS and CSS of the `--mode single` build into one HTML file that works offline from disk.
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist-single");
let html = readFileSync(join(dist, "index.html"), "utf8");

html = html.replace(/<script type="module" crossorigin src="\.\/(assets\/[^"]+\.js)"><\/script>/g, (_, file) => {
  const js = readFileSync(join(dist, file), "utf8").replace(/<\/script/gi, "<\\/script");
  return `<script type="module">${js}</script>`;
});
html = html.replace(/<link rel="stylesheet" crossorigin href="\.\/(assets\/[^"]+\.css)">/g, (_, file) => {
  return `<style>${readFileSync(join(dist, file), "utf8")}</style>`;
});

if (/src="\.\/assets|href="\.\/assets/.test(html)) {
  throw new Error("Some assets were not inlined — check the build output");
}
writeFileSync(join(dist, "bizforge.html"), html);
rmSync(join(dist, "assets"), { recursive: true, force: true });
rmSync(join(dist, "index.html"));
console.log(`dist-single/bizforge.html — ${(html.length / 1024).toFixed(0)} KB`);
