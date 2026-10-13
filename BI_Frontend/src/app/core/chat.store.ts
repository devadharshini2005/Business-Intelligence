import { Injectable, computed, inject, signal } from '@angular/core';

import { ApiService, errorText } from './api.service';
import { McpLog } from './mcp-log.service';
import { ChatMessage, Conversation } from './models';

const STORAGE_KEY = 'bi.chats.v2';
const LEGACY_KEY = 'bi.chat.v1';
const MAX_CONVERSATIONS = 60;
const MAX_MESSAGES = 60;

/**
 * Every conversation with the assistant, like a chat app's history: "New chat" starts a fresh one and
 * the previous one stays in the list. Saved in this browser only (localStorage).
 *
 * Answers stream in - steps and charts appear as they happen - and always land in the conversation
 * they were asked in, even if another conversation is opened meanwhile.
 */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly api = inject(ApiService);
  private readonly log = inject(McpLog);
  private abort?: AbortController;

  readonly conversations = signal<Conversation[]>(load());
  /** The open conversation; null = a new chat that has no messages yet. */
  readonly activeId = signal<string | null>(null);
  /** The conversation an answer is being written for, if any. */
  readonly busyId = signal<string | null>(null);
  readonly busy = computed(() => this.busyId() !== null);

  /** Newest activity first. */
  readonly history = computed(() => [...this.conversations()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
  readonly active = computed(() => this.conversations().find((c) => c.id === this.activeId()) ?? null);
  readonly messages = computed(() => this.active()?.messages ?? []);

  /** Ask in the open conversation, or start one. `fresh` always starts a new conversation. */
  ask(question: string, opts: { fresh?: boolean } = {}): void {
    const q = question.trim();
    if (!q || this.busy()) return;
    const now = new Date().toISOString();

    let id = opts.fresh ? null : this.activeId();
    if (!id || !this.find(id)) {
      id = newId();
      this.conversations.update((list) => [{ id: id!, title: titleFrom(q), createdAt: now, updatedAt: now, messages: [] }, ...list]);
      this.activeId.set(id);
    }

    const history: ChatMessage[] = [...this.find(id)!.messages, { role: 'user', content: q, at: now }];
    this.patch(id, () => [...history, { role: 'assistant', content: '', steps: [], charts: [], pending: true, at: now }]);
    this.busyId.set(id);
    this.abort = new AbortController();
    const convId = id;

    this.api
      .chatStream(
        history,
        {
          step: (s) => {
            this.log.record({ tool: s.tool, at: new Date(), ok: s.ok, via: 'chat' });
            this.patchLast(convId, (m) => ({ ...m, steps: [...(m.steps ?? []), s] }));
          },
          chart: (c) => this.patchLast(convId, (m) => ({ ...m, charts: [...(m.charts ?? []), c] })),
        },
        this.abort.signal,
      )
      .then((res) =>
        this.patchLast(convId, () => ({
          role: 'assistant',
          content: res.answer,
          charts: res.charts,
          steps: res.steps,
          followUps: res.follow_ups ?? [],
          at: new Date().toISOString(),
        })),
      )
      .catch((err) => this.patchLast(convId, (m) => ({ ...m, content: errorText(err), pending: false, error: true })))
      .finally(() => {
        this.busyId.set(null);
        this.abort = undefined;
        this.persist();
      });
  }

  /** Re-asks the question before a failed answer, in the open conversation. */
  retry(): void {
    const id = this.activeId();
    const conv = id ? this.find(id) : null;
    const lastUser = conv ? [...conv.messages].reverse().find((m) => m.role === 'user') : null;
    if (!conv || !lastUser || this.busy()) return;
    const cut = conv.messages.lastIndexOf(lastUser);
    this.patch(conv.id, (msgs) => msgs.slice(0, cut));
    this.ask(lastUser.content);
  }

  stop(): void {
    this.abort?.abort();
  }

  /** Leave the open conversation in the history and show an empty chat. */
  newChat(): void {
    this.activeId.set(null);
  }

  /** Open a conversation from the history; false if it doesn't exist. */
  open(id: string): boolean {
    if (!this.find(id)) return false;
    this.activeId.set(id);
    return true;
  }

  rename(id: string, title: string): void {
    const t = title.trim().slice(0, 120);
    if (!t) return;
    this.conversations.update((list) => list.map((c) => (c.id === id ? { ...c, title: t } : c)));
    this.persist();
  }

  remove(id: string): void {
    if (this.busyId() === id) this.stop();
    this.conversations.update((list) => list.filter((c) => c.id !== id));
    if (this.activeId() === id) this.activeId.set(null);
    this.persist();
  }

  clearAll(): void {
    this.stop();
    this.conversations.set([]);
    this.activeId.set(null);
    this.persist();
  }

  private find(id: string): Conversation | undefined {
    return this.conversations().find((c) => c.id === id);
  }

  private patch(id: string, fn: (messages: ChatMessage[]) => ChatMessage[]): void {
    const now = new Date().toISOString();
    this.conversations.update((list) =>
      list.map((c) => (c.id === id ? { ...c, messages: fn(c.messages), updatedAt: now } : c)),
    );
  }

  private patchLast(id: string, fn: (m: ChatMessage) => ChatMessage): void {
    this.patch(id, (msgs) => (msgs.length ? [...msgs.slice(0, -1), fn(msgs[msgs.length - 1])] : msgs));
  }

  /**
   * Saves the history. If the browser's storage is full, the oldest conversations lose their charts
   * first, then the oldest conversations are dropped, until it fits.
   */
  private persist(): void {
    let list = this.history()
      .filter((c) => c.messages.length)
      .slice(0, MAX_CONVERSATIONS)
      .map((c) => ({ ...c, messages: c.messages.filter((m) => !m.pending).slice(-MAX_MESSAGES) }));
    for (let attempt = 0; attempt < 40; attempt++) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
        return;
      } catch {
        const heavy = [...list].reverse().find((c) => c.messages.some((m) => m.charts?.length));
        if (heavy) {
          list = list.map((c) => (c === heavy ? { ...c, messages: c.messages.map(({ charts, ...m }) => m) } : c));
        } else if (list.length > 1) {
          list = list.slice(0, -1);
        } else {
          return; // storage blocked - the history just isn't remembered
        }
      }
    }
  }
}

function load(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const list = JSON.parse(raw) as Conversation[];
      return Array.isArray(list)
        ? list.map((c) => ({ ...c, messages: (c.messages ?? []).filter((m) => !m.pending) }))
        : [];
    }
    // The single conversation saved by the previous version becomes the first history entry.
    const legacy = JSON.parse(localStorage.getItem(LEGACY_KEY) ?? '[]') as ChatMessage[];
    const msgs = Array.isArray(legacy) ? legacy.filter((m) => !m.pending) : [];
    const first = msgs.find((m) => m.role === 'user');
    if (!first) return [];
    const at = msgs[msgs.length - 1].at ?? new Date().toISOString();
    const migrated = [{ id: newId(), title: titleFrom(first.content), createdAt: first.at ?? at, updatedAt: at, messages: msgs }];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated));
    localStorage.removeItem(LEGACY_KEY);
    return migrated;
  } catch {
    return [];
  }
}

/** A conversation is named after its first question, like a chat app does. */
function titleFrom(question: string): string {
  const t = question.replace(/\s+/g, ' ').trim();
  return t.length > 60 ? t.slice(0, 57).trimEnd() + '…' : t;
}

function newId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}
