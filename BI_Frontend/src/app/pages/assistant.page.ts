import {
  ChangeDetectionStrategy, Component, ElementRef, OnDestroy, computed, effect, inject, signal, untracked, viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../api.service';
import { full } from '../format';
import { ChartSpec, ChatEvent, ChatTurn } from '../models';
import { ChatChartComponent } from '../shared/chat-chart.component';
import { IconComponent } from '../shared/icon.component';
import { MarkdownPipe } from '../shared/markdown.pipe';
import { printReport } from '../shared/report-pdf';
import { UiStateService } from '../ui-state.service';

interface Step { id: string; name: string; input: Record<string, unknown>; done: boolean; ok?: boolean; summary?: string; }
/** One dot in the timeline: a stage the agent went through, or a tool call (index into Message.steps). */
type FlowItem = { kind: 'status'; text: string; done: boolean } | { kind: 'tool'; step: number };
interface Message {
  role: 'user' | 'assistant'; text: string; steps?: Step[]; charts?: ChartSpec[]; error?: boolean; pending?: boolean;
  /** Everything that happened while answering, in order (older saved chats only have steps). */
  flow?: FlowItem[];
}

/** Plain-language names for the MCP tools, shown in the step timeline. */
const TOOL_LABELS: Record<string, string> = {
  ping_db: 'Check the database connection', server_info: 'Read server info', list_databases: 'List databases',
  list_collections: 'List collections', find_collections_like: 'Find collections', collection_exists: 'Check a collection',
  get_collection_details: 'Read collection details', list_indexes: 'List indexes',
  infer_collection_schema: 'Read the collection schema', find_fields_like: 'Find fields', field_exists: 'Check a field',
  get_inferred_relationships: 'Work out how collections link', count_documents: 'Count documents',
  get_distinct_values: 'List distinct values', run_find: 'Query documents', run_aggregate: 'Run an aggregation',
  idp_find_submissions: 'Search submissions', idp_get_submission: 'Open a submission', idp_get_run_details: 'Open run details',
  get_database_overview: 'Survey the database', chart_metric: 'Build a dashboard chart', create_chart: 'Build a chart',
  show_stat_cards: 'Show stat cards', dashboard_kpis: 'Read the dashboard KPIs',
};
interface Conversation { id: string; title: string; updated: number; messages: Message[]; }

const STORE_KEY = 'actuvara-bi.conversations';

function loadStore(): Conversation[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) || '[]') as Conversation[];
    // Anything still "pending" was interrupted by a reload.
    return raw.map((c) => ({ ...c, messages: c.messages.map((m) => ({ ...m, pending: false })) }));
  } catch {
    return [];
  }
}

@Component({
  selector: 'bi-assistant',
  imports: [FormsModule, NgTemplateOutlet, ChatChartComponent, IconComponent, MarkdownPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './assistant.page.html',
  host: { class: 'assistant-host' },
})
export class AssistantPage implements OnDestroy {
  private api = inject(ApiService);
  ui = inject(UiStateService);
  private thread = viewChild<ElementRef<HTMLElement>>('thread');

  conversations = signal<Conversation[]>(loadStore());
  activeId = signal<string | null>(null);
  busy = signal(false);
  editingId = signal<string | null>(null);
  draft = '';
  private abort: AbortController | null = null;

  active = computed(() => this.conversations().find((c) => c.id === this.activeId()) ?? null);

  groups = computed(() => {
    const day = 864e5;
    const today = new Date().setHours(0, 0, 0, 0);
    const out: { label: string; items: Conversation[] }[] = [
      { label: 'Today', items: [] }, { label: 'Yesterday', items: [] }, { label: 'Previous 7 days', items: [] },
      { label: 'Older', items: [] },
    ];
    for (const c of [...this.conversations()].sort((a, b) => b.updated - a.updated)) {
      const i = c.updated >= today ? 0 : c.updated >= today - day ? 1 : c.updated >= today - 7 * day ? 2 : 3;
      out[i].items.push(c);
    }
    return out.filter((g) => g.items.length);
  });

  greeting = (() => {
    const h = new Date().getHours();
    return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  })();

  cards = [
    { icon: 'pie', title: 'Pipeline health', text: 'How many submissions, files and runs came in this week, and how many failed?' },
    { icon: 'wrench', title: 'Investigate failures', text: 'Which workflow nodes failed most in the last 7 days, and why?' },
    { icon: 'database', title: 'Explore the data model', text: 'Which collections hold submissions and runs, and how are they linked?' },
  ];
  /** Suggested questions, always visible next to the input. */
  promptGroups = [
    { title: 'Charts', icon: 'pie', prompts: [
      'Pie chart of extraction runs by status for the last 30 days',
      'Bar chart of runs by process this month',
      'Pie chart of submissions by source for the last 90 days',
      'Horizontal bar chart of the workflow nodes that failed most in the last 90 days',
      'Line chart of runs per day for the last 30 days',
    ] },
    { title: 'Submissions', icon: 'inbox', prompts: [
      'Show the latest webhook submissions',
      'Which manual uploads failed this week?',
      'How many submissions came in during the last 7 days, by source?',
    ] },
    { title: 'Runs & processes', icon: 'workflow', prompts: [
      'Which process has the lowest success rate this month?',
      'How many extraction runs failed this month?',
      'List the distinct statuses of extraction_results with counts',
    ] },
    { title: 'Data model', icon: 'database', prompts: [
      'How many collections are there in the database?',
      'Which collections hold submissions and runs, and how are they linked?',
    ] },
  ];
  allPrompts = this.promptGroups.flatMap((g) => g.prompts);

  constructor() {
    effect(() => {
      try { localStorage.setItem(STORE_KEY, JSON.stringify(this.conversations().slice(-50))); } catch { /* storage off */ }
    });
    // A question handed over from the dashboard starts a new chat.
    effect(() => {
      const q = this.ui.pendingQuestion();
      if (!q) return;
      untracked(() => {
        this.ui.pendingQuestion.set(null);
        this.newChat();
        this.send(q);
      });
    });
  }

  ngOnDestroy() { this.abort?.abort(); }

  newChat() {
    if (this.busy()) this.stop();
    this.activeId.set(null);
    this.draft = '';
  }

  open(id: string) {
    if (this.busy()) this.stop();
    this.activeId.set(id);
    this.scrollDown();
  }

  remove(id: string, ev: Event) {
    ev.stopPropagation();
    this.conversations.update((cs) => cs.filter((c) => c.id !== id));
    if (this.activeId() === id) this.activeId.set(null);
  }

  startEdit(id: string, ev: Event) {
    ev.stopPropagation();
    this.editingId.set(id);
    // Focus the input once it has rendered.
    setTimeout(() => (document.querySelector('.history-rename') as HTMLInputElement | null)?.select());
  }

  /** Called on blur (Enter blurs too). Escape clears editingId first, so the blur that follows is ignored. */
  saveTitle(id: string, value: string) {
    if (this.editingId() !== id) return;
    this.editingId.set(null);
    const title = value.trim().slice(0, 80);
    if (title) this.patch(id, (c) => ({ ...c, title }));
  }

  stop() {
    this.abort?.abort();
  }

  onKey(ev: KeyboardEvent) {
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      this.send();
    }
  }

  private patch(id: string, fn: (c: Conversation) => Conversation) {
    this.conversations.update((cs) => cs.map((c) => (c.id === id ? fn(c) : c)));
  }

  private patchLast(id: string, fn: (m: Message) => Message) {
    this.patch(id, (c) => ({ ...c, updated: Date.now(), messages: [...c.messages.slice(0, -1), fn(c.messages[c.messages.length - 1])] }));
  }

  async send(text?: string) {
    const question = (text ?? this.draft).trim();
    if (!question || this.busy()) return;
    this.draft = '';

    let conv = this.active();
    if (!conv) {
      conv = { id: crypto.randomUUID(), title: question.slice(0, 80), updated: Date.now(), messages: [] };
      this.conversations.update((cs) => [...cs, conv!]);
      this.activeId.set(conv.id);
    }
    const id = conv.id;
    // The API is stateless: send the conversation so far (text only) plus the new question.
    const history: ChatTurn[] = [
      ...conv.messages
        .filter((m) => m.text && !m.error && !m.pending)
        .map((m) => ({ role: m.role, content: m.text.slice(0, 20000) })),
      { role: 'user' as const, content: question.slice(0, 20000) },
    ].slice(-40);
    this.patch(id, (c) => ({
      ...c, updated: Date.now(),
      messages: [...c.messages, { role: 'user', text: question }, { role: 'assistant', text: '', steps: [], pending: true }],
    }));
    this.scrollDown();

    this.busy.set(true);
    this.abort = new AbortController();
    try {
      const reply = await this.api.chatStream(history, (ev) => this.onEvent(id, ev), this.abort.signal);
      this.patchLast(id, (m) => ({
        ...m,
        text: reply.answer,
        charts: reply.charts,
        // Keep the summaries that arrived while streaming.
        steps: reply.steps.map((st, i) => ({ id: String(i), name: st.tool, input: st.input, done: true, ok: st.ok,
                                             summary: m.steps?.[i]?.summary })),
      }));
    } catch (err) {
      const aborted = (err as Error).name === 'AbortError';
      const msg = (err as Error).message;
      this.patchLast(id, (m) => ({
        ...m, error: !aborted,
        text: aborted ? '_Stopped._'
          : msg && !/fetch/i.test(msg) ? msg : 'Could not reach the BI API server. Is `python api_server.py` running?',
      }));
    } finally {
      this.patchLast(id, (m) => ({
        ...m, pending: false, flow: m.flow && this.stagesDone(m.flow),
        text: m.text || (m.charts?.length ? '' : '_(no answer)_'),
      }));
      this.busy.set(false);
      this.abort = null;
      this.scrollDown();
    }
  }

  /** Live progress from the stream: each stage and tool call becomes a dot; a new one ends the stage before it. */
  private onEvent(id: string, ev: ChatEvent) {
    this.patchLast(id, (m) => {
      if (ev.type === 'status') {
        return { ...m, flow: [...this.stagesDone(m.flow ?? []), { kind: 'status', text: ev.text, done: false }] };
      }
      const steps = [...(m.steps ?? [])];
      if (ev.state === 'running') {
        steps[ev.id] = { id: String(ev.id), name: ev.tool, input: ev.input, done: false };
        return { ...m, steps, flow: [...this.stagesDone(m.flow ?? []), { kind: 'tool', step: ev.id }] };
      }
      if (steps[ev.id]) steps[ev.id] = { ...steps[ev.id], done: true, ok: ev.ok, summary: ev.summary };
      return { ...m, steps };
    });
    this.scrollDown();
  }

  private stagesDone(flow: FlowItem[]): FlowItem[] {
    return flow.map((f) => (f.kind === 'status' && !f.done ? { ...f, done: true } : f));
  }

  /** Timeline items for a message; chats saved before stages were recorded only have their tool calls. */
  flowOf(m: Message): FlowItem[] {
    return m.flow ?? (m.steps ?? []).map((_, i) => ({ kind: 'tool' as const, step: i }));
  }

  /** Save one answer as a PDF report (print dialog -> Save as PDF). */
  downloadPdf(ev: Event) {
    const body = (ev.currentTarget as HTMLElement).closest<HTMLElement>('.bot-body');
    if (body) printReport({ content: body });
  }

  full = full;

  toolLabel(name: string) { return TOOL_LABELS[name] ?? name.replace(/_/g, ' '); }

  private scrollDown() {
    setTimeout(() => {
      const el = this.thread()?.nativeElement;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  stepLabel(s: Step) {
    const args = Object.entries(s.input || {})
      .filter(([, v]) => v !== '' && v != null)
      .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
      .join(', ');
    return args.length > 140 ? args.slice(0, 140) + '…' : args;
  }
}
