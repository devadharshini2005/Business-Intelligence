import { Component, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { AnalyticsStore } from '../core/analytics.store';
import { ChatStore } from '../core/chat.store';
import { ChartSpec, Kpi } from '../core/models';
import { BottlenecksPanel } from '../shared/analytics/bottlenecks-panel';
import { InsightsPanel } from '../shared/analytics/insights-panel';
import { KpiTile } from '../shared/analytics/kpi-tile';
import { PipelinePanel } from '../shared/analytics/pipeline-panel';
import { ProcessScorecard } from '../shared/analytics/process-scorecard';
import { ReviewQueue } from '../shared/analytics/review-queue';
import { ChartCard } from '../shared/chart-card';
import { SubmissionPanel } from '../shared/submission-panel';

const RANGES = [
  { days: 7, label: '7d' },
  { days: 30, label: '30d' },
  { days: 90, label: '90d' },
  { days: 365, label: '12m' },
  { days: 0, label: 'All' },
];

/**
 * The Analytics page: one filter row (period, source, process) scoping every panel below it, like the
 * Property Guidelines analytics. Filters live in the address (?days=&source=&process=), so a view can be
 * bookmarked or shared, and clicking a process anywhere on the page focuses the page on it.
 */
@Component({
  selector: 'app-dashboard',
  imports: [
    ChartCard, SubmissionPanel, DatePipe, FormsModule,
    KpiTile, PipelinePanel, InsightsPanel, ProcessScorecard, BottlenecksPanel, ReviewQueue,
  ],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
})
export class DashboardPage {
  readonly store = inject(AnalyticsStore);
  private readonly chat = inject(ChatStore);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly ranges = RANGES;
  // Filters and data live in AnalyticsStore, so they survive navigating to another page and back.
  readonly days = this.store.days;
  readonly source = this.store.source;
  readonly process = this.store.process;
  readonly data = this.store.data;
  readonly loading = this.store.loading;
  readonly busy = this.store.busy;
  readonly error = this.store.error;
  readonly openSubmission = signal<string | null>(null);

  readonly kpis = computed(() => this.data()?.kpis ?? []);
  readonly runs = computed(() => this.kpis().find((k) => k.key === 'runs')?.value ?? null);
  /** The period has no runs although the data has some: say when the last activity was. */
  readonly empty = computed(() => this.runs() === 0 && !!this.data()?.latest_activity);
  readonly processName = computed(() => this.data()?.process_name ?? null);
  readonly filtered = computed(() => !!(this.source() || this.process()));

  constructor() {
    // A shared or bookmarked link (?days=&source=&process=) sets the filters; a plain /analytics keeps
    // the ones from last time.
    const q = this.route.snapshot.queryParamMap;
    if (q.has('days') || q.has('source') || q.has('process')) {
      const days = Number(q.get('days'));
      if (RANGES.some((r) => r.days === days)) this.days.set(days);
      this.source.set(q.get('source') ?? '');
      this.process.set(q.get('process') ?? '');
    }
    this.load();
  }

  /** Show the current filters - instantly from memory when already loaded. */
  load(force = false): void {
    this.router.navigate([], {
      queryParams: { days: this.days(), source: this.source() || null, process: this.process() || null },
      replaceUrl: true,
    });
    this.store.show(force);
  }

  refresh(): void {
    this.load(true);
  }

  setDays(days: number): void {
    this.days.set(days);
    this.load();
  }

  setSource(source: string): void {
    this.source.set(source);
    this.load();
  }

  setProcess(process: string): void {
    this.process.set(process);
    this.load();
    window.scrollTo?.({ top: 0, behavior: 'smooth' });
  }

  clearFilters(): void {
    this.source.set('');
    this.process.set('');
    this.load();
  }

  rangeText(): string {
    return this.days() ? `the last ${this.days()} days` : 'all time';
  }

  /** A sentence describing the current scope, used in questions handed to the chatbot. */
  private scopeText(): string {
    const parts = [this.rangeText()];
    if (this.processName()) parts.push(`process "${this.processName()}"`);
    if (this.source()) parts.push(`source ${this.source().replace('_', ' ')}`);
    return parts.join(', ');
  }

  askKpi(key: string): void {
    const k = this.kpis().find((x: Kpi) => x.key === key);
    if (k) this.askChat(`Explain "${k.title}" for ${this.scopeText()}: what drives it and how has it changed? Show a breakdown.`);
  }

  askInsight(text: string): void {
    this.askChat(`${text} Why is that, for ${this.scopeText()}? Show the supporting numbers.`);
  }

  askAbout(c: ChartSpec): void {
    this.askChat(`Analyse "${c.title}" for ${this.scopeText()}. What stands out, and what are the likely reasons?`);
  }

  askChat(q: string): void {
    if (!q.trim()) return;
    this.chat.ask(q, { fresh: true });
    this.openSubmission.set(null);
    this.router.navigateByUrl('/chat');
  }
}
