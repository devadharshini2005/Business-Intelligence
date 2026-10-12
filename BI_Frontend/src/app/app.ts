import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { ApiService } from './core/api.service';
import { Health } from './core/models';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly api = inject(ApiService);
  readonly collapsed = signal(readCollapsed());
  readonly health = signal<Health | null>(null);
  readonly healthError = signal(false);

  constructor() {
    this.api.health().subscribe({
      next: (h) => this.health.set(h),
      error: () => this.healthError.set(true),
    });
  }

  toggleSidebar(): void {
    this.collapsed.update((c) => !c);
    try {
      localStorage.setItem('bi.sidebar.collapsed', String(this.collapsed()));
    } catch {
      /* storage unavailable - preference just isn't remembered */
    }
  }
}

function readCollapsed(): boolean {
  try {
    return localStorage.getItem('bi.sidebar.collapsed') === 'true';
  } catch {
    return false;
  }
}
