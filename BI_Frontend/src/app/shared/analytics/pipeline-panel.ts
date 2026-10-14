import { Component, computed, input } from '@angular/core';
import { DecimalPipe } from '@angular/common';

import { Pipeline } from '../../core/models';

/**
 * The document pipeline - received → processed → extracted → completed - with the conversion between
 * each pair of stages, and beside it where the documents that did not get through stopped.
 * Stages use one blue hue, light to dark: they are ordered, not categories.
 */
@Component({
  selector: 'app-pipeline-panel',
  imports: [DecimalPipe],
  template: `
    <section class="card">
      <header class="head">
        <div>
          <span class="kind">Pipeline</span>
          <h2>Document pipeline</h2>
          <p>How far each received document got - the furthest point any of its runs reached.</p>
        </div>
        @if (overall() !== null) {
          <div class="overall"><strong class="num">{{ overall() }}%</strong><span>received → completed</span></div>
        }
      </header>

      <div class="body">
        <ol class="stages">
          @for (s of pipeline().stages; track s.key; let i = $index) {
            @if (i > 0) {
              <li class="conv" aria-hidden="true">
                <span class="num">{{ conversion(i) }}</span>
              </li>
            }
            <li class="stage" [title]="s.hint">
              <span class="name">{{ s.label }}</span>
              <span class="track"><i [style.width.%]="width(s.value)" [style.background]="'var(--ord-' + (i + 1) + ')'"></i></span>
              <span class="value num">{{ s.value | number }}</span>
            </li>
          }
        </ol>

        <div class="stops">
          <h3>Where documents stop</h3>
          @for (l of pipeline().leaks; track l.key) {
            <div class="stop" [attr.data-tone]="l.tone">
              <span class="dot"></span>
              <span class="what">{{ l.label }}</span>
              <span class="num">{{ l.value | number }}</span>
            </div>
          }
        </div>
      </div>
      <p class="caveat">{{ pipeline().note }}</p>
    </section>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      --ord-1: #86b6ef;
      --ord-2: #5598e7;
      --ord-3: #2a78d6;
      --ord-4: #184f95;
    }
    :host-context([data-theme='dark']) {
      --ord-1: #b7d3f6;
      --ord-2: #86b6ef;
      --ord-3: #3987e5;
      --ord-4: #1d5fae;
    }
    .card {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
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
    .overall {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      strong {
        font-size: 22px;
        font-weight: 600;
        line-height: 1;
      }
      span {
        margin-top: 3px;
        font-size: 11px;
        color: var(--text-muted);
      }
    }
    .body {
      flex: 1;
      align-items: center;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 200px;
      gap: 20px;
    }
    @media (max-width: 700px) {
      .body {
        grid-template-columns: minmax(0, 1fr);
      }
      .stage,
      .conv {
        grid-template-columns: 70px minmax(0, 1fr) 40px;
        gap: 8px;
      }
      .stops {
        padding: 12px 0 0;
        border-left: 0;
        border-top: 1px solid var(--border);
      }
      .head {
        flex-direction: column;
      }
      .overall {
        align-items: flex-start;
      }
    }
    .stages {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
    }
    .stage {
      display: grid;
      grid-template-columns: 78px minmax(0, 1fr) 52px;
      align-items: center;
      gap: 10px;
      font-size: 13px;
    }
    .name {
      color: var(--text-secondary);
    }
    .track {
      height: 22px;
      border-radius: 5px;
      background: var(--surface-2);
      overflow: hidden;
      i {
        display: block;
        height: 100%;
        min-width: 3px;
        border-radius: 5px;
        transition: width 0.4s ease-out;
      }
    }
    .value {
      text-align: right;
      font-weight: 600;
    }
    .conv {
      display: grid;
      grid-template-columns: 78px minmax(0, 1fr) 52px;
      gap: 10px;
      height: 18px;
      span {
        grid-column: 2;
        align-self: center;
        font-size: 11px;
        color: var(--text-muted);
        &::before {
          content: '↓ ';
        }
      }
    }
    .stops {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding-left: 16px;
      border-left: 1px solid var(--border);
      h3 {
        margin: 0 0 2px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--text-muted);
      }
    }
    .stop {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      .what {
        flex: 1;
        color: var(--text-secondary);
      }
      .num {
        font-weight: 600;
      }
      .dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--text-muted);
      }
      &[data-tone='warning'] .dot {
        background: var(--status-warning);
      }
      &[data-tone='critical'] .dot {
        background: var(--status-critical);
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
      background: color-mix(in srgb, var(--accent) 11%, transparent);
      color: var(--accent);
    }
  `,
})
export class PipelinePanel {
  readonly pipeline = input.required<Pipeline>();

  private readonly first = computed(() => this.pipeline().stages[0]?.value ?? 0);

  readonly overall = computed(() => {
    const st = this.pipeline().stages;
    return st.length && st[0].value ? Math.round((100 * st[st.length - 1].value) / st[0].value) : null;
  });

  width(v: number): number {
    return this.first() ? Math.max(1.5, (100 * v) / this.first()) : 0;
  }

  /** Share of the previous stage that reached this one. */
  conversion(i: number): string {
    const st = this.pipeline().stages;
    const prev = st[i - 1].value;
    return prev ? `${Math.round((100 * st[i].value) / prev)}% continue` : '—';
  }
}
