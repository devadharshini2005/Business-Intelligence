import { Component, input, output } from '@angular/core';
import { DecimalPipe } from '@angular/common';

import { ReviewItem } from '../../core/models';

/** Runs waiting for a person's review, oldest first. Clicking one opens its submission. */
@Component({
  selector: 'app-review-queue',
  imports: [DecimalPipe],
  template: `
    <section class="card">
      <header>
        <span class="kind">Review queue</span>
        <h2>Waiting longest for review</h2>
        <p>Oldest first. Click one to open its submission.</p>
      </header>
      @if (items().length) {
        <ul>
          @for (r of items(); track r.run_id) {
            <li>
              <button type="button" (click)="open.emit(r.run_id)">
                <span class="age" [class.old]="(r.waiting_days ?? 0) >= 7">
                  <strong class="num">{{ r.waiting_days ?? '—' }}</strong><small>days</small>
                </span>
                <span class="what">
                  <span class="file" [title]="r.file">{{ r.file }}</span>
                  <span class="proc">{{ r.process }}</span>
                </span>
                @if (r.confidence !== null) {
                  <span class="badge" [class.warning]="r.confidence < 80" title="Extraction confidence">
                    {{ r.confidence | number: '1.0-0' }}%
                  </span>
                }
              </button>
            </li>
          }
        </ul>
      } @else {
        <p class="quiet">Nothing is waiting for review.</p>
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
      background: color-mix(in srgb, var(--status-warning) 20%, transparent);
      color: var(--status-warning-text);
    }
    ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    button {
      display: flex;
      align-items: center;
      gap: 12px;
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
    .age {
      flex: none;
      width: 44px;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 3px 0;
      border-radius: 7px;
      background: var(--surface-2);
      line-height: 1.1;
      strong {
        font-size: 15px;
      }
      small {
        font-size: 10px;
        color: var(--text-muted);
      }
      &.old {
        background: color-mix(in srgb, var(--status-warning) 18%, transparent);
        strong {
          color: var(--status-warning-text);
        }
      }
    }
    .what {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
    }
    .file {
      font-size: 13px;
      font-weight: 500;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .proc {
      font-size: 11px;
      color: var(--text-muted);
    }
    .quiet {
      font-size: 13px;
      color: var(--text-muted);
    }
  `,
})
export class ReviewQueue {
  readonly items = input.required<ReviewItem[]>();
  readonly open = output<string>();
}
