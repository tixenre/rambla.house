/**
 * runInBatches — corre `task` sobre los items de a lo sumo `concurrency` en
 * simultáneo, reportando cada resultado individual vía `onSettled` a medida
 * que termina (no espera al lote completo). Usado por PhotoGallery para las
 * subidas (evita 429 contra ADMIN_UPLOAD_LIMIT, 20/min) y los borrados en
 * lote (ADMIN_WRITE_LIMIT, 60/min) de las 3 galerías del back-office.
 */
export async function runInBatches<T>(
  items: T[],
  concurrency: number,
  task: (item: T) => Promise<unknown>,
  onSettled?: (item: T, ok: boolean, error?: unknown) => void,
): Promise<{ ok: number; failed: number }> {
  let ok = 0;
  let failed = 0;
  for (let i = 0; i < items.length; i += concurrency) {
    const tanda = items.slice(i, i + concurrency);
    const resultados = await Promise.allSettled(tanda.map((item) => task(item)));
    resultados.forEach((r, idx) => {
      const item = tanda[idx];
      if (r.status === "fulfilled") {
        ok++;
        onSettled?.(item, true);
      } else {
        failed++;
        onSettled?.(item, false, r.reason);
      }
    });
  }
  return { ok, failed };
}
