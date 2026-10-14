import { Component, computed, input, output } from '@angular/core';
import { DecimalPipe } from '@angular/common';

import { Kpi } from '../../core/models';
import { Sparkline } from './sparkline';

/**
 * One headline figure: label, value, change vs the previous period and a sparkline.
 * Direction is shown by an arrow and the sign, so colour is reinforcement, never the only signal.
 */
@Component({
  selector: 'app-kpi-tile',
  imports: [DecimalPipe, Sparkline],
  template: `
    <button type="button" class="tile" [class.active]="active()" (click)="pick.emit(kpi().key)"
            [title]="kpi().hint ?? ''">
      <span class="top">
        <span class="label">{{ kpi().title }}</span>
        @if (deltaText(); as d) {
          <span class="badge" [class.good]="tone() === 'good'" [class.critical]="tone() === 'bad'"
                title="Change vs the previous period of the same length">{{ d }}</span>
        } @else {
          <span class="none" title="No previous period to compare with">—</span>
        }
      </span>
      <span class="bottom">
        <span class="value num">
          @if (kpi().value === null) { — }
          @else { {{ kpi().value | number: '1.0-1' }}<small>{{ kpi().unit }}</small> }
        </span>
        <app-sparkline [values]="kpi().spark" [color]="sparkColor()" />
      </span>
      @if (kpi().hint) { <span class="hint">{{ kpi().hint }}</span> }
    </button>
  `,
  styles: `
    .tile {
      display: flex;
      flex-direction: column;
      gap: 8px;
      width: 100%;
      height: 100%;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface-1);
      box-shadow: 0 1px 2px rgba(11, 11, 11, 0.05);
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
      transition: border-color 0.12s, background 0.12s;
      &:hover {
        border-color: var(--border-strong);
      }
      &.active {
        border-color: var(--accent);
        box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 20%, transparent);
      }
    }
    .top,
    .bottom {
      display: flex;
      justify-content: space-between;
      gap: 8px;
    }
    .top {
      align-items: flex-start;
    }
    .bottom {
      align-items: flex-end;
    }
    .label {
      min-width: 0;
      font-size: 12px;
      font-weight: 500;
      color: var(--text-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .none {
      font-size: 11px;
      color: var(--text-muted);
    }
    .value {
      font-size: 22px;
      font-weight: 600;
      line-height: 1;
      letter-spacing: -0.02em;
      small {
        margin-left: 1px;
        font-size: 13px;
        font-weight: 500;
        color: var(--text-secondary);
      }
    }
    .hint {
      font-size: 11px;
      color: var(--text-muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  `,
})
export class KpiTile {
  readonly kpi = input.required<Kpi>();
  readonly active = input(false);
  readonly pick = output<string>();

  /** good / bad / neutral, from the direction of change and which way is better for this figure. */
  readonly tone = computed<'good' | 'bad' | 'neutral'>(() => {
    const { delta, better } = this.kpi();
    if (delta === null || better === 'neutral' || Math.abs(delta) < 0.0005) return 'neutral';
    return (better === 'higher') === delta > 0 ? 'good' : 'bad';
  });

  readonly deltaText = computed(() => {
    const { delta, delta_kind } = this.kpi();
    if (delta === null) return null;
    const arrow = Math.abs(delta) < 0.0005 ? '→' : delta > 0 ? '↑' : '↓';
    const size = Math.abs(delta);
    const text = delta_kind === 'points'
      ? `${size.toFixed(1)} pts`
      : delta >= 9 ? `${Math.round(1 + delta)}×` // +3,267% reads better as "34×"
        : `${Math.round(size * 100)}%`;
    return `${arrow} ${text}`;
  });

  readonly sparkColor = computed(() =>
    this.tone() === 'good' ? 'var(--status-good)' : this.tone() === 'bad' ? 'var(--status-critical)' : 'var(--accent)',
  );
}
