import { AfterViewChecked, Component, ElementRef, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { DatePipe, JsonPipe } from '@angular/common';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { marked } from 'marked';

import { ChatStore } from '../core/chat.store';
import { downloadAnswerWorkbook } from '../core/excel';
import { Conversation, ToolStep } from '../core/models';
import { AnswerAnalytics } from '../shared/answer-analytics';

const SUGGESTIONS: { group: string; questions: string[] }[] = [
  {
    group: 'Volumes & trends',
    questions: [
      'How many submissions did we receive per day in the last 30 days, by source?',
      'How many submissions came by email vs webhook vs manual upload?',
    ],
  },
  {
    group: 'Quality & failures',
    questions: [
      'Which processes have the most failed extraction runs?',
      'What is the average confidence score per process?',
    ],
  },
  {
    group: 'Work in progress',
    questions: [
      'How many runs are awaiting approval or pending review right now?',
      'Show the latest 10 webhook submissions and their run status',
    ],
  },
];

/** Plain-language description of a database step, shown while the answer is being built. */
function describe(s: ToolStep): string {
  const i = s.input as Record<string, any>;
  const coll = i['collection'] ? ` in ${i['collection']}` : '';
  switch (s.tool) {
    case 'list_collections': return 'Looked up the available collections';
    case 'infer_collection_schema': return `Read the fields${coll}`;
    case 'get_distinct_values': return `Checked the values of "${i['field_path']}"${coll}`;
    case 'count_documents': return `Counted documents${coll}`;
    case 'run_find': return `Read records${coll}`;
    case 'run_aggregate': return `Ran an aggregation${coll}`;
    case 'get_inferred_relationships': return 'Checked how collections are linked';
    case 'idp_find_submissions': return 'Searched submissions';
    case 'idp_get_submission': return `Opened submission ${i['submission_id'] ?? ''}`;
    case 'idp_get_run_details': return `Opened run ${i['run_id'] ?? ''}`;
    case 'idp_process_performance': return 'Checked completion and stuck steps for each process';
    case 'build_chart': return `Built the chart "${i['title'] ?? ''}"`;
    default: return s.tool;
  }
}

@Component({
  selector: 'app-chat',
  imports: [FormsModule, AnswerAnalytics, JsonPipe, DatePipe, RouterLink],
  templateUrl: './chat.html',
  styleUrl: './chat.scss',
})
export class ChatPage implements AfterViewChecked {
  readonly store = inject(ChatStore);
  readonly suggestions = SUGGESTIONS;
  readonly draft = signal('');
  readonly copied = signal<number | null>(null);
  readonly thread = viewChild<ElementRef<HTMLDivElement>>('thread');
  readonly describe = describe;
  private lastSize = '';
  private readonly mdCache = new Map<string, string>();
  private readonly router = inject(Router);

  /** The conversation id in the address bar (/chat/:id), so back/forward and bookmarks work. */
  private readonly routeId = toSignal(inject(ActivatedRoute).paramMap.pipe(map((p) => p.get('id'))));

  // --- history sidebar ---------------------------------------------------------------------------
  readonly sidebarOpen = signal(readSidebar());
  readonly search = signal('');
  readonly editingId = signal<string | null>(null);

  /** History grouped like a chat app: Today, Yesterday, Previous 7 days, Previous 30 days, then by month. */
  readonly groups = computed(() => {
    const q = this.search().trim().toLowerCase();
    const list = this.store
      .history()
      .filter((c) => !q || c.title.toLowerCase().includes(q) ||
        c.messages.some((m) => m.role === 'user' && m.content.toLowerCase().includes(q)));
    const groups: { label: string; items: Conversation[] }[] = [];
    for (const c of list) {
      const label = groupLabel(c.updatedAt);
      const g = groups.find((x) => x.label === label);
      if (g) g.items.push(c);
      else groups.push({ label, items: [c] });
    }
    return groups;
  });

  constructor() {
    // Address bar -> open conversation. A bare /chat resumes the conversation already open.
    effect(() => {
      const id = this.routeId();
      untracked(() => {
        if (id) {
          if (!this.store.open(id)) this.go(null);
        } else if (this.store.activeId()) {
          this.go(this.store.activeId());
        }
      });
    });
  }

  send(text: string): void {
    if (!text.trim() || this.store.busy()) return;
    this.store.ask(text);
    this.draft.set('');
    // A first question creates the conversation: give it its own address.
    if (this.store.activeId() !== this.routeId()) this.go(this.store.activeId());
  }

  newChat(): void {
    this.store.newChat();
    this.draft.set('');
    this.router.navigate(['/chat']);
    if (window.innerWidth < 900) this.sidebarOpen.set(false);
  }

  opened(): void {
    if (window.innerWidth < 900) this.sidebarOpen.set(false);
  }

  toggleSidebar(): void {
    this.sidebarOpen.update((v) => !v);
    try {
      localStorage.setItem('bi.chat.sidebar', String(this.sidebarOpen()));
    } catch {
      /* not remembered */
    }
  }

  startRename(c: Conversation, e: Event): void {
    e.preventDefault();
    e.stopPropagation();
    this.editingId.set(c.id);
    setTimeout(() => document.querySelector<HTMLInputElement>('.history .rename')?.select());
  }

  finishRename(c: Conversation, value: string): void {
    if (this.editingId() !== c.id) return;
    this.store.rename(c.id, value);
    this.editingId.set(null);
  }

  remove(c: Conversation, e: Event): void {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`Delete "${c.title}"? This can't be undone.`)) return;
    const wasOpen = this.store.activeId() === c.id;
    this.store.remove(c.id);
    if (wasOpen) this.go(null);
  }

  clearHistory(): void {
    if (!confirm("Delete every conversation in this browser? This can't be undone.")) return;
    this.store.clearAll();
    this.go(null);
  }

  private go(id: string | null): void {
    this.router.navigate(id ? ['/chat', id] : ['/chat'], { replaceUrl: true });
  }

  onEnter(e: Event): void {
    const k = e as KeyboardEvent;
    if (!k.shiftKey) {
      k.preventDefault();
      this.send(this.draft());
    }
  }

  /** Markdown -> HTML. Angular's [innerHTML] sanitizer strips scripts and event handlers. */
  md(text: string): string {
    let html = this.mdCache.get(text);
    if (html === undefined) {
      html = marked.parse(text, { async: false, gfm: true, breaks: true }) as string;
      this.mdCache.set(text, html);
    }
    return html;
  }

  readonly exporting = signal<number | null>(null);

  /** The answer at index i as an Excel workbook: question + answer, a sheet per chart/table, the queries. */
  async downloadExcel(i: number): Promise<void> {
    const msgs = this.store.messages();
    const answer = msgs[i];
    const question = [...msgs.slice(0, i)].reverse().find((m) => m.role === 'user')?.content ?? 'Question';
    this.exporting.set(i);
    try {
      await downloadAnswerWorkbook(question, answer);
    } catch (e) {
      alert(`Could not create the Excel file: ${e instanceof Error ? e.message : e}`);
    } finally {
      this.exporting.set(null);
    }
  }

  copy(text: string, i: number): void {
    navigator.clipboard?.writeText(text).then(() => {
      this.copied.set(i);
      setTimeout(() => this.copied.set(null), 1500);
    });
  }

  /** Keeps the newest content in view while an answer streams in. */
  ngAfterViewChecked(): void {
    const msgs = this.store.messages();
    const last = msgs[msgs.length - 1];
    const size = `${msgs.length}:${last?.steps?.length ?? 0}:${last?.charts?.length ?? 0}:${last?.pending}`;
    if (size !== this.lastSize) {
      this.lastSize = size;
      const el = this.thread()?.nativeElement;
      el?.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  }
}

function readSidebar(): boolean {
  try {
    const v = localStorage.getItem('bi.chat.sidebar');
    if (v !== null) return v === 'true';
  } catch {
    /* fall through */
  }
  return window.innerWidth >= 900;
}

function groupLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.floor((today.getTime() - new Date(d).setHours(0, 0, 0, 0)) / 86_400_000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return 'Previous 7 days';
  if (days < 30) return 'Previous 30 days';
  return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
}
