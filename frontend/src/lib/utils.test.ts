import { test } from "node:test";
import assert from "node:assert/strict";
import { cn, formatBytes, extFromUrl } from "./utils.ts";

test("cn preserva text-background al combinar con un tamaño de texto custom (text-15)", () => {
  const result = cn(
    "bg-ink text-background shadow-sm hover:bg-[var(--area-accent)] hover:text-ink",
    "w-full h-auto py-4 text-15 font-bold",
  );
  assert.match(result, /\btext-background\b/, "text-background no debería desaparecer del merge");
  assert.match(result, /\btext-15\b/, "text-15 debería sobrevivir el merge");
});

test("cn preserva text-ink con los otros tamaños custom (text-22/text-2xs/text-3xs)", () => {
  for (const size of ["text-22", "text-2xs", "text-3xs"]) {
    const result = cn("text-ink", size);
    assert.match(result, /\btext-ink\b/, `text-ink no debería desaparecer al combinar con ${size}`);
    assert.match(result, new RegExp(`\\b${size}\\b`), `${size} debería sobrevivir el merge`);
  }
});

test("cn sigue resolviendo conflictos DENTRO del grupo font-size (custom vence a texto previo)", () => {
  assert.equal(cn("text-sm", "text-15"), "text-15");
  assert.equal(cn("text-15", "text-base"), "text-base");
});

test("formatBytes elige la unidad correcta en cada rango", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(1024), "1,0 KB");
  assert.equal(formatBytes(348_160), "340 KB");
  assert.equal(formatBytes(1_258_291), "1,2 MB");
  assert.equal(formatBytes(15_728_640), "15 MB");
});

test("extFromUrl lee la extensión del último segmento de path, ignorando query/hash", () => {
  assert.equal(
    extFromUrl("https://pub-x.r2.dev/media/equipo/1-x/fotos/0/display-abc123.webp"),
    "WEBP",
  );
  assert.equal(extFromUrl("https://x.com/a/b/c/foto.JPG?v=2#frag"), "JPG");
});

test("extFromUrl no devuelve la URL entera cuando no hay extensión (bug real, imagen sin dot)", () => {
  // Reproduce el bug encontrado en vivo con una URL de prueba sin extensión
  // (ej. un host que sirve por id, sin sufijo de archivo).
  assert.equal(extFromUrl("https://picsum.photos/seed/g1/600/600"), "—");
});
