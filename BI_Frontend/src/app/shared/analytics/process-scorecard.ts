import { Component, computed, input, output } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';

import { ProcessRow } from '../../core/models';
import { Sparkline } from './sparkline';

/**
 * One row per process: volume, how runs ended (a stacked bar), completion, confidence, speed and trend.
 * Clicking a row scopes the whole page to that process; clicking it again clears the filter.
 */
@Component({
  selector: 'app-process-scorecard',
  imports: [DecimalPipe, DatePipe, Sparkline],
  template: `
    <section class="card flush">
      <header class="head">
        <div>
          <span class="kind">Processes</span>
          <h2>Process scorecard</h2>
          <p>Click a process to focus the whole page on it.</p>
        </div>
        <div class="legend" aria-hidden="true">
          <span><i class="completed"></i>Completed</span>
          <span><i class="review"></i>Awaiting review</span>
          <span><i class="failed"></i>Failed</span>
          <span><i class="rejected"></i>Rejected</span>
        </div>
      </header>

      @if (rows().length) {
        <div class="wrap">
          <table class="grid">
            <thead>
              <tr>
                <th>Process</th>
                <th class="r">Runs</th>
                <th class="outcome">How runs ended</th>
                <th class="r">Completion</th>
                <th class="r">Confidence</th>
                <th class="r">Avg time</th>
                <th>Trend</th>
                <th>Last run</th>
              </tr>
            </thead>
            <tbody>
              @for (p of rows(); track p.process_id) {
                <tr class="clickable" tabindex="0" [class.selected]="p.process_id === selected()"
                    [class.dimmed]="selected() && p.process_id !== selected()"
                    (click)="toggle(p)" (keydown.enter)="toggle(p)"
                    [title]="p.process_id === selected() ? 'Show all processes' : 'Focus on ' + p.name">
                  <td class="name">{{ p.name }}</td>
                  <td class="r num strong">{{ p.runs | number }}</td>
                  <td class="outcome"><div class="outcome-cell">
                    <span class="stack" [attr.aria-label]="p.completed + ' completed, ' + p.review + ' awaiting review, ' + p.failed + ' failed, ' + p.rejected + ' rejected'">
                      <i class="completed" [style.flex-grow]="p.completed"></i>
                      <i class="review" [style.flex-grow]="p.review"></i>
                      <i class="failed" [style.flex-grow]="p.failed"></i>
                      <i class="rejected" [style.flex-grow]="p.rejected"></i>
                    </span>
                    <span class="counts num">
                      {{ p.completed }} · {{ p.review }} · {{ p.failed }}@if (p.rejected) { · {{ p.rejected }} }
                    </span>
                  </div></td>
                  <td class="r">
                    @if (p.completion !== null) {
                      <span class="badge" [class.good]="p.completion >= 75" [class.warning]="p.completion >= 40 && p.completion < 75"
                            [class.critical]="p.completion < 40">{{ p.completion | number: '1.0-0' }}%</span>
                    } @else { — }
                  </td>
                  <td class="r num">{{ p.confidence === null ? '—' : (p.confidence | number: '1.0-1') + '%' }}</td>
                  <td class="r num">{{ p.time_s === null ? '—' : (p.time_s | number: '1.0-1') + ' s' }}</td>
                  <td><app-sparkline [values]="p.spark" [width]="84" [height]="22" /></td>
                  <td class="muted num">{{ p.last_run ? (p.last_run | date: 'd MMM, HH:mm') : '—' }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      } @else {
        <div class="empty-state"><strong>No runs in this period</strong><p>Widen the period to see how processes performed.</p></div>
      }
    </section>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
    }
    .card.flush {
      flex: 1;
      padding: 0;
      overflow: hidden;
    }
    .head {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: flex-end;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      h2 {
        margin: 2px 0 0;
        font-size: 14px;
        font-weight: 600;
      }
      p {
        margin: 2px 0 0;
        font-size: 12px;
        color: var(--text-muted);
      }
    }
    .kind {
      display: inline-block;
      padding: 0 7px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 600;
      line-height: 17px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      background: color-mix(in srgb, var(--series-2) 13%, transparent);
      color: var(--series-2);
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      font-size: 11px;
      color: var(--text-secondary);
      span {
        display: inline-flex;
        align-items: center;
        gap: 5px;
      }
      i {
        width: 9px;
        height: 9px;
        border-radius: 2px;
      }
    }
    .completed {
      background: var(--status-good);
    }
    .review {
      background: var(--status-warning);
    }
    .failed {
      background: var(--status-critical);
    }
    .rejected {
      background: var(--series-5);
    }
    .wrap {
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }
    @media (max-width: 700px) {
      .legend {
        gap: 8px;
      }
      .name {
        max-width: 160px;
      }
    }
    .name {
      font-weight: 500;
      max-width: 240px;
    }
    .strong {
      font-weight: 600;
    }
    .outcome {
      min-width: 200px;
    }
    .outcome-cell {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .stack {
      display: flex;
      flex: 1;
      height: 10px;
      gap: 2px;
      border-radius: 3px;
      overflow: hidden;
      background: var(--surface-2);
      i {
        flex-basis: 0;
        flex-grow: 0;
        min-width: 0;
      }
    }
    .counts {
      flex: none;
      font-size: 11px;
      color: var(--text-muted);
    }
    .muted {
      color: var(--text-muted);
      font-size: 12px;
    }
    tr.selected td {
      background: color-mix(in srgb, var(--accent) 8%, transparent);
    }
    tr.selected .name {
      color: var(--accent);
    }
    tr.dimmed td {
      opacity: 0.55;
    }
  `,
})
export class ProcessScorecard {
  readonly rows = input.required<ProcessRow[]>();
  /** The process the page is scoped to, if any. */
  readonly selected = input<string>('');
  readonly select = output<string>();

  readonly total = computed(() => this.rows().reduce((n, r) => n + r.runs, 0));

  toggle(p: ProcessRow): void {
    if (!p.process_id) return;
    this.select.emit(p.process_id === this.selected() ? '' : p.process_id);
  }
}
