import { Component, computed, input } from '@angular/core';

import { ChartSpec } from '../core/models';
import { ChartCard } from './chart-card';

/**
 * The analytics under a chat answer, laid out by what the answer contains rather than in one
 * uniform grid: headline numbers as a strip of tiles, the first chart as the main view, the rest as
 * supporting views, and detail tables last. A "how many" answer is just a tile; a ranking is one
 * large ranked chart; a trend leads with its line - so different questions look different.
 */
@Component({
  selector: 'app-answer-analytics',
  imports: [ChartCard],
  template: `
    @if (kpis().length) {
      <div class="headline" [class.solo]="kpis().length === 1 && !plots().length && !tables().length">
        @for (k of kpis(); track $index) { <app-chart-card [spec]="k" [annotated]="true" /> }
      </div>
    }
    @if (main(); as m) {
      <app-chart-card class="main" [spec]="m" [annotated]="true" [hero]="true" />
    }
    @if (supporting().length) {
      <div class="supporting" [class.pair]="supporting().length > 1">
        @for (c of supporting(); track $index) { <app-chart-card [spec]="c" [annotated]="true" /> }
      </div>
    }
    @for (t of tables(); track $index) {
      <app-chart-card [spec]="t" [annotated]="true" />
    }
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-top: 12px;
    }
    app-chart-card {
      animation: rise 0.3s ease-out;
    }
    .headline {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
      gap: 10px;
      &.solo {
        grid-template-columns: minmax(0, 280px);
      }
    }
    .supporting {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 12px;
      &.pair {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    @media (max-width: 900px) {
      .supporting.pair {
        grid-template-columns: minmax(0, 1fr);
      }
    }
    @keyframes rise {
      from {
        opacity: 0;
        transform: translateY(6px);
      }
    }
  `,
})
export class AnswerAnalytics {
  readonly charts = input.required<ChartSpec[]>();

  readonly kpis = computed(() => this.charts().filter((c) => c.type === 'kpi'));
  readonly tables = computed(() => this.charts().filter((c) => c.type === 'table'));
  readonly plots = computed(() => this.charts().filter((c) => c.type !== 'kpi' && c.type !== 'table'));
  readonly main = computed(() => this.plots()[0] ?? null);
  readonly supporting = computed(() => this.plots().slice(1));
}
