import { ChangeDetectionStrategy, Component, effect, inject, input, output, signal } from '@angular/core';

import { ApiService } from '../api.service';
import { dateTime, duration, SOURCE_LABEL } from '../format';
import { RunDetails, Submission } from '../models';
import { IconComponent } from './icon.component';
import { StatusBadgeComponent } from './status-badge.component';

interface RunState { loading: boolean; error?: string; data?: RunDetails; }

/** Submission → files → runs (collapsed); a run expands to every workflow node in order. */
@Component({
  selector: 'bi-submission-drawer',
  imports: [IconComponent, StatusBadgeComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'close.emit()' },
  template: `
    <div class="scrim" (click)="close.emit()"></div>
    <aside class="drawer" role="dialog" aria-label="Submission details">
      <div class="drawer-head">
        <div>
          <div class="eyebrow">Submission · {{ id() }}</div>
          <h2>{{ title() }}</h2>
        </div>
        <button type="button" class="icon-btn" (click)="close.emit()" aria-label="Close"><bi-icon name="x" /></button>
      </div>

      @if (error()) {
        <div class="placeholder error"><bi-icon name="alert" /> {{ error() }}</div>
      } @else if (!sub()) {
        <div class="placeholder"><span class="spinner"></span>Loading…</div>
      } @else {
        @let s = sub()!;
        <div class="drawer-meta">
          <span class="src src-{{ s.source }}">{{ source(s.source) }}</span>
          <bi-status [status]="$any(s.details)['status']" />
          <span class="muted">{{ s.totals.files }} files · {{ s.totals.runs }} runs</span>
          <bi-status [status]="s.totals.run_status" />
        </div>
        @if (s.note) { <p class="muted small">{{ s.note }}</p> }
        <button type="button" class="ghost-btn" (click)="ask.emit('Explain what happened to submission ' + s.submission_id + ' and anything that needs attention.')">
          <bi-icon name="sparkles" /> Ask the assistant about this submission
        </button>

        <ul class="tree">
          @for (f of s.files; track f.file_id) {
            <li>
              <div class="tree-file">
                <bi-icon name="workflow" />
                <span class="ellipsis grow">{{ f.filename || f.file_id }}</span>
                <span class="muted small">{{ f.file_type }}{{ f.pages ? ' · ' + f.pages + ' p' : '' }}</span>
                <bi-status [status]="f.run_status" />
              </div>
              <ul>
                @for (r of f.runs; track r.run_id) {
                  <li class="tree-run">
                    <button type="button" class="run-row" (click)="toggle(r.run_id)" [attr.aria-expanded]="!!runs()[r.run_id]">
                      <bi-icon [name]="runs()[r.run_id] ? 'chevron-down' : 'chevron-right'" [size]="14" />
                      <span class="grow ellipsis"><b>{{ r.process || 'Run' }}</b> <span class="muted">· {{ r.node_progress }}</span></span>
                      <span class="muted small">{{ dur(r.duration_s) }}</span>
                      <bi-status [status]="r.status" />
                    </button>
                    @if (r.needs_attention.length) {
                      <div class="attention">
                        @for (n of r.needs_attention; track n.step) {
                          <span><bi-status [status]="n.status" /> step {{ n.step }} · {{ n.name }}</span>
                        }
                      </div>
                    }
                    @if (runs()[r.run_id]; as st) {
                      @if (st.loading) { <div class="placeholder small"><span class="spinner"></span>Loading nodes…</div> }
                      @if (st.error) { <div class="placeholder error small">{{ st.error }}</div> }
                      @if (st.data) {
                        <ol class="nodes">
                          @for (n of st.data.nodes; track n.step) {
                            <li>
                              <span class="step">{{ n.step }}</span>
                              <span class="grow">{{ n.name || n.node_id }}
                                @if (n.error?.['reason']) { <span class="node-err">{{ n.error?.['reason'] }}</span> }
                              </span>
                              <span class="muted small">{{ dur(n.duration_s) }}</span>
                              <bi-status [status]="n.status" />
                            </li>
                          }
                        </ol>
                      }
                    }
                  </li>
                } @empty {
                  <li class="muted small tree-empty">No runs for this file</li>
                }
              </ul>
            </li>
          }
        </ul>
      }
    </aside>`,
})
export class SubmissionDrawerComponent {
  private api = inject(ApiService);
  id = input.required<string>();
  close = output<void>();
  ask = output<string>();

  sub = signal<Submission | null>(null);
  error = signal<string | null>(null);
  runs = signal<Record<string, RunState>>({});
  source = (s: string) => SOURCE_LABEL[s] || s;
  dur = duration;

  constructor() {
    effect(() => {
      const id = this.id();
      this.sub.set(null);
      this.error.set(null);
      this.runs.set({});
      this.api.submission(id).subscribe({ next: (s) => this.sub.set(s), error: (e: Error) => this.error.set(e.message) });
    });
  }

  title() {
    const d = this.sub()?.details ?? {};
    const t = (d['subject'] || d['reference_subject'] || '') as string;
    const when = (d['date_received'] || d['received_at'] || d['uploaded_at']) as string | undefined;
    return t || (when ? `Received ${dateTime(when)}` : 'Submission');
  }

  toggle(runId: string) {
    const cur = { ...this.runs() };
    if (cur[runId]) {
      delete cur[runId];
      this.runs.set(cur);
      return;
    }
    this.runs.set({ ...cur, [runId]: { loading: true } });
    this.api.run(runId).subscribe({
      next: (data) => this.runs.update((m) => ({ ...m, [runId]: { loading: false, data } })),
      error: (e: Error) => this.runs.update((m) => ({ ...m, [runId]: { loading: false, error: e.message } })),
    });
  }
}
