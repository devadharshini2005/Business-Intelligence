import { Injectable, inject, signal } from '@angular/core';

import { ApiService, errorText } from './api.service';
import { McpLog } from './mcp-log.service';
import { ChatMessage } from './models';

const STORAGE_KEY = 'bi.chat.v1';
const MAX_SAVED = 40;

/**
 * The conversation: survives switching between Dashboard and Chat, and page reloads
 * (saved in this browser only). Answers stream in - steps and charts appear as they happen.
 */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly api = inject(ApiService);
  private readonly log = inject(McpLog);
  private abort?: AbortController;

  readonly messages = signal<ChatMessage[]>(load());
  readonly busy = signal(false);

  ask(question: string): void {
    const q = question.trim();
    if (!q || this.busy()) return;
    const now = new Date().toISOString();
    const history: ChatMessage[] = [...this.messages(), { role: 'user', content: q, at: now }];
    this.messages.set([...history, { role: 'assistant', content: '', steps: [], charts: [], pending: true, at: now }]);
    this.busy.set(true);
    this.abort = new AbortController();

    this.api
      .chatStream(
        history,
        {
          step: (s) => {
            this.log.record({ tool: s.tool, at: new Date(), ok: s.ok, via: 'chat' });
            this.patchLast((m) => ({ ...m, steps: [...(m.steps ?? []), s] }));
          },
          chart: (c) => this.patchLast((m) => ({ ...m, charts: [...(m.charts ?? []), c] })),
        },
        this.abort.signal,
      )
      .then((res) =>
        this.patchLast(() => ({
          role: 'assistant',
          content: res.answer,
          charts: res.charts,
          steps: res.steps,
          followUps: res.follow_ups ?? [],
          at: new Date().toISOString(),
        })),
      )
      .catch((err) =>
        this.patchLast((m) => ({ ...m, content: errorText(err), pending: false, error: true })),
      )
      .finally(() => {
        this.busy.set(false);
        this.abort = undefined;
        save(this.messages());
      });
  }

  /** Re-asks the question before a failed answer. */
  retry(): void {
    const msgs = this.messages();
    const lastUser = [...msgs].reverse().find((m) => m.role === 'user');
    if (!lastUser || this.busy()) return;
    const cut = msgs.lastIndexOf(lastUser);
    this.messages.set(msgs.slice(0, cut));
    this.ask(lastUser.content);
  }

  stop(): void {
    this.abort?.abort();
  }

  clear(): void {
    if (this.busy()) return;
    this.messages.set([]);
    save([]);
  }

  private patchLast(fn: (m: ChatMessage) => ChatMessage): void {
    this.messages.update((list) => [...list.slice(0, -1), fn(list[list.length - 1])]);
  }
}

function load(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const list = raw ? (JSON.parse(raw) as ChatMessage[]) : [];
    return Array.isArray(list) ? list.filter((m) => !m.pending) : [];
  } catch {
    return [];
  }
}

function save(list: ChatMessage[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(-MAX_SAVED)));
  } catch {
    /* storage full or blocked - the conversation just isn't remembered */
  }
}
