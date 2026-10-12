import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export interface GaugePart { label: string; value: number; role: string; }

const R = 90;
const CX = 120;
const CY = 112;
const STROKE = 30;

/** Half-donut: each part's share of the total as an arc, with the headline in the middle. */
@Component({
  selector: 'bi-gauge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg viewBox="0 0 240 130" class="gauge" role="img" [attr.aria-label]="aria()">
      <defs>
        <pattern id="gauge-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" class="gauge-hatch-bg" />
          <line x1="0" y1="0" x2="0" y2="6" class="gauge-hatch-line" />
        </pattern>
      </defs>
      <path [attr.d]="track" class="gauge-track" [attr.stroke-width]="stroke" />
      @for (a of arcs(); track a.label) {
        <path [attr.d]="a.d" class="gauge-arc arc-{{ a.role }}" [attr.stroke-width]="stroke"><title>{{ a.label }}: {{ a.pct }}%</title></path>
      }
      <text x="120" y="98" text-anchor="middle" class="gauge-value">{{ center() }}</text>
      <text x="120" y="118" text-anchor="middle" class="gauge-label">{{ caption() }}</text>
    </svg>`,
})
export class GaugeComponent {
  parts = input.required<GaugePart[]>();
  center = input('');
  caption = input('');
  readonly stroke = STROKE;
  readonly track = arc(0, 1);

  aria = computed(() => this.parts().map((p) => `${p.label} ${p.value}`).join(', '));

  arcs = computed(() => {
    const parts = this.parts().filter((p) => p.value > 0);
    const total = parts.reduce((a, p) => a + p.value, 0);
    if (!total) return [];
    const gap = parts.length > 1 ? 0.012 : 0;
    let at = 0;
    return parts.map((p) => {
      const share = p.value / total;
      const d = arc(at + gap / 2, Math.max(at + gap / 2 + 0.002, at + share - gap / 2));
      at += share;
      return { label: p.label, role: p.role, d, pct: Math.round(share * 1000) / 10 };
    });
  });
}

/** Arc along the upper half-circle from fraction f0 to f1 (0 = left end, 1 = right end). */
function arc(f0: number, f1: number): string {
  const pt = (f: number) => {
    const a = Math.PI * (1 - f);
    return `${(CX + R * Math.cos(a)).toFixed(2)} ${(CY - R * Math.sin(a)).toFixed(2)}`;
  };
  return `M ${pt(f0)} A ${R} ${R} 0 0 1 ${pt(f1)}`;
}
