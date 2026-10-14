import { Component, computed, input } from '@angular/core';

/** A tiny trend line with a soft fill. Gaps (null) are bridged; a flat or empty series draws a baseline. */
@Component({
  selector: 'app-sparkline',
  template: `
    <svg [attr.viewBox]="'0 0 ' + width() + ' ' + height()" [attr.width]="width()" [attr.height]="height()"
         preserveAspectRatio="none" aria-hidden="true">
      @if (paths(); as p) {
        <path [attr.d]="p.area" [attr.fill]="color()" fill-opacity="0.12" />
        <path [attr.d]="p.line" fill="none" [attr.stroke]="color()" stroke-width="1.6"
              stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />
        <circle [attr.cx]="p.lastX" [attr.cy]="p.lastY" r="2" [attr.fill]="color()" />
      }
    </svg>
  `,
  styles: `
    :host {
      display: block;
      line-height: 0;
    }
  `,
})
export class Sparkline {
  readonly values = input<(number | null)[] | null>(null);
  readonly width = input(76);
  readonly height = input(24);
  readonly color = input('var(--accent)');

  readonly paths = computed(() => {
    const vals = (this.values() ?? []).map((v) => (v === null || v === undefined ? null : v));
    const known = vals.filter((v): v is number => v !== null);
    if (vals.length < 2 || !known.length) return null;
    const w = this.width();
    const h = this.height();
    const pad = 2;
    const min = Math.min(...known);
    const max = Math.max(...known);
    const span = max - min || 1;
    const pts: [number, number][] = [];
    vals.forEach((v, i) => {
      if (v === null) return;
      const x = (i / (vals.length - 1)) * w;
      const y = max === min ? h - pad - 1 : h - pad - ((v - min) / span) * (h - pad * 2);
      pts.push([+x.toFixed(1), +y.toFixed(1)]);
    });
    const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x},${y}`).join(' ');
    const area = `${line} L${pts[pts.length - 1][0]},${h} L${pts[0][0]},${h} Z`;
    const [lastX, lastY] = pts[pts.length - 1];
    return { line, area, lastX, lastY };
  });
}
