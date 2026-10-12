import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { statusRole } from '../format';
import { IconComponent } from './icon.component';

const ICON = { good: 'check-circle', critical: 'x-circle', warning: 'alert', info: 'clock', neutral: 'circle' };

/** Status is never colour-alone: icon + label + reserved status colour. */
@Component({
  selector: 'bi-status',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="status status-{{ role() }}">
    <bi-icon [name]="icon()" [size]="13" [stroke]="2.4" />{{ label() }}</span>`,
})
export class StatusBadgeComponent {
  status = input<string | null | undefined>(null);
  role = computed(() => statusRole(this.status()));
  icon = computed(() => ICON[this.role()]);
  label = computed(() => (this.status() || 'unknown').replaceAll('_', ' '));
}
