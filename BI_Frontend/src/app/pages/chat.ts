import { AfterViewChecked, Component, ElementRef, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { JsonPipe } from '@angular/common';
import { marked } from 'marked';

import { ChatStore } from '../core/chat.store';
import { ChartCard } from '../shared/chart-card';

const SUGGESTIONS = [
  'How many submissions did we receive per day in the last 30 days, by source?',
  'Which processes have the most failed extraction runs?',
  'What is the average confidence score per process?',
  'Show the latest 10 webhook submissions and their run status',
  'How many runs are awaiting approval right now?',
];

@Component({
  selector: 'app-chat',
  imports: [FormsModule, ChartCard, JsonPipe],
  template: `
    <div class="page-head">
      <div>
        <h1>Ask the data</h1>
        <p class="sub">Answers come from the Actuvara database, with charts built from the same queries.</p>
      </div>
      @if (store.messages().length) {
        <button class="ghost" type="button" (click)="store.clear()" [disabled]="store.busy()">New chat</button>
      }
    </div>

    <div class="thread" #thread>
      @if (!store.messages().length) {
        <div class="welcome">
          <p>Try one of these:</p>
          <div class="chips">
            @for (s of suggestions; track s) {
              <button type="button" class="chip" (click)="send(s)">{{ s }}</button>
            }
          </div>
        </div>
      }

      @for (m of store.messages(); track $index) {
        @if (m.role === 'user') {
          <div class="msg user"><div class="bubble">{{ m.content }}</div></div>
        } @else {
          <div class="msg assistant" [class.error]="m.error">
            <div class="avatar" aria-hidden="true">AI</div>
            <div class="body">
              <div class="md" [innerHTML]="md(m.content)"></div>
              @if (m.charts?.length) {
                <div class="charts" [class.single]="m.charts!.length === 1">
                  @for (c of m.charts!; track $index) {
                    <app-chart-card [spec]="c" [class.wide]="c.type === 'table' || c.type === 'line'" />
                  }
                </div>
              }
              @if (m.steps?.length) {
                <details class="steps">
                  <summary>{{ m.steps!.length }} database {{ m.steps!.length === 1 ? 'query' : 'queries' }}</summary>
                  <ol>
                    @for (s of m.steps!; track $index) {
                      <li [class.failed]="!s.ok">
                        <code>{{ s.tool }}</code>
                        <pre>{{ s.input | json }}</pre>
                      </li>
                    }
                  </ol>
                </details>
              }
            </div>
          </div>
        }
      }

      @if (store.busy()) {
        <div class="msg assistant">
          <div class="avatar" aria-hidden="true">AI</div>
          <div class="body thinking"><span></span><span></span><span></span> Querying the database…</div>
        </div>
      }
    </div>

    <form class="composer" (ngSubmit)="send(draft())">
      <textarea
        name="q"
        rows="1"
        placeholder="Ask a question about your data…"
        [ngModel]="draft()"
        (ngModelChange)="draft.set($event)"
        (keydown.enter)="onEnter($event)"
        [disabled]="store.busy()"
        aria-label="Question"
      ></textarea>
      <button type="submit" class="primary" [disabled]="store.busy() || !draft().trim()">Send</button>
    </form>
  `,
  styleUrl: './chat.scss',
})
export class ChatPage implements AfterViewChecked {
  readonly store = inject(ChatStore);
  readonly suggestions = SUGGESTIONS;
  readonly draft = signal('');
  readonly thread = viewChild<ElementRef<HTMLDivElement>>('thread');
  private lastCount = -1;
  private readonly mdCache = new Map<string, string>();

  send(text: string): void {
    if (!text.trim()) return;
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

  /** Markdown -> HTML. Angular's [innerHTML] sanitizer strips scripts and handlers. */
  md(text: string): string {
    let html = this.mdCache.get(text);
    if (html === undefined) {
      html = marked.parse(text, { async: false, gfm: true, breaks: true }) as string;
      this.mdCache.set(text, html);
    }
    return html;
  }

  ngAfterViewChecked(): void {
    const count = this.store.messages().length + (this.store.busy() ? 1 : 0);
    if (count !== this.lastCount) {
      this.lastCount = count;
      const el = this.thread()?.nativeElement;
      el?.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  }
}
