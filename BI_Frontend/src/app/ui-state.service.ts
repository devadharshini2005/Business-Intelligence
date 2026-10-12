import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { ApiService } from './api.service';
import { Health } from './models';

/** App-wide UI state: DB health, the open submission drawer, questions handed to the assistant. */
@Injectable({ providedIn: 'root' })
export class UiStateService {
  private api = inject(ApiService);
  private router = inject(Router);

  readonly health = signal<Health | null>(null);
  readonly openSubmissionId = signal<string | null>(null);
  /** A question from the dashboard waiting to be sent by the assistant page. */
  readonly pendingQuestion = signal<string | null>(null);

  constructor() {
    this.api.health().subscribe({
      next: (h) => this.health.set(h),
      error: (e: Error) => this.health.set({ database: false, database_error: e.message }),
    });
  }

  ask(question: string) {
    this.openSubmissionId.set(null);
    this.pendingQuestion.set(question);
    this.router.navigate(['/assistant']);
  }
}
