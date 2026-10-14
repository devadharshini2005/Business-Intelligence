import { Component, input, output } from '@angular/core';

import { Insight } from '../../core/models';

const LABELS: Record<Insight['kind'], string> = { observation: 'Observation', risk: 'Risk', gap: 'No data' };

/**
 * Sentences templated by the backend around figures it computed (dashboard.py insights()) - no model
 * writes them, so every number here is one the page also shows. "Ask" hands one to the chatbot.
 */
@Component({
  selector: 'app-insights-panel',
  template: `
    <section class="card">
      <header>
        <span class="kind">Insights</span>
        <h2>What stands out</h2>
      </header>
      @if (insights().length) {
        <ul>
          @for (i of insights(); track $index) {
            <li [attr.data-kind]="i.kind">
              <span class="icon" aria-hidden="true">{{ i.kind === 'observation' ? 'i' : '!' }}</span>
              <div>
                <span class="tag">{{ label(i.kind) }}</span>
                <p>{{ i.text }}</p>
                <button type="button" class="ask" (click)="ask.emit(i.text)">Ask why →</button>
              </div>
            </li>
          }
        </ul>
      } @else {
        <p class="quiet">Nothing unusual in this period.</p>
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
    .kind {
      display: inline-block;
      padding: 0 7px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 600;
      line-height: 17px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      background: color-mix(in srgb, var(--series-3) 14%, transparent);
      color: var(--series-3);
    }
    ul {
      list-style: none;
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      margin: 0 -6px 0 0;
      padding: 0 6px 20px 0; /* room for the fade, so the last item stays crisp */
      display: flex;
      flex-direction: column;
      gap: 12px;
      scrollbar-gutter: stable;
      /* Fade the bottom edge so it is obvious there is more to scroll to. */
      mask-image: linear-gradient(to bottom, #000 calc(100% - 24px), transparent);
    }
    .card {
      min-height: 0;
    }
    header {
      flex: none;
    }
    li {
      flex: none;
    }
    li {
      display: flex;
      gap: 10px;
    }
    .icon {
      flex: none;
      display: grid;
      place-items: center;
      width: 20px;
      height: 20px;
      margin-top: 1px;
      border-radius: 50%;
      font-size: 11px;
      font-weight: 700;
      background: var(--surface-2);
      color: var(--text-secondary);
    }
    [data-kind='risk'] .icon {
      background: color-mix(in srgb, var(--status-warning) 22%, transparent);
      color: var(--status-warning-text);
    }
    [data-kind='gap'] .icon {
      background: color-mix(in srgb, var(--status-critical) 14%, transparent);
      color: var(--status-critical-text);
    }
    .tag {
      font-size: 11px;
      font-weight: 600;
      color: var(--text-muted);
    }
    p {
      margin: 1px 0 0;
      font-size: 13px;
      line-height: 1.45;
    }
    .ask {
      margin-top: 2px;
      padding: 0;
      border: 0;
      background: none;
      color: var(--accent);
      font-size: 12px;
      cursor: pointer;
      &:hover {
        text-decoration: underline;
      }
    }
    .quiet {
      font-size: 13px;
      color: var(--text-muted);
    }
  `,
})
export class InsightsPanel {
  readonly insights = input.required<Insight[]>();
  readonly ask = output<string>();

  label(kind: Insight['kind']): string {
    return LABELS[kind];
  }
}
