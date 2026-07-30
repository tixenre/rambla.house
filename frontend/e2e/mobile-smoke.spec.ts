import { test, expect } from "@playwright/test";

const PUBLIC_ROUTES = [
  "/",
  "/rental",
  "/estudio",
  "/escuelas",
  "/preguntas-frecuentes",
  "/cliente/login",
  "/cliente/registro",
];

for (const route of PUBLIC_ROUTES) {
  test(`${route} — sin scroll horizontal en mobile`, async ({ page }) => {
    await page.goto(route);
    await page.waitForLoadState("networkidle");

    const overflowX = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    expect(overflowX, `scroll horizontal detectado en ${route}`).toBe(false);
  });
}
