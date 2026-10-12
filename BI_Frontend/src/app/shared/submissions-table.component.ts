import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { dateTime, SOURCE_LABEL } from '../format';
import { SubmissionRow } from '../models';
import { StatusBadgeComponent } from './status-badge.component';

@Component({
  selector: 'bi-submissions-table',
  imports: [StatusBadgeComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!rows().length) {
      <div class="placeholder">No submissions match.</div>
    } @else {
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Received</th><th>Source</th><th>Title</th><th>From</th>
              <th class="num">Files</th><th class="num">Runs</th><th>Status</th><th>Run status</th>
            </tr>
          </thead>
          <tbody>
            @for (r of rows(); track r.submission_id) {
              <tr class="clickable" tabindex="0" (click)="open.emit(r.submission_id)" (keydown.enter)="open.emit(r.submission_id)">
                <td class="nowrap">{{ when(r.received_at) }}</td>
                <td><span class="src src-{{ r.source }}">{{ source(r.source) }}</span></td>
                <td class="title-cell">{{ r.title || '(no subject)' }}</td>
                <td class="muted ellipsis">{{ r.from || '–' }}</td>
                <td class="num">{{ r.files }}</td>
                <td class="num">{{ r.runs }}</td>
                <td><bi-status [status]="r.status" /></td>
                <td><bi-status [status]="r.run_status" /></td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    }`,
})
export class SubmissionsTableComponent {
  rows = input.required<SubmissionRow[]>();
  open = output<string>();
  when = dateTime;
  source = (s: string) => SOURCE_LABEL[s] || s;
}
