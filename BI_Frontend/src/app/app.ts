import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { ApiService } from './core/api.service';
import { ChatStore } from './core/chat.store';
import { McpLog } from './core/mcp-log.service';
import { ThemeService } from './core/theme.service';
import { Health, McpInfo } from './core/models';

const NAV = [
  { path: '/dashboard', label: 'Overview', icon: 'overview' },
  { path: '/submissions', label: 'Submissions', icon: 'inbox' },
  { path: '/chat', label: 'Ask AI', icon: 'spark' },
  { path: '/catalog', label: 'Data catalog', icon: 'db' },
] as const;

/**
 * The application frame: top navigation with a global ask box, and the source panel that says
 * where every number came from - the MCP server, its database, and the tools it just ran.
 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, FormsModule, DatePipe],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  readonly theme = inject(ThemeService);
  readonly chat = inject(ChatStore);
  readonly log = inject(McpLog);

  readonly nav = NAV;
  readonly panelOpen = signal(readPanel());
  readonly health = signal<Health | null>(null);
  readonly healthError = signal(false);
  readonly mcp = signal<McpInfo | null>(null);
  readonly checking = signal(false);
  readonly question = signal('');

  constructor() {
    this.check();
  }

  check(): void {
    this.checking.set(true);
    this.healthError.set(false);
    this.api.health().subscribe({
      next: (h) => {
        this.health.set(h);
        this.checking.set(false);
      },
      error: () => {
        this.healthError.set(true);
        this.checking.set(false);
      },
    });
    this.api.mcp().subscribe({ next: (m) => this.mcp.set(m), error: () => this.mcp.set(null) });
  }

  ask(): void {
    const q = this.question().trim();
    if (!q) return;
    this.chat.ask(q);
    this.question.set('');
    this.router.navigateByUrl('/chat');
  }

  togglePanel(): void {
    this.panelOpen.update((open) => !open);
    try {
      localStorage.setItem('bi.source.open', String(this.panelOpen()));
    } catch {
      /* storage unavailable - preference just isn't remembered */
    }
  }
}

function readPanel(): boolean {
  try {
    const v = localStorage.getItem('bi.source.open');
    if (v !== null) return v === 'true';
  } catch {
    /* fall through to the width default */
  }
  return window.innerWidth >= 1200;
}
