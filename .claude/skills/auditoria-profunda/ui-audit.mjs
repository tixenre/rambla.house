#!/usr/bin/env node
/**
 * ui-audit.mjs — Auditoría UI profunda y REPETIBLE de TODA la web cliente.
 *
 * Real Chromium (system Chrome), viewports exactos, renderiza reveals con scroll
 * real, mide rigurosamente y GUARDA UN SCREENSHOT por pantalla×variante×tamaño,
 * con NOMBRE claro (screen__viewport.png) + un _INDEX.md legible que mapea cada
 * captura a sus hallazgos → comparar antes/después y saber "cuál es cuál".
 *
 * Uso (desde frontend/):
 *   node ../.claude/skills/auditoria-profunda/ui-audit.mjs                  # web completa
 *   SCREENS=hub,rental-grid VIEWPORTS=320,1280 node ...ui-audit.mjs         # subset por nombre
 *   ROUTES=/rental,/estudio node ...ui-audit.mjs                            # subset por path
 *   LABEL=before node ...ui-audit.mjs                                       # baseline comparable
 *
 * Requiere: backend :8000 + vite :3000, DB local con cliente verificado.
 * Criterios buscados: ver SKILL.md (lista descriptiva).
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { execSync } from "node:child_process";

const BASE = process.env.BASE || "http://localhost:3000";
const SECRET = process.env.STAGING_LOGIN_SECRET || "dev-local-secret";
const CLIENTE_ID = Number(process.env.CLIENTE_ID || 209);
// Resuelto contra la raíz del repo (no relativo a este archivo): si el script se copia a otro
// lugar (necesario en sandboxes donde Playwright solo resuelve el módulo ESM dentro de la cadena
// de `frontend/node_modules`), un path relativo a `import.meta.url` apuntaba a un lugar
// equivocado SIN error (bug real, 2026-07-25) — `git rev-parse` sigue siendo correcto porque el
// script, dondequiera que se copie, sigue viviendo DENTRO del mismo working tree.
const REPO = (() => {
  try {
    return execSync("git rev-parse --show-toplevel", {
      cwd: dirname(fileURLToPath(import.meta.url)),
    }).toString().trim();
  } catch {
    return resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
  }
})();
const LABEL = process.env.LABEL || "run";
const OUT = resolve(REPO, "docs/audit-ui-screenshots", LABEL);
mkdirSync(OUT, { recursive: true });

const VIEWPORTS = (process.env.VIEWPORTS ? process.env.VIEWPORTS.split(",").map(Number) : [320, 360, 375, 414, 640, 768, 1024, 1280, 1440, 1920]);
const H = (w) => (w < 640 ? 780 : w < 1024 ? 1024 : 900);

export const safe = (s) => s.replace(/[^\w]+/g,"_").replace(/^_|_$/g,"") || "root";

// TODA la web cliente (cada {name} = nombre de archivo legible; grid y list son variantes por URL).
const ALL_SCREENS = [
  { name: "hub",            path: "/" },
  { name: "rental-grid",    path: "/rental?view=grid" },
  { name: "rental-list",    path: "/rental?view=list" },
  { name: "estudio",        path: "/estudio" },
  { name: "escuela",        path: "/escuela" },
  { name: "equipo-detail",  path: "/equipo/213" },
  { name: "login",          path: "/cliente/login" },
  { name: "registro",       path: "/cliente/registro" },
  { name: "portal",         path: "/cliente/portal" },
  { name: "perfil",         path: "/cliente/perfil" },
  { name: "faq",            path: "/preguntas-frecuentes" },
  { name: "terminos",       path: "/terminos" },
  { name: "privacidad",     path: "/privacidad" },
];
// Back-office /admin/* (requiere sesión admin: el cliente 209 = dueño tiene is_admin=true).
const ADMIN_SCREENS = [
  { name: "admin-dashboard", path: "/admin" },
  { name: "admin-pedidos", path: "/admin/pedidos" },
  { name: "admin-pedido-detalle", path: "/admin/pedidos/393" },
  { name: "admin-pedido-nuevo", path: "/admin/pedidos/nuevo" },
  { name: "admin-equipos", path: "/admin/equipos" },
  { name: "admin-equipo-editar", path: "/admin/equipos/213/editar" },
  { name: "admin-equipo-nuevo", path: "/admin/equipos/nuevo" },
  { name: "admin-equipos-calidad", path: "/admin/equipos/calidad" },
  { name: "admin-categorias", path: "/admin/equipos/categorias" },
  { name: "admin-marcas", path: "/admin/equipos/marcas" },
  { name: "admin-equipos-specs", path: "/admin/equipos/specs" },
  { name: "admin-clientes", path: "/admin/clientes" },
  { name: "admin-contabilidad", path: "/admin/contabilidad" },
  { name: "admin-conta-cuentas", path: "/admin/contabilidad/cuentas" },
  { name: "admin-conta-movimientos", path: "/admin/contabilidad/movimientos" },
  { name: "admin-conta-liquidacion", path: "/admin/contabilidad/liquidacion" },
  { name: "admin-conta-reporte", path: "/admin/contabilidad/reporte" },
  { name: "admin-conta-glosario", path: "/admin/contabilidad/glosario" },
  { name: "admin-pagos", path: "/admin/pagos" },
  { name: "admin-estadisticas", path: "/admin/estadisticas" },
  { name: "admin-estudio", path: "/admin/estudio" },
  { name: "admin-talleres", path: "/admin/talleres" },
  { name: "admin-solicitudes", path: "/admin/solicitudes" },
  { name: "admin-settings", path: "/admin/settings" },
  { name: "admin-email-templates", path: "/admin/email-templates" },
  { name: "admin-dataio", path: "/admin/dataio" },
  { name: "admin-diseno", path: "/admin/diseno" },
  { name: "admin-novedades", path: "/admin/novedades" },
  { name: "admin-specs", path: "/admin/specs" },
  { name: "admin-specs-def", path: "/admin/specs/definitions" },
  { name: "admin-unidades", path: "/admin/unidades" },
];
const GROUP_SCREENS = process.env.GROUP === "admin" ? ADMIN_SCREENS : ALL_SCREENS;
const SCREENS = process.env.ROUTES
  ? process.env.ROUTES.split(",").map((p) => ({ name: safe(p), path: p }))
  : process.env.SCREENS
  ? GROUP_SCREENS.filter((s) => process.env.SCREENS.split(",").includes(s.name))
  : GROUP_SCREENS;

// ── Medición in-page: overflow, tap<44, font<min, contraste<AA, truncación ──
export const MEASURE = () => {
  const vw = innerWidth;
  const cv = document.createElement("canvas"); cv.width = cv.height = 1;
  const cx = cv.getContext("2d", { willReadFrequently: true });
  const toRGBA = (s) => { try { cx.clearRect(0,0,1,1); cx.fillStyle = "#000"; cx.fillStyle = s; cx.fillRect(0,0,1,1); const d = cx.getImageData(0,0,1,1).data; return [d[0],d[1],d[2],d[3]/255]; } catch { return null; } };
  const lum = (rgb) => { const [r,g,b] = rgb.map(v=>{v/=255; return v<=.03928? v/12.92 : Math.pow((v+.055)/1.055,2.4);}); return .2126*r+.7152*g+.0722*b; };
  const bgOf = (el) => { let e=el; while(e){ const s=getComputedStyle(e); if(s.backgroundImage && s.backgroundImage!=="none") return "IMAGE"; const c=toRGBA(s.backgroundColor); if(c && c[3]>0.5) return c.slice(0,3); e=e.parentElement; } return [255,255,255]; };
  const contrast = (el) => { const fg=toRGBA(getComputedStyle(el).color); if(!fg) return null; const bg=bgOf(el); if(bg==="IMAGE") return null; const L1=lum(fg.slice(0,3)), L2=lum(bg); const a=Math.max(L1,L2),b=Math.min(L1,L2); return +((a+.05)/(b+.05)).toFixed(2); };
  const inHScroll = (el) => { let p=el.parentElement; while(p){ const c=getComputedStyle(p); if(/(auto|scroll)/.test(c.overflowX) && p.scrollWidth>p.clientWidth+2) return true; p=p.parentElement; } return false; };
  const hitArea = (el) => { for (const pe of ["::before","::after"]) { const s=getComputedStyle(el,pe); if (s.content!=="none" && s.position==="absolute") { const t=parseFloat(s.top)||0,b=parseFloat(s.bottom)||0,l=parseFloat(s.left)||0,r=parseFloat(s.right)||0; if (t<0||b<0||l<0||r<0) return true; } } return false; };

  const tap=[], font=[], contrastBad=[], overflow=[], truncated=[];
  const seen=new Set();
  document.querySelectorAll("button,a,input,select,textarea,[role=button]").forEach(el=>{
    const r=el.getBoundingClientRect(); if(r.width===0||r.height===0) return;
    const cs=getComputedStyle(el); if(cs.visibility==="hidden"||cs.display==="none") return;
    const label=(el.getAttribute("aria-label")||el.textContent||el.placeholder||"").replace(/\s+/g," ").trim().slice(0,28)||"·";
    const k=el.tagName+label+Math.round(r.width)+Math.round(r.height); if(seen.has(k))return; seen.add(k);
    const fs=parseFloat(cs.fontSize), isIn=/INPUT|TEXTAREA|SELECT/.test(el.tagName);
    if((r.width<44||r.height<44) && !hitArea(el)) tap.push({label, w:Math.round(r.width), h:Math.round(r.height)});
    if(fs<(isIn?16:11)) font.push({label, fs});
    if(r.right>vw+2 && !inHScroll(el)) overflow.push({label, right:Math.round(r.right)});
    const txt=(el.textContent||"").trim();
    if(txt && fs<24){ const c=contrast(el); if(c!==null && c<4.5) contrastBad.push({label, c, fs}); }
  });
  document.querySelectorAll("h1,h2,h3,span,p,a,button,div").forEach(el=>{ if(el.children.length===0 && el.scrollWidth>el.clientWidth+2 && el.clientWidth>24){ const t=(el.textContent||"").trim().slice(0,30); if(t && !truncated.includes(t)) truncated.push(t); } });

  const dd=(arr,key)=>{ const m=new Map(); arr.forEach(x=>{ const k=key(x); if(!m.has(k)) m.set(k,x); }); return [...m.values()]; };
  return {
    vw, hScroll: document.documentElement.scrollWidth>vw+1,
    docW: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    interactive: document.querySelectorAll("button,a,input,select,textarea,[role=button]").length,
    tap_lt44: dd(tap, x=>x.label+x.w+x.h).slice(0,30),
    font_lt_min: dd(font, x=>x.label+x.fs).slice(0,20),
    contrast_lt_AA: dd(contrastBad, x=>x.label+x.c).slice(0,20),
    h_overflow: dd(overflow, x=>x.label).slice(0,15),
    truncated: truncated.slice(0,25),
  };
};

// Detector de scroller inyectado en cada página (window.__findAuditScroller) — UNA sola
// implementación, no una copiada en `scrollLoad` y otra en `main` (así se coló el bug real:
// arreglar una copia y no la otra). Excluye `nav`/`aside`/`[role=navigation]` y prefiere el de
// MAYOR área en vez del primero en orden DOM: en `/admin/*` el sidebar aparece antes que el
// contenido en el DOM y tiene su propio `overflow-y:auto` para su lista de nav — sin esto, las
// capturas desktop de TODO el back-office quedaban recortadas al sidebar (bug real, 2026-07-25).
async function installScrollerDetector(page) {
  await page.addInitScript(() => {
    window.__findAuditScroller = () => {
      const candidates = [...document.querySelectorAll("*")].filter((el) => {
        const c = getComputedStyle(el);
        return /(auto|scroll)/.test(c.overflowY) && el.scrollHeight > el.clientHeight + 200;
      });
      const content = candidates.filter((el) => !el.closest("nav, aside, [role='navigation']"));
      const pool = content.length ? content : candidates;
      return pool.sort((a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight)[0] || null;
    };
  });
}

export async function scrollLoad(page) {
  await page.evaluate(async () => {
    const sc = window.__findAuditScroller();
    const max = sc ? sc.scrollHeight : document.body.scrollHeight;
    const step = (sc?sc.clientHeight:innerHeight) * 0.8;
    for (let y=0; y<=max; y+=step){ if(sc) sc.scrollTop=y; else window.scrollTo(0,y); await new Promise(r=>setTimeout(r,250)); }
    if(sc) sc.scrollTop=0; else window.scrollTo(0,0);
    await new Promise(r=>setTimeout(r,300));
  });
  await page.waitForTimeout(400);
}

const main = async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const ctx = await browser.newContext({ deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  await installScrollerDetector(page);
  await page.goto(BASE + "/rental", { waitUntil: "domcontentloaded" });
  let login = "skipped (NOLOGIN)";
  if (!process.env.NOLOGIN) {
    login = await page.evaluate(async ({ SECRET, CLIENTE_ID }) => {
      const r = await fetch("/auth/staging-login", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ secret:SECRET, target:"cliente", cliente_id:CLIENTE_ID }), credentials:"include" });
      const me = await (await fetch("/api/cliente/me",{credentials:"include"})).json().catch(()=>null);
      return { status:r.status, verified: !!(me&&me.dni_validado_at) };
    }, { SECRET, CLIENTE_ID });
  }
  console.log("login:", JSON.stringify(login), "| screens:", SCREENS.length, "× viewports:", VIEWPORTS.length, "=", SCREENS.length*VIEWPORTS.length);

  // merge con corridas previas del mismo LABEL (subsets no pisan el resto)
  const reportPath = resolve(OUT, "_report.json");
  const prev = existsSync(reportPath) ? JSON.parse(readFileSync(reportPath, "utf8")).results || [] : [];
  const merged = new Map(prev.map((r) => [`${r.screen}__${r.w}`, r]));
  const report = { label: LABEL, base: BASE, results: [] };
  for (const { name, path } of SCREENS) {
    for (const w of VIEWPORTS) {
      const tag = `${name}__${w}`;
      try {
        await page.setViewportSize({ width: w, height: H(w) });
        await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 25000 }).catch(()=>{});
        await page.waitForTimeout(700);
        await scrollLoad(page);
        const m = await page.evaluate(MEASURE);
        const innerSel = await page.evaluate(() => { const sc=window.__findAuditScroller(); if(!sc)return null; sc.setAttribute("data-audit-scroller",""); return true; });
        try { if (innerSel) await page.locator("[data-audit-scroller]").first().screenshot({ path: resolve(OUT, tag+".png") }); else await page.screenshot({ path: resolve(OUT, tag+".png"), fullPage: true }); }
        catch { await page.screenshot({ path: resolve(OUT, tag+".png") }); }
        const flags = (m.hScroll?1:0)+m.tap_lt44.length+m.font_lt_min.length+m.contrast_lt_AA.length+m.h_overflow.length;
        merged.set(tag, { screen:name, path, w, screenshot:tag+".png", flags, ...m });
        console.log(`✓ ${tag}  flags=${flags}  tap<44=${m.tap_lt44.length} font=${m.font_lt_min.length} contrast=${m.contrast_lt_AA.length} hScroll=${m.hScroll} overflow=${m.h_overflow.length}`);
      } catch (e) { console.log(`✗ ${tag}  ERROR ${e.message}`); merged.set(tag, { screen:name, path, w, error:e.message }); }
    }
  }
  report.results = [...merged.values()].sort((a,b)=> a.screen.localeCompare(b.screen) || a.w-b.w);
  writeFileSync(resolve(OUT, "_report.json"), JSON.stringify(report, null, 2));
  // _INDEX.md legible: qué screenshot es qué + flags + issues top
  let idx = `# Índice de auditoría UI — \`${LABEL}\`\n\n${SCREENS.length} pantallas × ${VIEWPORTS.length} viewports. Screenshot = \`<pantalla>__<viewport>.png\`.\n\n| Pantalla | Viewport | Screenshot | Flags | hScroll | tap<44 | font | contraste | overflow |\n|---|---|---|---|---|---|---|---|---|\n`;
  for (const r of report.results) {
    if (r.error) { idx += `| ${r.screen} | ${r.w} | — | ERROR | | | | | |\n`; continue; }
    idx += `| ${r.screen} (${r.path}) | ${r.w} | \`${r.screenshot}\` | ${r.flags} | ${r.hScroll?"⚠️":"✅"} | ${r.tap_lt44.length} | ${r.font_lt_min.length} | ${r.contrast_lt_AA.length} | ${r.h_overflow.length} |\n`;
  }
  writeFileSync(resolve(OUT, "_INDEX.md"), idx);
  console.log("\nReport:", resolve(OUT, "_report.json"), "\nÍndice:", resolve(OUT, "_INDEX.md"), "\nScreenshots:", OUT);
  await browser.close();
};

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
