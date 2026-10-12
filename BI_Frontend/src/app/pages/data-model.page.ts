import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../api.service';
import { compact, full } from '../format';
import { CollectionRow } from '../models';
import { IconComponent } from '../shared/icon.component';
import { UiStateService } from '../ui-state.service';
import { load, loadable } from './load';

/** Every collection with its (estimated) size; click one to have the assistant explain it. */
@Component({
  selector: 'bi-data-model',
  imports: [FormsModule, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page-head">
      <h1>Data model</h1>
      <button type="button" class="ghost-btn" (click)="ui.ask('Give me an overview of the database: the main collections, what they hold and how they relate.')">
        <bi-icon name="sparkles" /> Explain the data model
      </button>
    </div>
    <section class="card">
      <div class="card-head">
        <h2>Collections <span class="muted">{{ cols().data?.length ?? '' }}</span></h2>
        <label class="field search-field"><bi-icon name="search" />
          <input [ngModel]="filter()" (ngModelChange)="filter.set($event)" placeholder="Filter collections" />
        </label>
      </div>
      @if (cols().data) {
        <div class="collections">
          @for (c of shown(); track c.collection) {
            <button type="button" class="collection" (click)="explain(c.collection)" [title]="full(c.documents) + ' documents (estimated)'">
              <div class="collection-top"><bi-icon name="database" /><span class="ellipsis">{{ c.collection }}</span><b>{{ compact(c.documents) }}</b></div>
              <div class="meter"><span class="fill sw-1" [style.width.%]="pct(c.documents)"></span></div>
            </button>
          } @empty { <div class="placeholder">No collection matches.</div> }
        </div>
        <p class="muted small">Document counts are estimates from collection metadata. Bars use a square-root scale so small collections stay visible.</p>
      } @else if (cols().error) { <div class="placeholder error"><bi-icon name="alert" /> {{ cols().error }}</div> }
      @else { <div class="placeholder"><span class="spinner"></span>Loading…</div> }
    </section>`,
})
export class DataModelPage {
  private api = inject(ApiService);
  ui = inject(UiStateService);
  cols = loadable<CollectionRow[]>();
  filter = signal('');
  compact = compact; full = full;

  shown = computed(() => {
    const f = this.filter().toLowerCase();
    return (this.cols().data ?? []).filter((c) => c.collection.toLowerCase().includes(f));
  });
  private max = computed(() => Math.max(1, ...(this.cols().data ?? []).map((c) => c.documents ?? 0)));

  constructor() { load(this.api.collections(), this.cols); }

  pct(n: number | null) { return n ? Math.max(1, (100 * Math.sqrt(n)) / Math.sqrt(this.max())) : 0; }

  explain(name: string) {
    this.ui.ask(`Explain the "${name}" collection: its fields, how it relates to other collections, and show a few example documents.`);
  }
}
