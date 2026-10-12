import {
  AfterViewInit,
  Component,
  DestroyRef,
  ElementRef,
  OnChanges,
  computed,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Chart, ChartConfiguration, registerables } from 'chart.js';

import { ChartSpec } from '../core/models';

Chart.register(...registerables);

/** CSS variable names; values live in styles.scss so light/dark swap in one place. */
const SERIES_VARS = Array.from({ length: 8 }, (_, i) => `--series-${i + 1}`);

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

@Component({
  selector: 'app-chart-card',
  imports: [DecimalPipe],
  template: `
    <section class="card" [class.kpi]="spec().type === 'kpi'">
      <header>
        <h3>{{ spec().title }}</h3>
        @if (isPlot()) {
          <button class="ghost small" type="button" (click)="showTable.set(!showTable())"
                  [attr.aria-pressed]="showTable()">
            {{ showTable() ? 'Chart' : 'Table' }}
          </button>
        }
      </header>

      @switch (spec().type) {
        @case ('kpi') {
          <div class="kpi-value" [class.critical]="spec().status === 'critical'">
            @if (spec().value === null || spec().value === undefined) { — }
            @else { {{ spec().value | number: '1.0-1' }}<span class="unit">{{ spec().unit }}</span> }
          </div>
        }
        @case ('error') {
          <p class="error">Couldn't load: {{ spec().error }}</p>
        }
        @case ('table') {
          <div class="table-wrap">
            <table>
              <thead><tr>@for (c of spec().columns ?? []; track $index) { <th>{{ c }}</th> }</tr></thead>
              <tbody>
                @for (r of spec().rows ?? []; track $index) {
                  <tr>@for (v of r; track $index) { <td>{{ cell(v) }}</td> }</tr>
                } @empty {
                  <tr><td [attr.colspan]="spec().columns?.length || 1" class="muted">No rows</td></tr>
                }
              </tbody>
            </table>
          </div>
        }
        @default {
          @if (empty()) {
            <p class="muted empty">No data for this period.</p>
          } @else {
            <div class="plot" [class.hidden]="showTable()" [class.tall]="spec().type === 'hbar'"
                 [style.height.px]="plotHeight()">
              <canvas #canvas role="img" [attr.aria-label]="spec().title"></canvas>
            </div>
            @if (showTable()) {
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr><th></th>@for (s of spec().series ?? []; track $index) { <th class="num">{{ s.name }}</th> }</tr>
                  </thead>
                  <tbody>
                    @for (l of spec().labels ?? []; track $index; let i = $index) {
                      <tr>
                        <td>{{ l }}</td>
                        @for (s of spec().series ?? []; track $index) {
                          <td class="num">{{ s.data[i] ?? '—' }}{{ spec().unit }}</td>
                        }
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            }
          }
        }
      }
    </section>
  `,
  styleUrl: './chart-card.scss',
})
export class ChartCard implements OnChanges, AfterViewInit {
  readonly spec = input.required<ChartSpec>();
  readonly canvas = viewChild<ElementRef<HTMLCanvasElement>>('canvas');
  readonly showTable = signal(false);

  readonly isPlot = computed(() => !['kpi', 'table', 'error'].includes(this.spec().type) && !this.empty());
  readonly empty = computed(() => {
    const s = this.spec();
    return !s.labels?.length || !(s.series ?? []).some((x) => x.data.some((v) => v !== null && v !== 0));
  });
  readonly plotHeight = computed(() => {
    const s = this.spec();
    return s.type === 'hbar' ? Math.max(180, (s.labels?.length ?? 0) * 30 + 40) : 260;
  });

  private chart?: Chart;
  private readonly destroyRef = inject(DestroyRef);

  constructor() {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const redraw = () => this.render();
    mq.addEventListener('change', redraw);
    this.destroyRef.onDestroy(() => {
      mq.removeEventListener('change', redraw);
      this.chart?.destroy();
    });
  }

  ngOnChanges(): void {
    queueMicrotask(() => this.render());
  }

  ngAfterViewInit(): void {
    this.render();
  }

  cell(v: unknown): string {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return v.slice(0, 16).replace('T', ' ');
    return typeof v === 'object' ? JSON.stringify(v) : String(v);
  }

  private render(): void {
    this.chart?.destroy();
    this.chart = undefined;
    const el = this.canvas()?.nativeElement;
    const s = this.spec();
    if (!el || !this.isPlot()) return;

    const ink = cssVar('--text-secondary');
    const muted = cssVar('--text-muted');
    const grid = cssVar('--grid');
    const surface = cssVar('--surface-1');
    const palette = SERIES_VARS.map(cssVar);
    const series = s.series ?? [];
    const labels = s.labels ?? [];
    const round = s.type === 'pie' || s.type === 'doughnut';
    const horizontal = s.type === 'hbar';
    const unit = s.unit ?? '';

    const datasets = series.map((ser, i) => {
      let color: string | string[] = palette[i % palette.length];
      if (round) color = labels.map((_, j) => palette[j % palette.length]);
      else if (s.status_colors && series.length === 1)
        color = labels.map((l) => cssVar(statusVar(l) ?? '--series-1'));
      return s.type === 'line'
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
      type: horizontal ? 'bar' : s.type,
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: horizontal ? 'y' : 'x',
        cutout: s.type === 'doughnut' ? '62%' : undefined,
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
