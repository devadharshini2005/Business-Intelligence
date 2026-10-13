import { Component, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { ApiService, errorText } from '../core/api.service';
import { ChatStore } from '../core/chat.store';
import { Envelope, SubmissionRow } from '../core/models';
import { SubmissionPanel } from '../shared/submission-panel';

const SOURCES = [
  { value: '', label: 'All sources' },
  { value: 'email', label: 'Email' },
  { value: 'webhook', label: 'Webhook' },
  { value: 'manual_upload', label: 'Manual upload' },
];

const PERIODS = [
  { days: 7, label: 'Last 7 days' },
  { days: 30, label: 'Last 30 days' },
  { days: 90, label: 'Last 90 days' },
  { days: 0, label: 'Any time' },
];

/** Every submission (email, webhook, manual upload), newest first - MCP idp_find_submissions. */
@Component({
  selector: 'app-submissions',
  imports: [DatePipe, FormsModule, SubmissionPanel],
  templateUrl: './submissions.html',
  styleUrl: './submissions.scss',
})
export class SubmissionsPage {
  private readonly api = inject(ApiService);
  private readonly chat = inject(ChatStore);
  private readonly router = inject(Router);

  readonly sources = SOURCES;
  readonly periods = PERIODS;

  readonly source = signal('');
  readonly status = signal('');
  readonly search = signal('');
  readonly days = signal(30);
  readonly limit = signal(50);

  readonly data = signal<Envelope<SubmissionRow> | null>(null);
  readonly loading = signal(false);
  readonly error = signal('');
  readonly openSubmission = signal<string | null>(null);

  /** Status options are the statuses actually present in what was loaded, never a fixed list. */
  readonly statuses = computed(() =>
    [...new Set((this.data()?.rows ?? []).map((r) => r.status).filter((s): s is string => !!s))].sort(),
  );
  readonly filtered = computed(() => !!(this.source() || this.status() || this.search()));

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set('');
    this.api
      .submissions({
        source: this.source(),
        status: this.status(),
        search: this.search().trim(),
        days: this.days(),
        limit: this.limit(),
      })
      .subscribe({
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

  reset(): void {
    this.source.set('');
    this.status.set('');
    this.search.set('');
    this.days.set(30);
    this.load();
  }

  sourceLabel(s: string): string {
    return SOURCES.find((x) => x.value === s)?.label ?? s;
  }

  tone(s: string | null | undefined): string {
    const v = (s ?? '').toLowerCase();
    if (/(complete|success|processed|done|approved)/.test(v)) return 'badge good';
    if (/(fail|error|reject)/.test(v)) return 'badge critical';
    if (/(await|review|pending|progress|processing|received|mixed)/.test(v)) return 'badge warning';
    return 'badge';
  }

  askChat(q: string): void {
    this.chat.ask(q, { fresh: true });
    this.openSubmission.set(null);
    this.router.navigateByUrl('/chat');
  }
}
