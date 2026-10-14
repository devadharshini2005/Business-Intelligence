import { Injectable, computed, inject, signal } from '@angular/core';

import { ApiService, errorText } from './api.service';
import { DashboardData } from './models';

/** Data older than this is refreshed in the background when the page is shown again. */
const STALE_MS = 5 * 60_000;
const MAX_CACHED = 12;

interface Entry {
  data: DashboardData;
  at: number;
}

/**
 * The Analytics page's filters and data, kept for the whole session. A page component is destroyed
 * when you navigate away; this store is not, so coming back shows the last view at once.
 *
 * Each filter combination (period · source · process) is cached. Showing one that is cached never
 * blanks the page: stale data stays on screen while a quiet background refresh replaces it.
 */
@Injectable({ providedIn: 'root' })
export class AnalyticsStore {
  private readonly api = inject(ApiService);
  private readonly cache = new Map<string, Entry>();
  private inflight = '';

  readonly days = signal(30);
  readonly source = signal('');
  readonly process = signal('');

  readonly data = signal<DashboardData | null>(null);
  /** First load of a filter combination: nothing to show yet. */
  readonly loading = signal(false);
  /** Refreshing data that is already on screen. */
  readonly refreshing = signal(false);
  readonly error = signal('');
  readonly fetchedAt = signal<number | null>(null);

  readonly busy = computed(() => this.loading() || this.refreshing());

  private key(): string {
    return `${this.days()}|${this.source()}|${this.process()}`;
  }

  /**
   * Show the current filters: from the cache when possible, fetching only what is missing or stale.
   * `force` (the Refresh button) always fetches, keeping what's on screen meanwhile.
   */
  show(force = false): void {
    const key = this.key();
    const hit = this.cache.get(key);
    if (hit) {
      this.data.set(hit.data);
      this.fetchedAt.set(hit.at);
      this.error.set('');
    }
    const fresh = hit && Date.now() - hit.at < STALE_MS;
    if (fresh && !force) {
      // Shown from memory; a request still running for other filters must not dim this view.
      this.loading.set(false);
      this.refreshing.set(false);
      return;
    }
    if (this.inflight === key) {
      (hit ? this.refreshing : this.loading).set(true); // already on its way
      return;
    }
    this.fetch(key, !!hit || (force && !!this.data()));
  }

  private fetch(key: string, background: boolean): void {
    this.inflight = key;
    (background ? this.refreshing : this.loading).set(true);
    if (!background) this.error.set('');
    const [days, source, process] = key.split('|');
    this.api.dashboard(Number(days), source, process).subscribe({
      next: (d) => {
        const at = Date.now();
        this.cache.delete(key);
        this.cache.set(key, { data: d, at });
        while (this.cache.size > MAX_CACHED) this.cache.delete(this.cache.keys().next().value!);
        if (key === this.key()) {
          // Only the filters still selected reach the screen; an older answer just fills the cache.
          this.data.set(d);
          this.fetchedAt.set(at);
          this.error.set('');
        }
        this.done(key);
      },
      error: (e) => {
        if (key === this.key()) this.error.set(errorText(e));
        this.done(key);
      },
    });
  }

  private done(key: string): void {
    if (this.inflight !== key) return; // a newer request is still running; its own finish ends loading
    this.inflight = '';
    this.loading.set(false);
    this.refreshing.set(false);
  }
}
