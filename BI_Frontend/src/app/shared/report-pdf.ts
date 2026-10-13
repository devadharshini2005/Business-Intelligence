/**
 * Turns one assistant answer into a printable A4 report and opens the browser's print dialog, where
 * "Save as PDF" produces the file. Printing (not a canvas capture) keeps the text selectable and the
 * SVG charts sharp. The answer's rendered DOM is cloned into a hidden iframe with the app's styles.
 *
 * The pages are laid out here, not by the browser: the browser prints its own header and footer (date,
 * title, URL, page number) in any page margin with room for them, even when the page defines its own.
 * So the page margins are 0 and each A4 sheet is a fixed-size box with its own "Page n of N" footer.
 */

export interface ReportInput {
  /** The rendered answer: markdown block and charts, cloned as they are on screen. */
  content: HTMLElement;
}

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));

// A4 sheet, in mm. Content fills the sheet minus the padding; the footer sits in the bottom padding.
const PAGE_W = 210;
const PAGE_H = 296.5;  // a hair under 297 so rounding never spills a sheet onto an extra page
const PAD_Y = 16;
const PAD_X = 14;
const PX_PER_MM = 96 / 25.4;
const USABLE_PX = (PAGE_H - 2 * PAD_Y) * PX_PER_MM * 0.95;  // 5% slack for screen vs print layout differences

const REPORT_CSS = `
  @page { size: A4; margin: 0; }
  html, body { background: #fff !important; }
  body { margin: 0; color: #1b1b22; font-size: 13px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .rp-measure { width: ${PAGE_W - 2 * PAD_X}mm; }
  .rp-sheet { box-sizing: border-box; width: ${PAGE_W}mm; height: ${PAGE_H}mm; padding: ${PAD_Y}mm ${PAD_X}mm;
              position: relative; overflow: hidden; break-after: page; }
  .rp-sheet:last-child { break-after: auto; }
  .rp-pnum { position: absolute; left: 0; right: 0; bottom: 7mm; text-align: center; font-size: 10px; color: #8a8a96; }
  .rp-head { display: flex; align-items: center; gap: 12px; padding-bottom: 10px; margin-bottom: 16px; border-bottom: 2px solid #5b4fd6; }
  .rp-head img { width: 34px; height: 34px; object-fit: contain; }
  .rp-brand { font-size: 18px; font-weight: 600; color: #4a3fc4; }
  .rp-sub { font-size: 11px; color: #6b6b78; }
  .md { font-size: 13px; line-height: 1.55; }
  .cc { margin: 14px 0; }
  .table-wrap { overflow: visible !important; max-height: none !important; }
  button, details > summary { display: none !important; }
`;

/** Resolves when every stylesheet in the document has loaded (or after a short timeout). */
function stylesLoaded(doc: Document): Promise<void> {
  const links = [...doc.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')];
  const each = links.map((l) => new Promise<void>((done) => {
    if (l.sheet) return done();
    l.addEventListener('load', () => done(), { once: true });
    l.addEventListener('error', () => done(), { once: true });
  }));
  return Promise.race([Promise.all(each).then(() => undefined), new Promise<void>((r) => setTimeout(r, 3000))]);
}

/** Height of an element including its vertical margins. */
function outerHeight(el: Element): number {
  const cs = el.ownerDocument.defaultView!.getComputedStyle(el);
  return el.getBoundingClientRect().height + (parseFloat(cs.marginTop) || 0) + (parseFloat(cs.marginBottom) || 0);
}

/** A piece of content placed on a sheet; `md` pieces are re-wrapped in .md so markdown styles still apply. */
interface Piece { el: HTMLElement; md: boolean; }

/**
 * Split a block taller than a page (a table or list, or a chart holding a table) into pieces: the first fits
 * `first` px (the room left on the current sheet), the rest a full sheet each. Returns null if it can't.
 */
function splitBlock(block: HTMLElement, first: number): HTMLElement[] | null {
  const target = block.matches('table, ul, ol') ? block : block.querySelector<HTMLElement>('table');
  if (!target) return null;
  const items = target.matches('table')
    ? [...target.querySelectorAll<HTMLElement>(':scope > tbody > tr')]
    : [...target.children] as HTMLElement[];
  if (items.length < 2) return null;
  const heights = items.map(outerHeight);
  const overhead = outerHeight(block) - heights.reduce((a, b) => a + b, 0);  // header row, title, padding

  const ranges: [number, number][] = [];
  let start = 0, room = first, used = overhead;
  for (let i = 0; i < items.length; i++) {
    if (used + heights[i] > room && i > start) {
      ranges.push([start, i]);
      start = i; room = USABLE_PX; used = overhead;
    }
    used += heights[i];
  }
  ranges.push([start, items.length]);

  return ranges.map(([from, to]) => {
    const copy = block.cloneNode(true) as HTMLElement;
    const t = copy.matches('table, ul, ol') ? copy : copy.querySelector<HTMLElement>('table')!;
    const own = t.matches('table') ? [...t.querySelectorAll(':scope > tbody > tr')] : [...t.children];
    own.forEach((el, i) => { if (i < from || i >= to) el.remove(); });
    if (t.matches('ol') && from > 0) t.setAttribute('start', String(from + 1));
    return copy;
  });
}

/** Distribute the measured header and answer blocks over A4 sheets. */
function paginate(header: HTMLElement, body: HTMLElement): Piece[][] {
  const blocks: Piece[] = [];
  for (const el of [...body.children] as HTMLElement[]) {
    if (el.classList.contains('md')) blocks.push(...([...el.children] as HTMLElement[]).map((c) => ({ el: c, md: true })));
    else blocks.push({ el, md: false });
  }
  const heights = new Map(blocks.map((b) => [b.el, outerHeight(b.el)]));

  const pages: Piece[][] = [[{ el: header, md: false }]];
  let used = outerHeight(header);
  const newPage = () => { pages.push([]); used = 0; };

  blocks.forEach((b, i) => {
    const h = heights.get(b.el)!;
    const next = blocks[i + 1];
    // Keep a heading with (the start of) what follows it.
    const keepWith = /^H[1-6]$/.test(b.el.tagName) && next ? Math.min(heights.get(next.el)!, USABLE_PX / 4) : 0;
    if (used + h + keepWith <= USABLE_PX) {
      pages.at(-1)!.push(b); used += h;
      return;
    }
    if (h > USABLE_PX) {
      const room = USABLE_PX - used;
      const startHere = room > USABLE_PX / 5;
      const parts = splitBlock(b.el, startHere ? room : USABLE_PX);
      if (parts) {
        if (!startHere) newPage();
        parts.forEach((p, j) => {
          if (j > 0) newPage();
          pages.at(-1)!.push({ el: p, md: b.md });
        });
        used = USABLE_PX;  // the last part may be short, but measuring it again isn't worth it
        return;
      }
    }
    if (used > 0) newPage();
    pages.at(-1)!.push(b); used += h;
  });
  return pages;
}

export async function printReport({ content }: ReportInput): Promise<void> {
  const now = new Date();
  const stamp = now.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  // The print dialog suggests the document title as the PDF file name: use the report's own first heading.
  const heading = content.querySelector('.md h1, .md h2, .md h3')?.textContent ?? '';
  const name = heading.replace(/\s+/g, ' ').trim().slice(0, 80).replace(/[\\/:*?"<>|]/g, '') || 'Assistant report';
  const title = `Actuvara - ${name} - ${now.toISOString().slice(0, 10)}`;

  // Same styles as the app (charts, tables and markdown look as on screen), absolute so the iframe finds them.
  const styles = [...document.querySelectorAll<HTMLElement>('link[rel="stylesheet"], style')].map((el) =>
    el instanceof HTMLLinkElement ? `<link rel="stylesheet" href="${esc(el.href)}">` : el.outerHTML).join('\n');
  const logo = new URL('logo.png', document.baseURI).href;

  const answer = content.cloneNode(true) as HTMLElement;
  answer.querySelectorAll('.steps, .msg-actions, button').forEach((el) => el.remove());

  // First lay everything out in one column of the sheet's content width, to measure it.
  const html = `<!doctype html><html lang="en" data-theme="light"><head><meta charset="utf-8">
    <title>${esc(title)}</title>${styles}<style>${REPORT_CSS}</style></head>
    <body><div class="rp-measure">
      <header class="rp-head"><img src="${esc(logo)}" alt="">
        <div><div class="rp-brand">Actuvara BI</div><div class="rp-sub">Assistant report · generated ${esc(stamp)}</div></div>
      </header>
      <main class="rp-body">${answer.innerHTML}</main>
    </div></body></html>`;

  const frame = document.createElement('iframe');
  frame.setAttribute('aria-hidden', 'true');
  // Real A4 size, off screen, so the measuring layout matches the printed one.
  frame.style.cssText = `position:fixed;left:-10000px;top:0;width:${PAGE_W}mm;height:${PAGE_H}mm;border:0;visibility:hidden`;
  document.body.appendChild(frame);
  const win = frame.contentWindow!;
  const doc = win.document;
  doc.open();
  doc.write(html);
  doc.close();

  await stylesLoaded(doc);
  await Promise.all([...doc.images].map((img) => img.complete ? null
    : new Promise((r) => { img.onload = img.onerror = r; })));
  await doc.fonts?.ready;

  // Then move the measured blocks onto A4 sheets, each with its page number.
  const pages = paginate(doc.querySelector<HTMLElement>('.rp-head')!, doc.querySelector<HTMLElement>('.rp-body')!);
  const sheets = pages.map((pieces, i) => {
    const sheet = doc.createElement('section');
    sheet.className = 'rp-sheet';
    let md: HTMLElement | null = null;
    for (const p of pieces) {
      if (!p.md) { sheet.appendChild(p.el); md = null; continue; }
      if (!md) { md = doc.createElement('div'); md.className = 'md'; sheet.appendChild(md); }
      md.appendChild(p.el);
    }
    const num = doc.createElement('div');
    num.className = 'rp-pnum';
    num.textContent = `Page ${i + 1} of ${pages.length}`;
    sheet.appendChild(num);
    return sheet;
  });
  doc.body.replaceChildren(...sheets);

  const cleanup = () => setTimeout(() => frame.remove(), 500);
  win.addEventListener('afterprint', cleanup, { once: true });
  setTimeout(() => frame.isConnected && frame.remove(), 10 * 60_000);  // fallback if afterprint never fires
  win.focus();
  win.print();
}
