import { Injectable, inject, signal } from '@angular/core';

import { ApiService, errorText } from './api.service';
import { ChatMessage } from './models';

/** Keeps the conversation alive while the user switches between Dashboard and Chat. */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly api = inject(ApiService);

  readonly messages = signal<ChatMessage[]>([]);
  readonly busy = signal(false);

  ask(question: string): void {
    const q = question.trim();
    if (!q || this.busy()) return;
    const history = [...this.messages(), { role: 'user', content: q } as ChatMessage];
    this.messages.set(history);
    this.busy.set(true);
    this.api.chat(history).subscribe({
      next: (res) => {
        this.messages.update((m) => [
          ...m,
          { role: 'assistant', content: res.answer, charts: res.charts, steps: res.steps },
        ]);
        this.busy.set(false);
      },
      error: (err) => {
        this.messages.update((m) => [...m, { role: 'assistant', content: errorText(err), error: true }]);
        this.busy.set(false);
      },
    });
  }

  clear(): void {
    if (!this.busy()) this.messages.set([]);
  }
}
