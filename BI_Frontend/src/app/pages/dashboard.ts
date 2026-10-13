import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { Router } from '@angular/router';

import { ApiService, errorText } from '../core/api.service';
import { ChatStore } from '../core/chat.store';
import { ChartSpec, DashboardData } from '../core/models';
import { ChartCard } from '../shared/chart-card';
import { SubmissionPanel } from '../shared/submission-panel';

const RANGES = [
  { days: 7, label: '7d' },
  { days: 30, label: '30d' },
  { days: 90, label: '90d' },
  { days: 365, label: '12m' },
  { days: 0, label: 'All' },
];

@Component({
  selector: 'app-dashboard',
  imports: [ChartCard, SubmissionPanel, DatePipe],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
})
export class DashboardPage {
  private readonly api = inject(ApiService);
  private readonly chat = inject(ChatStore);
  private readonly router = inject(Router);

  readonly ranges = RANGES;
  readonly days = signal(30);
  readonly data = signal<DashboardData | null>(null);
  readonly loading = signal(false);
  readonly error = signal('');
  readonly openSubmission = signal<string | null>(null);

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

  rangeText(): string {
    return this.days() ? `the last ${this.days()} days` : 'all time';
  }

  /** "Ask AI" on a card: open the chatbot with a question about that chart. */
  askAbout(c: ChartSpec): void {
    this.askChat(
      c.type === 'kpi'
        ? `Explain the "${c.title}" figure for ${this.rangeText()}: how is it calculated and what drives it? Show a breakdown.`
        : `Analyse "${c.title}" for ${this.rangeText()}. What stands out, and what are the likely reasons? Show the supporting numbers.`,
    );
  }

  askChat(q: string): void {
    if (!q.trim()) return;
    this.chat.ask(q, { fresh: true });
    this.openSubmission.set(null);
    this.router.navigateByUrl('/chat');
  }
}
