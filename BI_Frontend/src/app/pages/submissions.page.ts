import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../api.service';
import { SubmissionRow } from '../models';
import { IconComponent } from '../shared/icon.component';
import { SubmissionsTableComponent } from '../shared/submissions-table.component';
import { UiStateService } from '../ui-state.service';
import { load, loadable } from './load';

@Component({
  selector: 'bi-submissions',
  imports: [FormsModule, IconComponent, SubmissionsTableComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page-head"><h1>Submissions</h1></div>
    <section class="card">
      <form class="filters" (ngSubmit)="search()">
        <label class="field search-field"><bi-icon name="search" />
          <input name="search" [(ngModel)]="q.search" placeholder="Subject, sender, claim or policy number" />
        </label>
        <select name="source" [(ngModel)]="q.source" (change)="search()" aria-label="Source">
          <option value="">All sources</option>
          <option value="email">Email</option>
          <option value="webhook">Webhook</option>
          <option value="manual_upload">Manual upload</option>
        </select>
        <input class="field" name="status" [(ngModel)]="q.status" placeholder="Status (e.g. failed)" aria-label="Status" />
        <select name="days" [(ngModel)]="q.days" (change)="search()" aria-label="Received">
          <option [ngValue]="0">Any time</option>
          <option [ngValue]="1">Last 24 hours</option>
          <option [ngValue]="7">Last 7 days</option>
          <option [ngValue]="30">Last 30 days</option>
          <option [ngValue]="90">Last 90 days</option>
        </select>
        <select name="limit" [(ngModel)]="q.limit" (change)="search()" aria-label="Rows">
          <option [ngValue]="25">25 rows</option>
          <option [ngValue]="50">50 rows</option>
          <option [ngValue]="100">100 rows</option>
          <option [ngValue]="200">200 rows</option>
        </select>
        <button class="primary-btn" type="submit">Search</button>
      </form>
      @if (rows().data; as r) { <bi-submissions-table [rows]="r" (open)="ui.openSubmissionId.set($event)" /> }
      @else if (rows().error) { <div class="placeholder error"><bi-icon name="alert" /> {{ rows().error }}</div> }
      @else { <div class="placeholder"><span class="spinner"></span>Loading…</div> }
    </section>`,
})
export class SubmissionsPage {
  private api = inject(ApiService);
  ui = inject(UiStateService);
  rows = loadable<SubmissionRow[]>();
  q = { search: '', source: '', status: '', days: 30, limit: 50 };

  constructor() { this.search(); }

  search() { load(this.api.submissions({ ...this.q, status: this.q.status.trim() }), this.rows); }
}
