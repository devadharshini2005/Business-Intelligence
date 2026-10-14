/**
 * Excel export of a chat answer: the question and answer, one sheet per chart or table, and the database
 * steps behind it. `exceljs` is imported on first use only, so it is not part of the initial download.
 */
import type { Workbook } from 'exceljs';

import { ChartSpec, ChatMessage } from './models';

const HEADER_FILL = { type: 'pattern' as const, pattern: 'solid' as const, fgColor: { argb: 'FFE0F2F3' } };
const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?$/;

/** Download `message` (an assistant answer) as an .xlsx file. `question` is the user turn it answers. */
export async function downloadAnswerWorkbook(question: string, message: ChatMessage): Promise<void> {
  // exceljs is CommonJS: depending on the bundler its exports arrive as named exports or under `default`.
  const mod = (await import('exceljs')) as unknown as { Workbook?: new () => Workbook; default?: { Workbook: new () => Workbook } };
  const WorkbookCtor = mod.Workbook ?? mod.default!.Workbook;
  const wb: Workbook = new WorkbookCtor();
  wb.creator = 'Actuvara BI';
  wb.created = new Date();

  answerSheet(wb, question, message);
  const used = new Set<string>(['answer', 'queries']); // lower-case: Excel compares names without case
  for (const chart of message.charts ?? []) {
    if (chart.type === 'error') continue;
    chartSheet(wb, chart, sheetName(chart.title, used));
  }
  if (message.steps?.length) queriesSheet(wb, message);

  const buffer = await wb.xlsx.writeBuffer();
  const url = URL.createObjectURL(
    new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
  );
  const a = document.createElement('a');
  a.href = url;
  a.download = `${fileStem(question)}.xlsx`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function answerSheet(wb: Workbook, question: string, m: ChatMessage): void {
  const ws = wb.addWorksheet('Answer');
  ws.columns = [{ width: 16 }, { width: 110 }];
  const rows: [string, string | Date][] = [
    ['Question', question],
    ['Answered', m.at ? new Date(m.at) : new Date()],
    ['Answer', plainText(m.content)],
  ];
  if (m.followUps?.length) rows.push(['Follow-ups', m.followUps.join('\n')]);
  rows.push(['Source', 'Actuvara BI - read-only queries through the MCP server (intellidoc database)']);
  for (const [label, value] of rows) {
    const row = ws.addRow([label, value]);
    row.getCell(1).font = { bold: true };
    row.getCell(2).alignment = { wrapText: true, vertical: 'top' };
    row.getCell(1).alignment = { vertical: 'top' };
    if (value instanceof Date) row.getCell(2).numFmt = 'd mmm yyyy, hh:mm';
  }
}

function chartSheet(wb: Workbook, c: ChartSpec, name: string): void {
  const ws = wb.addWorksheet(name);
  ws.addRow([c.title]).font = { bold: true, size: 13 };
  if (c.insight) ws.addRow([c.insight]).font = { italic: true, color: { argb: 'FF52514E' } };
  ws.addRow([]);

  let header: string[];
  let body: unknown[][];
  if (c.type === 'table') {
    header = (c.columns ?? []).map((h) => h.replace(/_/g, ' '));
    body = c.rows ?? [];
  } else if (c.type === 'kpi') {
    header = ['Metric', 'Value', 'Unit'];
    body = [[c.title, c.value ?? null, c.unit ?? '']];
  } else {
    header = ['Label', ...(c.series ?? []).map((s) => s.name)];
    body = (c.labels ?? []).map((label, i) => [label, ...(c.series ?? []).map((s) => s.data[i] ?? null)]);
  }

  const headerRow = ws.addRow(header);
  headerRow.eachCell((cell) => {
    cell.font = { bold: true };
    cell.fill = HEADER_FILL;
    cell.border = { bottom: { style: 'thin', color: { argb: 'FFC9C7C0' } } };
  });
  const percent = c.unit === '%' && c.type !== 'table';
  for (const values of body) {
    const row = ws.addRow(values.map(cellValue));
    row.eachCell((cell, col) => {
      if (cell.value instanceof Date) cell.numFmt = 'd mmm yyyy, hh:mm';
      else if (typeof cell.value === 'number')
        cell.numFmt = percent && col > 1 ? '0.0"%"' : Number.isInteger(cell.value) ? '#,##0' : '#,##0.00';
    });
  }

  // Freeze the header, add filter buttons, and size columns to their content.
  ws.views = [{ state: 'frozen', ySplit: headerRow.number }];
  if (body.length) {
    ws.autoFilter = { from: { row: headerRow.number, column: 1 }, to: { row: headerRow.number, column: header.length } };
  }
  header.forEach((h, i) => {
    const longest = Math.max(h.length, ...body.map((r) => display(r[i]).length));
    ws.getColumn(i + 1).width = Math.min(60, Math.max(10, longest + 2));
  });
}

function queriesSheet(wb: Workbook, m: ChatMessage): void {
  const ws = wb.addWorksheet('Queries');
  ws.columns = [
    { header: '#', width: 5 },
    { header: 'MCP tool', width: 26 },
    { header: 'Result', width: 10 },
    { header: 'Input', width: 100 },
  ];
  ws.getRow(1).eachCell((cell) => {
    cell.font = { bold: true };
    cell.fill = HEADER_FILL;
  });
  (m.steps ?? []).forEach((s, i) => {
    const row = ws.addRow([i + 1, s.tool, s.ok ? 'ok' : 'failed', JSON.stringify(s.input, null, 1)]);
    row.getCell(4).alignment = { wrapText: true, vertical: 'top' };
  });
  ws.views = [{ state: 'frozen', ySplit: 1 }];
}

/** Numbers stay numbers and ISO dates become real dates, so Excel can sort, filter and sum them. */
function cellValue(v: unknown): string | number | Date | null {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number' || typeof v === 'boolean') return typeof v === 'boolean' ? String(v) : v;
  if (typeof v === 'string' && ISO_DATE.test(v) && v.length > 10) {
    const d = new Date(v);
    return isNaN(d.getTime()) ? v : d;
  }
  return typeof v === 'object' ? JSON.stringify(v) : String(v);
}

function display(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string' && ISO_DATE.test(v) && v.length > 10) return 'dd mmm yyyy, hh:mm';
  return typeof v === 'object' ? JSON.stringify(v) : String(v);
}

/** Markdown to readable plain text for a cell. */
function plainText(md: string): string {
  return md
    .replace(/<[^>]+>/g, '')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(^|\s)[*_](.+?)[*_](?=\s|$)/g, '$1$2')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*[-*]\s+/gm, '• ')
    .replace(/\[(.+?)\]\((.+?)\)/g, '$1 ($2)')
    .trim();
}

/** Excel sheet names: at most 31 characters, none of : \ / ? * [ ], and unique within the workbook. */
function sheetName(title: string, used: Set<string>): string {
  const base = (title.replace(/[:\\/?*[\]]/g, ' ').replace(/\s+/g, ' ').trim() || 'Data').slice(0, 28);
  let name = base;
  for (let n = 2; used.has(name.toLowerCase()); n++) name = `${base.slice(0, 26)} ${n}`;
  used.add(name.toLowerCase());
  return name;
}

function fileStem(question: string): string {
  const slug = question.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50) || 'answer';
  const d = new Date();
  const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
  return `actuvara-bi-${slug}-${stamp}`;
}

