// Demo video: three projects run in parallel, cell colors follow the stage, and every hand-over is an e-mail with
// an approve link. The next owner opens the link, presses approve, and the dashboard updates by itself.
// Layout: dashboard | inbox | the recipient's browser. Run: node demo-video/source/record-mail.mjs
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { spawn, execFileSync } from 'node:child_process'

const require = createRequire('C:/whatapPos/tests/e2e-scenarios/package.json')
const { chromium } = require('@playwright/test')

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const ROOT = path.resolve(HERE, '..', '..')
const OUT = path.resolve(HERE, '..')
const PORT = 8795, MPORT = 8801
const API = `http://127.0.0.1:${PORT}`
const DATA = path.join(HERE, 'demo-data.xlsx')
const OUTBOX = path.join(HERE, 'outbox')
const ACTIVE = ['ירפא', 'כללית', 'מאוחדת']
const W = 1600, H = 900
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const SETTLE = 2800 // the dashboard polls every 2s

// ---------- servers (throwaway workbook, mails go to the outbox folder, nothing leaves the machine)
for (const f of [DATA, DATA + '.lock', DATA + '.tmp', path.join(HERE, 'mail.json')]) fs.rmSync(f, { force: true })
fs.rmSync(OUTBOX, { recursive: true, force: true })
execFileSync('python', [path.join(HERE, 'prepare.py'), DATA], { stdio: 'inherit', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
const log = (n) => fs.openSync(path.join(HERE, n), 'w')
const flow = spawn('python', [path.join(ROOT, 'dashboard', 'server.py'), '--port', String(PORT), '--data', DATA], { stdio: ['ignore', log('server.log'), log('server.log')] })
const mbox = spawn('python', [path.join(HERE, 'mailbox.py'), '--port', String(MPORT), '--outbox', OUTBOX, '--dash', String(PORT)], { stdio: ['ignore', log('mailbox.log'), log('mailbox.log')] })
for (let i = 0; i < 60; i++) { try { await fetch(API + '/api/state'); await fetch(`http://127.0.0.1:${MPORT}/idle`); break } catch { await sleep(200) } }

const state = async () => (await fetch(API + '/api/state')).json()
const mails = async () => (await fetch(`http://127.0.0.1:${MPORT}/mails.json`)).json()
const post = async (p, b) => { const r = await fetch(API + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }); if (!r.ok) throw new Error(p + ' ' + r.status + ' ' + await r.text()) }

let S = await state()
const proj = Object.fromEntries(S.projects.map((p) => [p.name, p]))
const mod = Object.fromEntries(S.modules.map((m) => [m.id, m.name]))
const STAGE = S.stages.map((s) => s.name)
const WHO = ['דרור', 'אייל', 'אדיר', 'שמעון', 'נחום', 'נחום']
const COLOR = ['כחול', 'סגול', 'כתום', 'צהוב', 'ורוד', 'טורקיז']
const cells = []
for (const n of ACTIVE) for (const m of proj[n].modules) cells.push({ p: proj[n], m, name: n })
const demo = cells[0] // the task followed through every mail
const others = cells.slice(1)
const act = (c, action, stage = 0, note = '') => post('/api/cell', { project: c.p.id, module: c.m, action, stage, who: WHO[stage], note })

let browser, context
try {
  browser = await chromium.launch()
  context = await browser.newContext({ viewport: { width: W, height: H }, locale: 'he-IL', recordVideo: { dir: path.join(HERE, 'rec'), size: { width: W, height: H } } })
  const page = await context.newPage()

  // top frame: caption bar + fake cursor (top layer, so they sit above the iframes); dashboard frame: zoomed to fit its pane
  await page.addInitScript(({ PORT }) => {
    if (window.top === window) {
      window.__cap = (title, text) => {
        let el = document.getElementById('__cap')
        if (!el) {
          el = document.createElement('div'); el.id = '__cap'; el.setAttribute('popover', 'manual')
          el.style.cssText = 'position:fixed;inset:auto 0 0 0;margin:0;width:100%;border:0;padding:14px 40px 18px;background:rgba(15,25,35,.95);color:#fff;direction:rtl;font:600 26px/1.35 Segoe UI,Arial,sans-serif;box-sizing:border-box'
          document.body.appendChild(el)
        }
        el.innerHTML = '<div style="font-size:18px;font-weight:600;color:#7fd4ff;margin-bottom:2px">' + title + '</div>' + text
        try { el.hidePopover() } catch (e) {}
        el.showPopover()
        window.__cur(window.__cx || 800, window.__cy || 450)
      }
      window.__cur = (x, y) => {
        window.__cx = x; window.__cy = y
        let c = document.getElementById('__cur')
        if (!c) {
          c = document.createElement('div'); c.id = '__cur'; c.setAttribute('popover', 'manual')
          c.style.cssText = 'position:fixed;inset:0 auto auto 0;margin:0;width:22px;height:22px;border-radius:50%;background:rgba(255,70,70,.85);border:3px solid #fff;pointer-events:none;box-shadow:0 0 0 3px rgba(255,70,70,.35);transform:translate(-50%,-50%)'
          document.body.appendChild(c)
        }
        c.style.left = x + 'px'; c.style.top = y + 'px'
        try { c.hidePopover() } catch (e) {}
        c.showPopover()
      }
    } else if (location.port === String(PORT) && !location.pathname.startsWith('/approve')) {
      document.addEventListener('DOMContentLoaded', () => { document.body.style.zoom = '0.6' })
    }
  }, { PORT })
  await page.goto(`http://127.0.0.1:${MPORT}/wrapper`)
  const has = async (f, sel) => { try { return !!(f && (await f.$(sel))) } catch { return false } } // the frame navigates while we poll
  const dash = () => page.frames().find((f) => f.url().startsWith(`http://localhost:${PORT}/`) && !f.url().includes('/approve'))
  const mailFrame = () => page.frames().find((f) => f.url().includes('/mailbox'))
  const apvFrame = () => page.frames().find((f) => f.url().includes('/approve'))
  for (let i = 0; i < 50 && !(await has(dash(), '.c')); i++) await sleep(200)
  const caption = (title, text) => page.evaluate(([t, x]) => window.__cap(t, x), [title, text])

  let pos = { x: 800, y: 450 }
  async function moveTo(x, y, steps = 22) {
    for (let i = 1; i <= steps; i++) {
      const px = pos.x + ((x - pos.x) * i) / steps, py = pos.y + ((y - pos.y) * i) / steps
      await page.mouse.move(px, py)
      await page.evaluate(([a, b]) => window.__cur(a, b), [px, py])
    }
    pos = { x, y }
  }
  async function click(loc) {
    await loc.scrollIntoViewIfNeeded()
    const b = await loc.boundingBox()
    await moveTo(b.x + b.width / 2, b.y + b.height / 2)
    await sleep(450)
    await page.mouse.click(b.x + b.width / 2, b.y + b.height / 2)
  }
  const waitMail = async (needle) => { for (let i = 0; i < 60; i++) { if ((await mails()).some((m) => m.subject.includes(needle))) return; await sleep(200) } throw new Error('no mail: ' + needle) }
  const subjectOf = (c, stageIdx) => `${c.name} / ${mod[c.m]}: ממתין לך שלב ${STAGE[stageIdx]}`

  // ---------- story
  await caption('הדגמה: מספר פרויקטים במקביל, צבע לפי שלב, ואישור במייל', 'ירפא, כללית ומאוחדת רצים יחד. בכל מעבר שלב נשלח מייל לבעל התפקיד הבא עם קישור, והאישור שלו מעדכן את הדשבורד')
  await sleep(8000)
  await caption('הצבעים במסך הראשי', 'לכל שלב צבע משלו: כחול מנהל מוצר · סגול מוכנות קוד · כתום פיתוח AI · צהוב מפתח · ורוד QA · טורקיז בדיקה קצה לקצה · ירוק הסתיים · אפור לא התחיל')
  await sleep(8000)

  await caption('מפעילים Flow בשלושה פרויקטים', 'כל תתי המודולים של ירפא, כללית ומאוחדת מתחילים במקביל. התאים עוברים מאפור לכחול, וכל אחד שולח מייל לדרור, מנהל המוצר')
  await Promise.all(cells.map((c) => act(c, 'start')))
  await waitMail(subjectOf(demo, 0))
  await sleep(SETTLE + 2500)

  for (let k = 0; k < 6; k++) {
    const owner = WHO[k], subj = subjectOf(demo, k)
    await waitMail(subj)
    await caption(`מייל ל${owner}: ${STAGE[k]}`, `${demo.name} / ${mod[demo.m]} הגיע לשלב ${STAGE[k]}. ${owner} מקבל מייל עם קישור לאישור`)
    await mailFrame().evaluate((n) => window.__show(n), subj)
    await sleep(4200)
    await caption(`${owner} לוחץ על הקישור במייל`, 'הקישור פותח דף אישור בדפדפן. הפתיחה לבדה לא משנה כלום')
    await click(mailFrame().locator('#mail a').first())
    for (let i = 0; i < 40 && !(await has(apvFrame(), 'button')); i++) await sleep(200)
    await sleep(3000)
    await caption(`${owner} מאשר סיום שלב`, `לחיצה על "אשר" סוגרת את השלב ב-${STAGE[k]} ומעדכנת את המערכת אוטומטית`)
    await click(apvFrame().locator('button[type=submit]'))
    await sleep(SETTLE + 1500)
    if (k < 5) {
      await caption('הצבע התחלף', `${demo.name} / ${mod[demo.m]} עבר לשלב ${STAGE[k + 1]}, ולכן הוא ${COLOR[k + 1]}. נשלח מייל לבעל התפקיד הבא (${WHO[k + 1]})`)
      await sleep(4500)
    }
    // in parallel the other tasks of the three projects advance one stage, each handing over by mail
    S = await state()
    const ready = others.filter((c) => S.cells[c.p.id + ':' + c.m].stages[k] === 'run')
    if (k === 5) {
      await caption('בו זמנית: כל שאר המשימות מסיימות', 'שאר תתי המודולים של שלושת הפרויקטים מסיימים את בדיקת הקצה לקצה, והתאים הופכים לירוק')
    } else {
      await caption(`במקביל, בשאר הפרויקטים`, `שאר המשימות של שלושת הפרויקטים מתקדמות לשלב ${STAGE[k + 1]} (${COLOR[k + 1]}). כל מעבר שולח מייל לבעל התפקיד הבא`)
    }
    await Promise.all(ready.map((c) => act(c, 'complete', k)))
    await sleep(SETTLE + 3500)
  }

  // ---------- project-level check by mail
  const pj = (n) => `${n}: בדיקה קצה לקצה לפרויקט ממתינה לך`
  await waitMail(pj('ירפא'))
  await caption('כל תתי המודולים הסתיימו', 'כשהמשימה האחרונה בפרויקט מסתיימת, נחום (QA) מקבל מייל לבדיקה קצה לקצה של הפרויקט כולו. עמודת הפרויקט צבועה בצבע בדיקת הקצה לקצה')
  await mailFrame().evaluate((n) => window.__show(n), pj('ירפא'))
  await sleep(6500)
  await caption('נחום לוחץ על הקישור', 'דף האישור של הפרויקט נפתח, ונחום מאשר שהכול עובד ותקין')
  await click(mailFrame().locator('#mail a').first())
  for (let i = 0; i < 40 && !(await has(apvFrame(), 'button')); i++) await sleep(200)
  await sleep(3200)
  await click(apvFrame().locator('button[type=submit]'))
  await sleep(SETTLE + 2500)
  await caption('הפרויקט אושר לפרודקשיין', 'ירפא ירוק במסך הראשי, ובעמודה האחרונה כתוב "מאושר לפרודקשיין". כך אושרו גם כללית ומאוחדת')
  await post('/api/project/e2e', { id: proj['כללית'].id, who: 'נחום (דרך המייל)' })
  await post('/api/project/e2e', { id: proj['מאוחדת'].id, who: 'נחום (דרך המייל)' })
  await sleep(SETTLE + 4500)

  const total = cells.length
  await caption('סיכום', `3 פרויקטים, ${total} תתי מודולים, ${total * 6} שלבים. כל מעבר שלב נשלח כמייל עם קישור, כל אישור עדכן את המסך הראשי, והכול נשמר בקובץ האקסל`)
  await sleep(9000)
} catch (e) {
  console.error('FAILED:', e.stack)
  process.exitCode = 1
} finally {
  await context?.close().catch(() => {})
  await browser?.close().catch(() => {})
  flow.kill(); mbox.kill()
}
if (process.exitCode) process.exit(1)
const rec = fs.readdirSync(path.join(HERE, 'rec')).filter((f) => f.endsWith('.webm')).map((f) => path.join(HERE, 'rec', f)).sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)[0]
const webm = path.join(OUT, (process.env.DEMO_NAME || 'demo-3-projects-mail-v3') + '.webm')
fs.copyFileSync(rec, webm)
console.log('video:', webm, (fs.statSync(webm).size / 1e6).toFixed(1) + ' MB')
