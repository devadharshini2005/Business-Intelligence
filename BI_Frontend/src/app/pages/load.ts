import { WritableSignal, signal } from '@angular/core';
import { Observable } from 'rxjs';

/** Per-card loading state, so one failing query doesn't blank the whole dashboard. */
export interface Loadable<T> { loading: boolean; error?: string; data?: T; }

export const loadable = <T>() => signal<Loadable<T>>({ loading: true });

export function load<T>(source: Observable<T>, target: WritableSignal<Loadable<T>>) {
  target.update((s) => ({ ...s, loading: true, error: undefined }));
  return source.subscribe({
    next: (data) => target.set({ loading: false, data }),
    error: (e: Error) => target.set({ loading: false, error: e.message }),
  });
}
