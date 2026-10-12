import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

import { full } from '../format';

export interface FlowSeries { key: string; label: string; slot: number; }
export interface FlowBucket { label: string; title: string; values: Record<string, number>; }

const W = 640;
const H = 300;
const TOP = 44;
const BOTTOM = 34;
const GAP = 3;

/**
 * Stacked columns per bucket, joined by soft ribbons that follow each series from one
 * column to the next. Legend always shown; total labelled above each column; hover for detail.
 */
@Component({
  selector: 'bi-flow-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flow" (mouseleave)="hover.set(null)">
      <svg [attr.viewBox]="'0 0 ' + W + ' ' + H" role="img" [attr.aria-label]="ariaLabel()">
        @for (r of geo().ribbons; track $index) {
          <polygon [attr.points]="r.points" class="ribbon s-{{ r.slot }}" />
        }
        @for (c of geo().cols; track c.label; let i = $index) {
          <g [class.dim]="hover() != null && hover() !== i">
            @for (s of c.segs; track s.slot) {
              <rect [attr.x]="c.x" [attr.y]="s.y" [attr.width]="c.w" [attr.height]="s.h" rx="5" class="s-{{ s.slot }}" />
            }
            <text [attr.x]="c.x + c.w / 2" [attr.y]="c.top - 12" class="flow-total" text-anchor="middle">{{ c.totalLabel }}</text>
            <text [attr.x]="c.x + c.w / 2" [attr.y]="H - 8" class="flow-axis" [class.on]="hover() === i" text-anchor="middle">{{ c.label }}</text>
            <rect [attr.x]="c.slotX" y="0" [attr.width]="c.slotW" [attr.height]="H" class="hit" (mouseenter)="hover.set(i)" />
          </g>
        }
      </svg>
      @if (tip(); as t) {
        <div class="tooltip flow-tip" [style.left.%]="t.left">
          <div class="tip-title">{{ t.title }} · {{ t.total }}</div>
          @for (r of t.rows; track r.slot) {
            <div class="tip-row"><i class="sw s-{{ r.slot }}"></i>{{ r.label }}<b>{{ r.v }}</b></div>
          }
        </div>
      }
    </div>
    <div class="legend center">
      @for (s of series(); track s.key) { <span><i class="sw s-{{ s.slot }}"></i>{{ s.label }}</span> }
    </div>`,
})
export class FlowChartComponent {
  readonly W = W;
  readonly H = H;
  buckets = input.required<FlowBucket[]>();
  series = input.required<FlowSeries[]>();
  hover = signal<number | null>(null);

  ariaLabel = computed(() => `Stacked submissions per period by source: ${this.buckets().map((b) => `${b.label} ${
    this.series().reduce((a, s) => a + (b.values[s.key] || 0), 0)}`).join(', ')}`);

  geo = computed(() => {
    const buckets = this.buckets();
    const series = this.series();
    const n = Math.max(1, buckets.length);
    const slotW = W / n;
    const colW = Math.min(slotW * 0.42, 92);
    const totals = buckets.map((b) => series.reduce((a, s) => a + (b.values[s.key] || 0), 0));
    const scale = (H - TOP - BOTTOM) / Math.max(1, ...totals);
    const base = H - BOTTOM;

    const cols = buckets.map((b, i) => {
      const x = slotW * i + (slotW - colW) / 2;
      let y = base;
      const segs = series.map((s) => {
        const v = b.values[s.key] || 0;
        const h = v * scale;
        const seg = { slot: s.slot, v, top: y - h, bottom: y, y: y - h + GAP / 2, h: Math.max(0, h - GAP) };
        y -= h;
        return seg;
      });
      return { label: b.label, title: b.title, x, w: colW, slotX: slotW * i, slotW, top: y, segs,
               totalLabel: full(totals[i]), total: totals[i] };
    });

    const ribbons: { points: string; slot: number }[] = [];
    for (let i = 0; i < cols.length - 1; i++) {
      const a = cols[i];
      const b = cols[i + 1];
      const x1 = a.x + a.w;
      const x2 = b.x;
      a.segs.forEach((sa, si) => {
        const sb = b.segs[si];
        if (!sa.v && !sb.v) return;
        ribbons.push({
          slot: sa.slot,
          points: `${x1},${sa.top + GAP / 2} ${x2},${sb.top + GAP / 2} ${x2},${sb.bottom - GAP / 2} ${x1},${sa.bottom - GAP / 2}`,
        });
      });
    }
    return { cols, ribbons };
  });

  tip = computed(() => {
    const i = this.hover();
    if (i == null) return null;
    const c = this.geo().cols[i];
    const series = this.series();
    return {
      left: Math.min(84, Math.max(16, ((c.x + c.w / 2) / W) * 100)),
      title: c.title,
      total: full(c.total),
      rows: [...series].reverse().map((s) => ({ slot: s.slot, label: s.label, v: full(this.buckets()[i].values[s.key] || 0) })),
    };
  });
}
