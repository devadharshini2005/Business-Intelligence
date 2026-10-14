import { Component, computed, input, output } from '@angular/core';

import { Bottleneck } from '../../core/models';

/**
 * Workflow steps where runs stopped - failed, waiting for approval, or rejected - from
 * file_process_tracker. The bar is split by why they stopped.
 */
@Component({
  selector: 'app-bottlenecks-panel',
  template: `
    <section class="card">
      <header>
        <span class="kind">Bottlenecks</span>
        <h2>Where runs get stuck</h2>
        <p>Workflow steps with the most runs that failed or are waiting.</p>
      </header>
      @if (items().length) {
        <ol>
          @for (b of items(); track b.process + b.step) {
            <li>
              <button type="button" (click)="select.emit(b.process_id)" [title]="'Focus on ' + b.process">
                <span class="labels">
                  <span class="step">{{ b.step }}</span>
                  <span class="proc">{{ b.process }}</span>
                </span>
                <span class="bar" [style.width.%]="(100 * b.total) / max()">
                  <i class="failed" [style.flex-grow]="b.failed"></i>
                  <i class="waiting" [style.flex-grow]="b.awaiting_approval"></i>
                  <i class="rejected" [style.flex-grow]="b.rejected"></i>
                </span>
                <span class="why">
                  @if (b.failed) { <span>{{ b.failed }} failed</span> }
                  @if (b.awaiting_approval) { <span>{{ b.awaiting_approval }} waiting</span> }
                  @if (b.rejected) { <span>{{ b.rejected }} rejected</span> }
                </span>
              </button>
            </li>
          }
        </ol>
      } @else {
        <p class="quiet">No run stopped at a workflow step in this period.</p>
      }
    </section>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
    }
    .card {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    h2 {
      margin: 2px 0 0;
      font-size: 14px;
      font-weight: 600;
    }
    header p {
      margin: 2px 0 0;
      font-size: 12px;
      color: var(--text-muted);
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
      background: color-mix(in srgb, var(--status-critical) 12%, transparent);
      color: var(--status-critical-text);
    }
    ol {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    li button {
      display: grid;
      grid-template-columns: minmax(0, 170px) minmax(0, 1fr);
      grid-template-areas: 'labels bar' 'labels why';
      align-items: center;
      gap: 3px 12px;
      width: 100%;
      padding: 6px 8px;
      border: 0;
      border-radius: 7px;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
      &:hover {
        background: var(--surface-2);
      }
    }
    .labels {
      grid-area: labels;
      display: flex;
      flex-direction: column;
      min-width: 0;
    }
    .step {
      font-size: 13px;
      font-weight: 500;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .proc {
      font-size: 11px;
      color: var(--text-muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .bar {
      grid-area: bar;
      display: flex;
      gap: 2px;
      height: 10px;
      min-width: 6px;
      border-radius: 3px;
      overflow: hidden;
      i {
        flex-basis: 0;
        flex-grow: 0;
      }
    }
    .failed {
      background: var(--status-critical);
    }
    .waiting {
      background: var(--status-warning);
    }
    .rejected {
      background: var(--series-5);
    }
    .why {
      grid-area: why;
      display: flex;
      gap: 10px;
      font-size: 11px;
      color: var(--text-secondary);
    }
    @media (max-width: 500px) {
      li button {
        grid-template-columns: minmax(0, 110px) minmax(0, 1fr);
      }
    }
    .quiet {
      font-size: 13px;
      color: var(--text-muted);
    }
  `,
})
export class BottlenecksPanel {
  readonly items = input.required<Bottleneck[]>();
  readonly select = output<string>();

  readonly max = computed(() => Math.max(1, ...this.items().map((b) => b.total)));
}
