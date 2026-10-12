import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';

import { ApiService, errorText } from '../core/api.service';
import { DashboardData } from '../core/models';
import { ChartCard } from '../shared/chart-card';

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
  { days: 0, label: 'All time' },
];

@Component({
  selector: 'app-dashboard',
  imports: [ChartCard, DatePipe],
  template: `
    <div class="page-head">
      <div>
        <h1>Analytics dashboard</h1>
        @if (data(); as d) {
          <p class="sub">Updated {{ d.generated_at | date: 'medium' }}</p>
        }
      </div>
      <div class="controls">
        <div class="segmented" role="group" aria-label="Time range">
          @for (r of ranges; track r.days) {
            <button type="button" [class.active]="days() === r.days" (click)="load(r.days)">{{ r.label }}</button>
          }
        </div>
        <button class="ghost" type="button" (click)="load(days())" [disabled]="loading()">Refresh</button>
      </div>
    </div>

    @if (error()) {
      <div class="banner error">{{ error() }}</div>
    }

    @if (loading() && !data()) {
      <div class="kpis">@for (i of [1, 2, 3, 4, 5, 6, 7]; track i) { <div class="skeleton kpi-sk"></div> }</div>
      <div class="grid">@for (i of [1, 2, 3, 4]; track i) { <div class="skeleton chart-sk"></div> }</div>
    }

    @if (data(); as d) {
      <div class="kpis" [class.dim]="loading()">
        @for (k of d.kpis; track k.title) { <app-chart-card [spec]="k" /> }
      </div>
      @if (d.kpi_error) { <div class="banner error">KPIs: {{ d.kpi_error }}</div> }
      <div class="grid" [class.dim]="loading()">
        @for (c of d.charts; track c.id) {
          <app-chart-card [spec]="c" [class.wide]="c.type === 'line' || c.type === 'table'" />
        }
      </div>
    }
  `,
  styleUrl: './dashboard.scss',
})
export class DashboardPage {
  private readonly api = inject(ApiService);
  readonly ranges = RANGES;
  readonly days = signal(30);
  readonly data = signal<DashboardData | null>(null);
  readonly loading = signal(false);
  readonly error = signal('');

  constructor() {
    this.load(30);
  }

  load(days: number): void {
    this.days.set(days);
    this.loading.set(true);
    this.error.set('');
    this.api.dashboard(days).subscribe({
      next: (d) => {
        this.data.set(d);
        this.loading.set(false);
      },
      error: (e) => {
        this.error.set(errorText(e));
        this.loading.set(false);
      },
    });
  }
}
