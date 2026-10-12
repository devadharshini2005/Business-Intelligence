import { AfterViewChecked, Component, ElementRef, inject, signal, viewChild } from '@angular/core';
import { DatePipe, JsonPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { marked } from 'marked';

import { ChatStore } from '../core/chat.store';
import { ToolStep } from '../core/models';
import { ChartCard } from '../shared/chart-card';

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
    case 'create_chart': return `Built the chart "${i['title'] ?? ''}"`;
    default: return s.tool;
  }
}

@Component({
  selector: 'app-chat',
  imports: [FormsModule, ChartCard, JsonPipe, DatePipe],
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

  send(text: string): void {
    if (!text.trim() || this.store.busy()) return;
    this.store.ask(text);
    this.draft.set('');
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
