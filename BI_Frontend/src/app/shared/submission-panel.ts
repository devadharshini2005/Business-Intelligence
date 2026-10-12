import { Component, HostListener, effect, inject, input, output, signal } from '@angular/core';
import { DatePipe, DecimalPipe, KeyValuePipe } from '@angular/common';

import { ApiService, errorText } from '../core/api.service';
import { RunSummary, Submission } from '../core/models';

const SOURCE_LABELS: Record<string, string> = { email: 'Email', webhook: 'Webhook', manual_upload: 'Manual upload' };

/** Side panel with one submission: header, files, and each file's runs with workflow progress. */
@Component({
  selector: 'app-submission-panel',
  imports: [DatePipe, DecimalPipe, KeyValuePipe],
  templateUrl: './submission-panel.html',
  styleUrl: './submission-panel.scss',
})
export class SubmissionPanel {
  private readonly api = inject(ApiService);
  readonly submissionId = input.required<string>();
  readonly closed = output<void>();
  readonly ask = output<string>();

  readonly data = signal<Submission | null>(null);
  readonly loading = signal(true);
  readonly error = signal('');

  constructor() {
    effect(() => {
      const id = this.submissionId();
      this.loading.set(true);
      this.error.set('');
      this.data.set(null);
      this.api.submission(id).subscribe({
        next: (d) => {
          this.data.set(d);
          this.loading.set(false);
        },
        error: (e) => {
          this.error.set(errorText(e));
          this.loading.set(false);
        },
      });
    });
  }

  @HostListener('document:keydown.escape')
  close(): void {
    this.closed.emit();
  }

  sourceLabel(s: string): string {
    return SOURCE_LABELS[s] ?? s;
  }

  title(d: Submission): string {
    const x = d.details;
    return String(x['subject'] ?? x['reference_subject'] ?? 'Submission');
  }

  /** Header fields worth showing, in a readable order. */
  headerFields(d: Submission): { label: string; value: unknown }[] {
    const x = d.details as Record<string, any>;
    const fields: [string, unknown][] = [
      ['From', x['from_email'] ?? x['user_email'] ?? x['source_domain']],
      ['Received', x['date_received'] ?? x['received_at'] ?? x['uploaded_at']],
      ['Processed', x['processed_at']],
      ['Status', x['status']],
      ['Claim number', x['metadata']?.['payload']?.['claim_number']],
      ['Policy number', x['metadata']?.['payload']?.['policy_number']],
      ['Uploaded by', x['metadata']?.['user_name']],
    ];
    return fields.filter(([, v]) => v !== undefined && v !== null && v !== '').map(([label, value]) => ({ label, value }));
  }

  isDate(v: unknown): boolean {
    return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v);
  }

  progress(r: RunSummary): { done: number; total: number; pct: number } {
    const counts = r.node_status_counts ?? {};
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const done = counts['completed'] ?? 0;
    return { done, total, pct: total ? Math.round((100 * done) / total) : 0 };
  }

  statusClass(s: string | null | undefined): string {
    const v = (s ?? '').toLowerCase();
    if (/(complete|success|processed|done|approved)/.test(v)) return 'pill good';
    if (/(fail|error|reject)/.test(v)) return 'pill critical';
    if (/(await|review|pending|progress|processing|received|mixed)/.test(v)) return 'pill warning';
    return 'pill';
  }

  /** True when the step is already listed under "needs attention" (avoids showing it twice). */
  attentionAt(r: RunSummary, step: number): boolean {
    return (r.needs_attention ?? []).some((n) => n.step === step);
  }

  label(status: string): string {
    return status.replace(/_/g, ' ');
  }

  confidence(v: number | null | undefined): number | null {
    if (v === null || v === undefined) return null;
    return v <= 1 ? v * 100 : v;
  }

  askAbout(d: Submission): void {
    this.ask.emit(`What happened to submission ${d.submission_id}? Summarise its files, runs and anything that failed or needs approval.`);
  }
}
