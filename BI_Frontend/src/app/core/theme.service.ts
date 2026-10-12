import { Injectable, signal } from '@angular/core';

export type Theme = 'light' | 'dark';
const KEY = 'bi.theme';

/** Light/dark toggle. Defaults to the OS setting; an explicit choice is stamped on <html data-theme>. */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly theme = signal<Theme>(initial());
  /** Bumped on every change so charts can redraw with the new colors. */
  readonly version = signal(0);

  constructor() {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      if (!stored()) this.apply(e.matches ? 'dark' : 'light', false);
    });
  }

  toggle(): void {
    this.apply(this.theme() === 'dark' ? 'light' : 'dark', true);
  }

  private apply(theme: Theme, remember: boolean): void {
    this.theme.set(theme);
    if (remember) {
      document.documentElement.dataset['theme'] = theme;
      try {
        localStorage.setItem(KEY, theme);
      } catch {
        /* not remembered */
      }
    }
    this.version.update((v) => v + 1);
  }
}

function stored(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    return null;
  }
}

function initial(): Theme {
  const s = stored();
  if (s) {
    document.documentElement.dataset['theme'] = s;
    return s;
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
