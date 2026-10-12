import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ApiService, errorText } from '../core/api.service';
import { CollectionRow, Envelope, SchemaField } from '../core/models';

/**
 * What the database holds: collections (MCP list_collections) and, for the one selected, the
 * fields found by sampling (MCP infer_collection_schema).
 */
@Component({
  selector: 'app-catalog',
  imports: [DecimalPipe, FormsModule],
  templateUrl: './catalog.html',
  styleUrl: './catalog.scss',
})
export class CatalogPage {
  private readonly api = inject(ApiService);

  readonly collections = signal<CollectionRow[]>([]);
  readonly loading = signal(false);
  readonly error = signal('');
  readonly filter = signal('');

  readonly selected = signal<string | null>(null);
  readonly schema = signal<Envelope<SchemaField> | null>(null);
  readonly schemaLoading = signal(false);
  readonly schemaError = signal('');
  readonly fieldFilter = signal('');

  readonly visible = computed(() => {
    const f = this.filter().trim().toLowerCase();
    return f ? this.collections().filter((c) => c.collection.toLowerCase().includes(f)) : this.collections();
  });
  readonly totalDocs = computed(() => this.collections().reduce((n, c) => n + (c.approx_documents ?? 0), 0));
  readonly largest = computed(() => Math.max(1, ...this.collections().map((c) => c.approx_documents ?? 0)));
  readonly fields = computed(() => {
    const f = this.fieldFilter().trim().toLowerCase();
    const rows = this.schema()?.rows ?? [];
    return f ? rows.filter((r) => r.field.toLowerCase().includes(f)) : rows;
  });
  readonly selectedRow = computed(() => this.collections().find((c) => c.collection === this.selected()) ?? null);

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set('');
    this.api.collections().subscribe({
      next: (d) => {
        this.collections.set(d.rows);
        this.loading.set(false);
        if (!this.selected() && d.rows.length) this.open(d.rows[0].collection);
      },
      error: (e) => {
        this.error.set(errorText(e));
        this.loading.set(false);
      },
    });
  }

  open(name: string): void {
    this.selected.set(name);
    this.schema.set(null);
    this.schemaError.set('');
    this.fieldFilter.set('');
    this.schemaLoading.set(true);
    this.api.schema(name).subscribe({
      next: (d) => {
        if (this.selected() !== name) return; // a later click won
        this.schema.set(d);
        this.schemaLoading.set(false);
      },
      error: (e) => {
        if (this.selected() !== name) return;
        this.schemaError.set(errorText(e));
        this.schemaLoading.set(false);
      },
    });
  }

  /** Nesting depth of a dotted field path, for indentation. */
  depth(field: string): number {
    return field.split('.').length - 1;
  }
}
