// Records a demo video of a full SDLC flow running in parallel on three projects (ירפא, כללית, מאוחדת).
// It starts its own flow desk on a throwaway workbook, drives it, and records the browser.
// Run: node demo-video/source/record.mjs
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { spawn, execFileSync } from 'node:child_process'

const require = createRequire('C:/whatapPos/tests/e2e-scenarios/package.json')
const { chromium } = require('@playwright/test')

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const ROOT = path.resolve(HERE, '..', '..')
const OUT = path.resolve(HERE, '..')
const PORT = 8795
const API = `http://127.0.0.1:${PORT}`
const DATA = path.join(HERE, 'demo-data.xlsx')
const ACTIVE = ['ירפא', 'כללית', 'מאוחדת']
const W = 1600, H = 900

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const SETTLE = 2800 // the page polls every 2s

// ---------- server on a throwaway workbook
for (const f of [DATA + '.lock', DATA + '.tmp']) fs.rmSync(f, { force: true }) // leftovers of a killed earlier run
execFileSync('python', [path.join(HERE, 'prepare.py'), DATA], { stdio: 'inherit', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
const server = spawn('python', [path.join(ROOT, 'dashboard', 'server.py'), '--port', String(PORT), '--data', DATA], { stdio: ['ignore', fs.openSync(path.join(HERE, 'server.log'), 'w'), fs.openSync(path.join(HERE, 'server.log'), 'a')] })
const t0 = Date.now()
server.on('exit', (c, sig) => console.error('SERVER EXITED code=%s signal=%s after %ss', c, sig, ((Date.now() - t0) / 1000).toFixed(1)))
for (let i = 0; i < 50; i++) { try { await fetch(API + '/api/state'); break } catch { await sleep(200) } }

const state = async () => (await fetch(API + '/api/state')).json()
const post = async (p, b) => { const r = await fetch(API + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }); if (!r.ok) throw new Error(p + ' ' + r.status + ' ' + await r.text()); }

let S = await state()
const proj = Object.fromEntries(S.projects.map((p) => [p.name, p]))
const mod = Object.fromEntries(S.modules.map((m) => [m.id, m.name]))
const WHO = ['דרור', 'אייל', 'אדיר', 'שמעון', 'נחום', 'נחום']
const cells = [] // every task of the three projects
for (const n of ACTIVE) for (const m of proj[n].modules) cells.push({ p: proj[n], m, name: n })
const act = (c, action, stage = 0, note = '') => post('/api/cell', { project: c.p.id, module: c.m, action, stage, who: WHO[stage], note })

// ---------- browser
const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: W, height: H }, locale: 'he-IL', recordVideo: { dir: path.join(HERE, 'rec'), size: { width: W, height: H } } })
const page = await context.newPage()

// caption bar and fake cursor live in the top layer (popover) so they stay above open dialogs
await page.addInitScript(() => {
  window.__cap = (title, text) => {
    let el = document.getElementById('__cap')
    if (!el) {
      el = document.createElement('div'); el.id = '__cap'; el.setAttribute('popover', 'manual')
      el.style.cssText = 'position:fixed;inset:auto 0 0 0;margin:0;width:100%;border:0;padding:16px 40px 20px;background:rgba(15,25,35,.94);color:#fff;direction:rtl;font:600 28px/1.35 Segoe UI,Arial,sans-serif;box-sizing:border-box'
      document.body.appendChild(el)
    }
    el.innerHTML = '<div style="font-size:19px;font-weight:600;color:#7fd4ff;margin-bottom:2px">' + title + '</div>' + text
    try { el.hidePopover() } catch (e) {}
    el.showPopover()
  }
  window.__top = () => { for (const id of ['__cap', '__cur']) { const e = document.getElementById(id); if (e) { try { e.hidePopover() } catch (x) {} e.showPopover() } } }
  document.addEventListener('DOMContentLoaded', () => {
    document.body.style.zoom = '0.86'
    const cur = document.createElement('div'); cur.id = '__cur'; cur.setAttribute('popover', 'manual')
    cur.style.cssText = 'position:fixed;inset:0 auto auto 0;margin:0;width:22px;height:22px;border-radius:50%;background:rgba(255,70,70,.85);border:3px solid #fff;pointer-events:none;box-shadow:0 0 0 3px rgba(255,70,70,.35);transform:translate(-50%,-50%)'
    document.body.appendChild(cur); cur.showPopover()
    document.addEventListener('mousemove', (e) => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; window.__top() }, true)
  })
})
await page.goto(`http://localhost:${PORT}/`)
await page.waitForSelector('.c')
const caption = (title, text) => page.evaluate(([t, x]) => window.__cap(t, x), [title, text])

async function click(sel) {
  const box = await page.locator(sel).first().boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 28 })
  await sleep(450)
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
}
const tile = (c) => `.c[data-p="${c.p.id}"][data-m="${c.m}"]`

// ---------- the story
try {
await caption('הדגמה: ניהול זרימת פיתוח', '9 פרויקטים × תתי מודולים, כל תא הוא משימה שעוברת 6 שלבים. נריץ במקביל שלושה פרויקטים: <b>ירפא, כללית, מאוחדת</b>')
await sleep(7000)
await caption('הצבעים', 'אדום: לא התחיל · תכלת: בתהליך עבודה · ירוק: הסתיים. תא מקווקו הוא תת מודול שלא משויך לפרויקט')
await sleep(6000)

// real clicks on the first task
const first = cells[0]
await caption('לוחצים על תא ופותחים את המשימה', `${first.name} / ${mod[first.m]}: ששת השלבים, ולכל שלב עובד אחראי`)
await click(tile(first)); await sleep(5000)
await caption('התחלת הזרם', 'בעל התפקיד מפעיל את הזרם בלחיצה')
await click('#dCell [data-a="start"]'); await sleep(SETTLE)
await caption('שלב 1: מנהל מוצר', 'דרור מסיים את האיפיון ולוחץ "סיים איפיון". רק אחרי הלחיצה התא עובר לשלב הבא')
await click('#dCell [data-a="complete"][data-k="0"]'); await sleep(SETTLE + 1200)
await click('#dCell [data-close]'); await sleep(800)

await caption('מפעילים את שאר המשימות', 'כל תתי המודולים של שלושת הפרויקטים מתחילים במקביל, כל אחד עם דרור במנהל מוצר')
await Promise.all(cells.slice(1).map((c) => act(c, 'start')))
await sleep(SETTLE + 2500)

const wave = async (stage, title, text, only = cells) => {
  await caption(title, text)
  await sleep(2500)
  S = await state()
  const ready = only.filter((c) => S.cells[c.p.id + ':' + c.m].stages[stage] === 'run')
  await Promise.all(ready.map((c) => act(c, 'complete', stage)))
  await sleep(SETTLE + 2200)
}
await wave(0, 'שלב 1: מנהל מוצר', 'דרור סוגר את האיפיון בשאר המשימות. כולן עוברות לשלב מוכנות הקוד')
await wave(1, 'שלב 2: מוכנות Source Code', 'אייל מאשר שה-source code מוכן לפני שסוכן ה-AI מתחיל לעבוד')
await wave(2, 'שלב 3: פיתוח AI', 'אדיר מריץ את סוכן ה-AI Dev מחוץ למערכת, ומעדכן כשהסוכן סיים')

// dev finds a problem in one task and sends it back
const bad = cells.find((c) => c.name === 'כללית' && mod[c.m] === 'הכנסה לסל')
await caption('שלב 4: מפתח', 'שמעון בודק שהקוד שה-AI יצר עובד ותקין לפי הגדרת הצרכים')
await sleep(2500)
await Promise.all(cells.filter((c) => c !== bad).map((c) => act(c, 'complete', 3)))
await sleep(SETTLE + 1500)
await caption('מצאו תקלה', 'בכללית / הכנסה לסל שמעון מצא תקלה ומחזיר ל-AI Dev עם הערה. התא נשאר תכלת וחוזר לשלב הקודם')
await act(bad, 'back', 3, 'הקוד לא מטפל במרשם ללא מספר רופא')
await sleep(SETTLE + 4500)
await caption('התיקון', 'אדיר מריץ שוב את סוכן ה-AI, ושמעון בודק ומאשר')
await act(bad, 'complete', 2); await sleep(SETTLE + 1500)
await act(bad, 'complete', 3); await sleep(SETTLE + 1500)

// employee filter before QA
await caption('מסנן לפי עובד', 'נחום בוחר את שמו ורואה בדשבורד רק את המשימות שממתינות לו. כל השאר מעומעמות')
await page.selectOption('#who-filter', 'נחום'); await sleep(6500)
await wave(4, 'שלב 5: QA', 'נחום מבצע את בדיקות ה-QA לכל תת מודול')
await page.selectOption('#who-filter', ''); await sleep(800)
await wave(5, 'שלב 6: בדיקה קצה לקצה לתת מודול', 'נחום בודק כל תת מודול מקצה לקצה. התא הופך ירוק רק אחרי שלב זה')

// project-level end to end
await caption('בדיקה קצה לקצה לפרויקט', 'כשכל תתי המודולים של פרויקט הסתיימו, נפתחת בעמודה האחרונה בדיקה של כל הפרויקט כמערכת אחת (תכלת)')
await sleep(7000)
const failing = cells.find((c) => c.name === 'מאוחדת')
await caption('הבדיקה נכשלה', `במאוחדת נחום מוצא שאחד התתי מודולים לא מתחבר לסיום. הוא פותח מחדש את "${mod[failing.m]}" בשלב QA והאישור של הפרויקט מבוטל`)
await act(failing, 'reopen', 4, 'בבדיקה קצה לקצה: הנתונים לא עוברים לשלב הבא'); await sleep(SETTLE + 5000)
await caption('התיקון עובר שוב את השלבים', 'QA ובדיקה קצה לקצה של אותו תת מודול, ואז הבדיקה של הפרויקט נפתחת מחדש')
await act(failing, 'complete', 4); await sleep(SETTLE)
await act(failing, 'complete', 5); await sleep(SETTLE + 1500)

await caption('אישור לפרודקשיין', 'נחום פותח את בדיקת הפרויקט כללית ומאשר שהכול עובד ותקין')
await click(`[data-e="${proj['כללית'].id}"]`); await sleep(5000)
await click('#dE2E [data-e2e]'); await sleep(SETTLE + 1000)
await click('#dE2E [data-close]'); await sleep(800)
await caption('אותו דבר בשאר הפרויקטים', 'ירפא ומאוחדת מאושרים אחרי בדיקת הפרויקט')
await post('/api/project/e2e', { id: proj['ירפא'].id, who: 'נחום' })
await post('/api/project/e2e', { id: proj['מאוחדת'].id, who: 'נחום' })
await sleep(SETTLE + 3500)

const total = cells.length
await caption('סיום', `שלושת הפרויקטים מאושרים לפרודקשיין: ${total} תתי מודולים, ${total * 6} שלבים, הכול נשמר בקובץ האקסל. שאר הפרויקטים לא נפגעו`)
await sleep(9000)

} catch (e) { console.error('FAILED after %ss:', ((Date.now() - t0) / 1000).toFixed(1), e.stack, e.cause); process.exitCode = 1 } finally {
  await context.close().catch(() => {})
  await browser.close().catch(() => {})
  server.kill()
}
if (process.exitCode) process.exit(1)
const rec = fs.readdirSync(path.join(HERE, 'rec')).filter((f) => f.endsWith('.webm')).map((f) => path.join(HERE, 'rec', f)).sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)[0]
const webm = path.join(OUT, 'parallel-3-projects-demo.webm')
fs.copyFileSync(rec, webm)
console.log('video:', webm, (fs.statSync(webm).size / 1e6).toFixed(1) + ' MB')
