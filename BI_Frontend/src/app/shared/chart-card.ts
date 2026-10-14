import {
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Chart, ChartConfiguration, Plugin, registerables } from 'chart.js';

import { ChartSpec, ChartType } from '../core/models';
import { ThemeService } from '../core/theme.service';

Chart.register(...registerables);

/** CSS variable names; values live in styles.scss so light/dark swap in one place. */
const SERIES_VARS = Array.from({ length: 8 }, (_, i) => `--series-${i + 1}`);
const PLOT_TYPES: ChartType[] = ['bar', 'hbar', 'line', 'pie', 'doughnut'];
const TYPE_LABELS: Partial<Record<ChartType, string>> = {
  bar: 'Bars', hbar: 'Horizontal bars', line: 'Line', doughnut: 'Doughnut', pie: 'Pie',
};

/** The analysis a chart type answers, as the reader would name it. */
const KIND: Partial<Record<ChartType, string>> = {
  line: 'Trend', hbar: 'Ranking', bar: 'Comparison', doughnut: 'Share', pie: 'Share', table: 'Details',
};

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Status hue for a status label (runs by status etc.); undefined = not a known status. */
function statusVar(label: string): string | undefined {
  const s = label.toLowerCase();
  if (/(complete|success|processed|done|approved|validated)/.test(s)) return '--status-good';
  if (/(fail|error|reject|cancel)/.test(s)) return '--status-critical';
  if (/(await|review|pending|progress|processing|queued|received)/.test(s)) return '--status-warning';
  return undefined;
}

/** Paints the chart surface behind the plot so a downloaded PNG isn't transparent. */
const surfacePlugin: Plugin = {
  id: 'surface',
  beforeDraw: (chart) => {
    const { ctx, width, height } = chart;
    ctx.save();
    ctx.globalCompositeOperation = 'destination-over';
    ctx.fillStyle = cssVar('--surface-1');
    ctx.fillRect(0, 0, width, height);
    ctx.restore();
  },
};

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'chart';
}

function download(name: string, href: string): void {
  const a = document.createElement('a');
  a.href = href;
  a.download = name;
  a.click();
}

@Component({
  selector: 'app-chart-card',
  imports: [DecimalPipe],
  templateUrl: './chart-card.html',
  styleUrl: './chart-card.scss',
})
export class ChartCard {
  readonly spec = input.required<ChartSpec>();
  /** Show the "Ask AI" button (dashboard). */
  readonly askable = input(false);
  /** The MCP tool the spec came from, shown under the title. */
  readonly source = input('');
  /** Chat answers: label the kind of analysis and add quick facts read off the chart's own data. */
  readonly annotated = input(false);
  /** The main chart of an answer: drawn taller. */
  readonly hero = input(false);
  readonly ask = output<ChartSpec>();
  /** Fired with the row id when a table row that has one is clicked. */
  readonly rowClick = output<string>();

  readonly canvas = viewChild<ElementRef<HTMLCanvasElement>>('canvas');
  readonly showTable = signal(false);
  readonly expanded = signal(false);
  readonly menuOpen = signal(false);
  readonly viewType = signal<ChartType | null>(null);

  readonly type = computed<ChartType>(() => this.viewType() ?? this.spec().type);
  readonly empty = computed(() => {
    const s = this.spec();
    return !s.labels?.length || !(s.series ?? []).some((x) => x.data.some((v) => v !== null && v !== 0));
  });
  readonly isPlot = computed(() => PLOT_TYPES.includes(this.spec().type) && !this.empty());
  readonly canDownload = computed(() => this.isPlot() || this.spec().type === 'table');
  /** Chart types this data can also be shown as. */
  /** Unit as shown after a value: "36.6%" but "29 runs". */
  readonly unit = computed(() => {
    const u = this.spec().unit ?? '';
    return !u || u === '%' ? u : ' ' + u;
  });
  readonly altTypes = computed<{ type: ChartType; label: string }[]>(() => {
    if (!this.isPlot()) return [];
    const s = this.spec();
    const multi = (s.series?.length ?? 0) > 1;
    const negative = (s.series ?? []).some((x) => x.data.some((v) => (v ?? 0) < 0));
    const types: ChartType[] = ['bar', 'hbar', 'line'];
    if (!multi && !negative && (s.labels?.length ?? 0) <= 12) types.push('doughnut');
    return types.map((type) => ({ type, label: TYPE_LABELS[type]! }));
  });
  readonly plotHeight = computed(() => {
    const s = this.spec();
    if (this.expanded()) return Math.round(window.innerHeight * 0.62);
    if (this.type() === 'hbar') return Math.max(180, (s.labels?.length ?? 0) * 30 + 40);
    return this.hero() ? 320 : 260;
  });

  /** What kind of analysis this is, in a word - so a reader knows how to read it before looking. */
  readonly kind = computed<string | null>(() => {
    if (!this.annotated()) return null;
    return KIND[this.spec().type] ?? null;
  });

  /**
   * Two or three facts a reader would otherwise have to work out from the chart: the peak of a trend,
   * the leader of a ranking, the largest share. Read straight off the chart's data, never estimated.
   */
  readonly facts = computed<{ label: string; value: string }[]>(() => {
    if (!this.annotated() || !this.isPlot()) return [];
    const s = this.spec();
    const labels = s.labels ?? [];
    const series = s.series ?? [];
    const unit = this.unit();
    const pct = s.unit === '%';
    const fmt = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 1 }) + unit;
    const points = (data: (number | null)[]) =>
      data.map((v, i) => ({ v, label: labels[i] })).filter((p): p is { v: number; label: string } => p.v !== null);

    if (series.length !== 1) {
      if (pct || this.spec().type !== 'line') return [];
      // Several lines: which one carries the most.
      const totals = series.map((x) => ({ name: x.name, t: points(x.data).reduce((a, p) => a + p.v, 0) }));
      const top = [...totals].sort((a, b) => b.t - a.t)[0];
      return top ? [{ label: 'Largest series', value: `${top.name} · ${fmt(top.t)}` }] : [];
    }

    const pts = points(series[0].data);
    if (!pts.length) return [];
    const total = pts.reduce((a, p) => a + p.v, 0);
    const max = pts.reduce((a, p) => (p.v > a.v ? p : a));
    const facts: { label: string; value: string }[] = [];

    switch (this.spec().type) {
      case 'line': {
        const last = pts[pts.length - 1];
        if (!pct) facts.push({ label: 'Total', value: fmt(total) });
        else facts.push({ label: 'Average', value: fmt(total / pts.length) });
        facts.push({ label: 'Peak', value: `${fmt(max.v)} · ${max.label}` });
        facts.push({ label: 'Latest', value: `${fmt(last.v)} · ${last.label}` });
        break;
      }
      case 'hbar':
      case 'bar': {
        const lead = s.highlight ? pts.find((p) => p.label === s.highlight) ?? max : max;
        facts.push({ label: s.highlight ? 'Highlighted' : 'Highest', value: `${lead.label} · ${fmt(lead.v)}` });
        if (!pct && total > 0) facts.push({ label: 'Share of total', value: `${Math.round((100 * lead.v) / total)}%` });
        if (pts.length > 2) facts.push({ label: 'Items', value: String(pts.length) });
        break;
      }
      case 'doughnut':
      case 'pie': {
        if (total > 0) facts.push({ label: 'Largest part', value: `${max.label} · ${Math.round((100 * max.v) / total)}%` });
        if (!pct) facts.push({ label: 'Total', value: fmt(total) });
        break;
      }
    }
    return facts;
  });

  private chart?: Chart;
  private readonly host = inject(ElementRef<HTMLElement>);

  constructor() {
    const theme = inject(ThemeService);
    // Redraw whenever the data, the chosen type, the size mode or the theme changes.
    effect(() => {
      this.spec();
      this.type();
      this.expanded();
      this.showTable();
      theme.version();
      const el = this.canvas()?.nativeElement;
      untracked(() => queueMicrotask(() => this.render(el)));
    });
    inject(DestroyRef).onDestroy(() => this.chart?.destroy());
  }

  @HostListener('document:click', ['$event'])
  onDocClick(e: MouseEvent): void {
    if (this.menuOpen() && !this.host.nativeElement.querySelector('.menu')?.contains(e.target as Node)) {
      this.menuOpen.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.menuOpen.set(false);
    this.expanded.set(false);
  }

  /** The chart/table switch in the header: the table is the chart's twin, not a fallback. */
  setView(table: boolean): void {
    this.showTable.set(table);
    this.menuOpen.set(false);
  }

  setType(t: ChartType): void {
    this.viewType.set(t === this.spec().type ? null : t);
    this.showTable.set(false);
    this.menuOpen.set(false);
  }

  toggleExpanded(): void {
    this.expanded.update((v) => !v);
    this.menuOpen.set(false);
  }

  cell(v: unknown): string {
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return v.slice(0, 16).replace('T', ' ');
    if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return typeof v === 'object' ? JSON.stringify(v) : String(v);
  }

  /** CSS class for status-like table cells (completed / failed / ...). */
  statusClass(column: string, v: unknown): string {
    if (!/status/i.test(column) || typeof v !== 'string') return '';
    const s = statusVar(v);
    return s ? `pill ${s.replace('--status-', '')}` : 'pill';
  }

  openRow(i: number): void {
    const id = this.spec().row_ids?.[i];
    if (id) this.rowClick.emit(id);
  }

  downloadCsv(): void {
    const s = this.spec();
    let rows: unknown[][];
    if (s.type === 'table') rows = [s.columns ?? [], ...(s.rows ?? [])];
    else if (s.type === 'kpi') rows = [['metric', 'value', 'unit'], [s.title, s.value, s.unit ?? '']];
    else
      rows = [
        ['label', ...(s.series ?? []).map((x) => x.name)],
        ...(s.labels ?? []).map((l, i) => [l, ...(s.series ?? []).map((x) => x.data[i])]),
      ];
    const csv = rows
      .map((r) => r.map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','))
      .join('\r\n');
    const url = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }));
    download(`${slug(s.title)}.csv`, url);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    this.menuOpen.set(false);
  }

  downloadPng(): void {
    if (this.chart) download(`${slug(this.spec().title)}.png`, this.chart.toBase64Image('image/png', 1));
    this.menuOpen.set(false);
  }

  private render(el: HTMLCanvasElement | undefined): void {
    this.chart?.destroy();
    this.chart = undefined;
    const s = this.spec();
    const type = this.type();
    if (!el || !this.isPlot() || this.showTable()) return;

    const ink = cssVar('--text-secondary');
    const muted = cssVar('--text-muted');
    const grid = cssVar('--grid');
    const surface = cssVar('--surface-1');
    const palette = SERIES_VARS.map(cssVar);
    const series = s.series ?? [];
    const labels = s.labels ?? [];
    const round = type === 'pie' || type === 'doughnut';
    const horizontal = type === 'hbar';
    const unit = this.unit();

    const datasets = series.map((ser, i) => {
      let color: string | string[] = palette[i % palette.length];
      // One series per status (e.g. runs per day by outcome): each takes its status colour. Rejected gets
      // its own hue so it isn't confused with failed.
      if (s.status_colors && series.length > 1)
        color = cssVar(/reject/i.test(ser.name) ? '--series-5' : statusVar(ser.name) ?? SERIES_VARS[i % SERIES_VARS.length]);
      else if (round) color = labels.map((_, j) => palette[j % palette.length]);
      else if (s.status_colors && series.length === 1 && type !== 'line')
        color = labels.map((l) => cssVar(statusVar(l) ?? '--series-1'));
      else if (s.highlight && series.length === 1 && type !== 'line')
        // The highlighted bar keeps full colour; the rest recede so the eye lands on it first.
        color = labels.map((l) => (l === s.highlight ? palette[0] : palette[0] + '59'));
      return type === 'line'
        ? {
            label: ser.name, data: ser.data, borderColor: color, backgroundColor: color,
            borderWidth: 2, pointRadius: labels.length > 40 ? 0 : 3, pointHoverRadius: 5,
            tension: 0.25, spanGaps: true,
          }
        : round
          ? { label: ser.name, data: ser.data, backgroundColor: color, borderColor: surface, borderWidth: 2 }
          : {
              label: ser.name, data: ser.data, backgroundColor: color, borderRadius: 4,
              borderSkipped: 'start' as const, maxBarThickness: 28, borderColor: surface, borderWidth: 1,
            };
    });

    const axis = {
      grid: { color: grid }, border: { color: grid },
      ticks: { color: muted, maxRotation: 0, autoSkip: true, font: { size: 11 } },
    };
    const config = {
      type: horizontal ? 'bar' : type,
      data: { labels, datasets },
      plugins: [surfacePlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 350 },
        indexAxis: horizontal ? 'y' : 'x',
        cutout: type === 'doughnut' ? '62%' : undefined,
        interaction: { mode: round ? 'nearest' : 'index', intersect: round },
        plugins: {
          legend: {
            display: round || series.length > 1,
            position: round ? 'right' : 'top',
            align: 'start',
            labels: { color: ink, boxWidth: 10, boxHeight: 10, usePointStyle: true },
          },
          tooltip: {
            callbacks: {
              label: (ctx: { dataset: { label?: string }; formattedValue: string; label: string }) =>
                ` ${round ? ctx.label : ctx.dataset.label}: ${ctx.formattedValue}${unit}`,
            },
          },
        },
        scales: round
          ? {}
          : {
              x: { ...axis, grid: { ...axis.grid, display: horizontal }, beginAtZero: horizontal },
              y: { ...axis, grid: { ...axis.grid, display: !horizontal }, beginAtZero: !horizontal },
            },
      },
    } as unknown as ChartConfiguration;
    Chart.defaults.font.family = cssVar('--font');
    this.chart = new Chart(el, config);
  }
}
