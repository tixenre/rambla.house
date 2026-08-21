import { test } from "node:test";
import assert from "node:assert/strict";
import { cn, compareFilenames } from "./utils.ts";

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

test("compareFilenames ordena numéricamente, no alfabéticamente (2 antes que 10)", () => {
  const shuffled = ["10.jpg", "2.jpg", "1.jpg"];
  assert.deepEqual(shuffled.sort(compareFilenames), ["1.jpg", "2.jpg", "10.jpg"]);
});

test("compareFilenames reproduce el caso real reportado: 01.jpg...013.jpg desordenados por el FileList", () => {
  const shuffled = ["05.jpg", "013.jpg", "01.jpg", "08.jpg", "02.jpg", "03.jpg", "04.jpg"];
  assert.deepEqual(shuffled.sort(compareFilenames), [
    "01.jpg",
    "02.jpg",
    "03.jpg",
    "04.jpg",
    "05.jpg",
    "08.jpg",
    "013.jpg",
  ]);
});
