import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

import { full } from '../format';

/** One bar per weekday; the busiest day is highlighted and labelled, others show their value on hover. */
@Component({
  selector: 'bi-weekday-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wk" (mouseleave)="hover.set(null)">
      @for (d of bars(); track d.day; let i = $index) {
        <div class="wk-col" (mouseenter)="hover.set(i)" [attr.aria-label]="d.day + ': ' + d.label">
          <div class="wk-plot">
            @if (d.peak || hover() === i) { <span class="wk-val">{{ d.label }}</span> }
            <span class="wk-bar" [class.peak]="d.peak" [class.hover]="hover() === i" [style.height.%]="d.h"></span>
          </div>
          <span class="wk-day" [class.on]="d.peak">{{ d.day }}</span>
        </div>
      }
    </div>`,
})
export class WeekdayChartComponent {
  /** Seven values, Sunday first. */
  values = input.required<number[]>();
  hover = signal<number | null>(null);

  bars = computed(() => {
    const v = this.values();
    const max = Math.max(1, ...v);
    const peak = v.some((x) => x > 0) ? v.indexOf(Math.max(...v)) : -1;
    return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day, i) => ({
      day, h: Math.max(3, (100 * v[i]) / max), label: full(v[i]), peak: i === peak,
    }));
  });
}
