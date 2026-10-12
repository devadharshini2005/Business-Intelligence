import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

import { full, statusRole } from '../format';
import { ChartSpec } from '../models';

const LW = 600;
const LH = 200;
const PAD = 8;
const MAX_COLOURS = 8; // categorical palette size; beyond this bars share one colour (never cycle hues)

/**
 * Renders a chart spec from the assistant (BI_Backend/charts.py); every number comes from a
 * query the backend ran. One colour per category, from a fixed-order palette - or the status
 * palette when the categories are run / node statuses. Always with a legend or direct labels.
 */
@Component({
  selector: 'bi-chat-chart',
  imports: [NgTemplateOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <figure class="cc">
      <figcaption class="cc-title">{{ spec().title }}</figcaption>
      @switch (spec().type) {
        @case ('kpi') {
          <div class="cc-kpi">{{ kpi() }}</div>
        }
        @case ('error') {
          <div class="placeholder error small">{{ spec().error }}</div>
        }
        @case ('table') {
          <div class="table-wrap">
            <table class="table">
              <thead><tr>@for (c of spec().columns ?? []; track $index) { <th>{{ c }}</th> }</tr></thead>
              <tbody>
                @for (r of spec().rows ?? []; track $index) {
                  <tr>@for (v of r; track $index) { <td [class.num]="isNum(v)">{{ cell(v) }}</td> }</tr>
                }
              </tbody>
            </table>
          </div>
        }

        @case ('line') {
          <div class="cc-line" (mouseleave)="hover.set(null)">
            <svg [attr.viewBox]="'0 0 ' + LW + ' ' + LH" preserveAspectRatio="none" role="img" [attr.aria-label]="spec().title">
              <line [attr.x1]="0" [attr.x2]="LW" [attr.y1]="LH - PAD" [attr.y2]="LH - PAD" class="cc-base" />
              @for (s of line().paths; track s.slot) {
                <polyline [attr.points]="s.points" class="cc-path stroke-{{ s.slot }}" vector-effect="non-scaling-stroke" />
              }
              @if (hover() != null) {
                <line [attr.x1]="line().xs[hover()!]" [attr.x2]="line().xs[hover()!]" y1="0" [attr.y2]="LH - PAD" class="cc-cross" vector-effect="non-scaling-stroke" />
              }
              @for (x of line().xs; track $index; let i = $index) {
                <rect [attr.x]="x - line().step / 2" y="0" [attr.width]="line().step" [attr.height]="LH" class="hit" (mouseenter)="hover.set(i)" />
              }
            </svg>
            @if (hover() != null) {
              <div class="tooltip" [style.left.%]="(100 * line().xs[hover()!]) / LW">
                <div class="tip-title">{{ labels()[hover()!] }}</div>
                @for (s of series(); track s.name; let si = $index) {
                  <div class="tip-row"><i class="sw s-{{ si + 1 }}"></i>{{ s.name }}<b>{{ fmt(s.data[hover()!]) }}</b></div>
                }
              </div>
            }
            <div class="cc-axis"><span>{{ labels()[0] }}</span><span class="muted">max {{ fmt(line().max) }}</span><span>{{ labels()[labels().length - 1] }}</span></div>
          </div>
        }

        @case ('pie') { <ng-container *ngTemplateOutlet="pieTpl" /> }
        @case ('doughnut') { <ng-container *ngTemplateOutlet="pieTpl" /> }

        @case ('bar') {
          @if (series().length > 1) { <ng-container *ngTemplateOutlet="hbarTpl" /> }
          @else {
            <!-- vertical columns, one colour per category, value on top -->
            <div class="cc-cols" [style.--n]="cats().length" (mouseleave)="hover.set(null)">
              @for (c of cats(); track $index; let i = $index) {
                <div class="cc-col" (mouseenter)="hover.set(i)" [class.dim]="hover() != null && hover() !== i"
                     [attr.aria-label]="c.label + ': ' + c.text">
                  <div class="cc-col-plot">
                    <span class="cc-col-val">{{ c.text }}</span>
                    <span class="cc-col-bar k-{{ c.colour }}" [style.height.%]="c.pct"></span>
                  </div>
                  <span class="cc-col-label" [title]="c.label">{{ c.label }}</span>
                </div>
              }
            </div>
          }
        }

        @default { <ng-container *ngTemplateOutlet="hbarTpl" /> }
      }

      @if (series().length > 1 && spec().type !== 'table' && spec().type !== 'kpi') {
        <div class="legend">@for (s of series(); track s.name; let si = $index) { <span><i class="sw s-{{ si + 1 }}"></i>{{ s.name }}</span> }</div>
      }
      @if (spec().note) { <div class="muted small">{{ spec().note }}</div> }
    </figure>

    <!-- horizontal bars: one row per category (one colour each), or one bar per series -->
    <ng-template #hbarTpl>
      <div class="cc-bars">
        @for (row of bars(); track $index) {
          <div class="cc-row">
            <span class="cc-label ellipsis" [title]="row.label">{{ row.label }}</span>
            <span class="cc-tracks">
              @for (b of row.bars; track $index) {
                <span class="cc-track"><span class="cc-fill k-{{ b.colour }}" [style.width.%]="b.pct"></span></span>
              }
            </span>
            <span class="cc-val">{{ row.text }}</span>
          </div>
        }
      </div>
    </ng-template>

    <!-- pie / doughnut with a value + share legend -->
    <ng-template #pieTpl>
      <div class="cc-pie" (mouseleave)="hover.set(null)">
        <svg viewBox="-110 -110 220 220" class="cc-pie-svg" role="img" [attr.aria-label]="spec().title">
          @for (s of pie().slices; track $index; let i = $index) {
            <path [attr.d]="s.d" fill-rule="evenodd" class="cc-slice k-{{ s.colour }}" [class.dim]="hover() != null && hover() !== i"
                  [class.on]="hover() === i" (mouseenter)="hover.set(i)"><title>{{ s.label }}: {{ s.text }} ({{ s.share }}%)</title></path>
          }
          @if (spec().type === 'doughnut') {
            <text y="-2" text-anchor="middle" class="cc-pie-total">{{ hover() != null ? pie().slices[hover()!].text : pie().totalText }}</text>
            <text y="18" text-anchor="middle" class="cc-pie-cap">{{ hover() != null ? pie().slices[hover()!].share + '%' : 'total' }}</text>
          }
        </svg>
        <ul class="cc-pie-legend">
          @for (s of pie().slices; track $index; let i = $index) {
            <li [class.on]="hover() === i" (mouseenter)="hover.set(i)">
              <i class="sw k-{{ s.colour }}"></i><span class="ellipsis">{{ s.label }}</span>
              <b>{{ s.text }}</b><span class="muted">{{ s.share }}%</span>
            </li>
          }
        </ul>
      </div>
    </ng-template>`,
})
export class ChatChartComponent {
  readonly LW = LW;
  readonly LH = LH;
  readonly PAD = PAD;
  spec = input.required<ChartSpec>();
  hover = signal<number | null>(null);

  labels = computed(() => this.spec().labels ?? []);
  /** At most three series (the validated categorical slots). */
  series = computed(() => (this.spec().series ?? []).slice(0, 3));
  isNum = (v: unknown) => typeof v === 'number';

  fmt = (v: number | null | undefined) => {
    if (v == null) return '–';
    const u = this.spec().unit ?? '';
    return `${Number.isInteger(v) ? full(v) : v.toLocaleString(undefined, { maximumFractionDigits: 2 })}${u}`;
  };

  cell(v: unknown) {
    if (v == null) return '–';
    if (typeof v === 'number') return this.fmt(v);
    return typeof v === 'object' ? JSON.stringify(v) : String(v);
  }

  kpi = computed(() => this.fmt(this.spec().value));

  /**
   * Colour per category: status colours when the labels are statuses (completed / failed / …),
   * otherwise palette slots 1-8 in order; more than 8 categories share slot 1 rather than cycling.
   */
  colours = computed(() => {
    const labels = this.labels();
    // "rejected" gets the serious (orange) step so it doesn't share red with "failed".
    const roles = labels.map((l) => (/^rejected$/i.test(l.trim()) ? 'serious' : statusRole(l)));
    const known = roles.filter((r) => r !== 'neutral').length;
    if (labels.length > 1 && known >= Math.ceil(labels.length / 2)) return roles as string[];
    if (labels.length <= MAX_COLOURS) return labels.map((_, i) => String(i + 1));
    return labels.map(() => '1');
  });

  /** Single-series categories with their colour, for columns. */
  cats = computed(() => {
    const data = this.series()[0]?.data ?? [];
    const max = Math.max(1e-9, ...data.map((v) => Math.abs(v ?? 0)));
    return this.labels().map((label, i) => ({
      label, colour: this.colours()[i], text: this.fmt(data[i]), pct: Math.max(0.5, (100 * Math.abs(data[i] ?? 0)) / max),
    }));
  });

  bars = computed(() => {
    const series = this.series();
    const multi = series.length > 1;
    const max = Math.max(1e-9, ...series.flatMap((s) => s.data.map((v) => Math.abs(v ?? 0))));
    return this.labels().map((label, i) => ({
      label,
      // One series: colour by category. Several: colour by series (legend below).
      bars: series.map((s, si) => ({ colour: multi ? String(si + 1) : this.colours()[i], pct: (100 * Math.abs(s.data[i] ?? 0)) / max })),
      text: series.map((s) => this.fmt(s.data[i])).join(' · '),
    }));
  });

  pie = computed(() => {
    const data = (this.series()[0]?.data ?? []).map((v) => Math.max(0, v ?? 0));
    const total = data.reduce((a, v) => a + v, 0);
    const inner = this.spec().type === 'doughnut' ? 62 : 0;
    const R = 100;
    let at = -Math.PI / 2;
    const slices = this.labels().map((label, i) => {
      const frac = total ? data[i] / total : 0;
      const a0 = at;
      const a1 = at + frac * 2 * Math.PI;
      at = a1;
      return {
        label, colour: this.colours()[i], text: this.fmt(data[i]),
        share: total ? Math.round(frac * 1000) / 10 : 0,
        d: frac >= 0.9999 ? ring(R, inner) : frac > 0 ? slice(a0, a1, R, inner) : '',
      };
    });
    return { slices, totalText: this.fmt(total) };
  });

  line = computed(() => {
    const series = this.series();
    const n = this.labels().length;
    const max = Math.max(1e-9, ...series.flatMap((s) => s.data.map((v) => v ?? 0)));
    const step = n > 1 ? LW / (n - 1) : LW;
    const xs = Array.from({ length: n }, (_, i) => (n > 1 ? i * step : LW / 2));
    const y = (v: number) => LH - PAD - ((LH - 2 * PAD) * v) / max;
    const paths = series.map((s, si) => ({
      slot: si + 1,
      points: s.data.map((v, i) => (v == null ? '' : `${xs[i].toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean).join(' '),
    }));
    return { xs, step, paths, max };
  });
}

function pt(a: number, r: number) {
  return `${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
}

/** Pie wedge (inner = 0) or doughnut segment from angle a0 to a1. */
function slice(a0: number, a1: number, R: number, inner: number): string {
  const large = a1 - a0 > Math.PI ? 1 : 0;
  if (!inner) return `M 0 0 L ${pt(a0, R)} A ${R} ${R} 0 ${large} 1 ${pt(a1, R)} Z`;
  return `M ${pt(a0, R)} A ${R} ${R} 0 ${large} 1 ${pt(a1, R)} L ${pt(a1, inner)} A ${inner} ${inner} 0 ${large} 0 ${pt(a0, inner)} Z`;
}

/** A single category that is 100% of the whole. */
function ring(R: number, inner: number): string {
  const outer = `M ${R} 0 A ${R} ${R} 0 1 1 ${-R} 0 A ${R} ${R} 0 1 1 ${R} 0 Z`;
  return inner ? `${outer} M ${inner} 0 A ${inner} ${inner} 0 1 0 ${-inner} 0 A ${inner} ${inner} 0 1 0 ${inner} 0 Z` : outer;
}
