import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { IconComponent } from './shared/icon.component';
import { SubmissionDrawerComponent } from './shared/submission-drawer.component';
import { UiStateService } from './ui-state.service';

interface NavItem { path: string; label: string; icon: string; badge?: string; title: string; hint: string; }

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, IconComponent, SubmissionDrawerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="app" [class.collapsed]="collapsed()">
      <aside class="sidebar">
        <div class="side-brand">
          <a class="brand" routerLink="/overview">
            <img class="brand-mark" src="logo.png" alt="" />
            <span class="brand-name">Actuvara</span>
          </a>
          <button type="button" class="icon-btn sq" (click)="collapsed.set(!collapsed())"
                  [attr.aria-label]="collapsed() ? 'Expand sidebar' : 'Collapse sidebar'">
            <bi-icon [name]="collapsed() ? 'panel-right' : 'panel-left'" />
          </button>
        </div>
        @for (sec of sections; track sec.title) {
          <nav class="side-section" [attr.aria-label]="sec.title">
            <div class="side-title">{{ sec.title }}</div>
            @for (n of sec.items; track n.path) {
              <a class="side-link" [routerLink]="n.path" routerLinkActive="active" [title]="n.label">
                <bi-icon [name]="n.icon" [size]="18" [stroke]="1.8" />
                <span class="side-label">{{ n.label }}</span>
                @if (n.badge) { <span class="side-badge">{{ n.badge }}</span> }
              </a>
            }
          </nav>
        }
        @let h = ui.health();
        <div class="side-db">
          <span class="side-db-icon"><bi-icon name="database" [size]="18" /></span>
          <span class="side-db-text">
            <span class="muted small">Database</span>
            <b>{{ h == null ? 'Connecting…' : h.database ? (h.database_name || 'Connected') : 'Offline' }}</b>
          </span>
          <span class="dot" [class.ok]="h?.database" [class.bad]="h && !h.database" [title]="h?.database_error || 'connected'"></span>
        </div>
      </aside>

      <div class="workspace">
        <header class="topbar">
          @if (page(); as p) {
            <div class="top-title">
              <span class="top-title-icon"><bi-icon [name]="p.icon" [size]="18" /></span>
              <span class="top-title-text"><b>{{ p.title }}</b><span class="muted small">{{ p.hint }}</span></span>
            </div>
          }
          <div class="top-right">
            <span class="ro-pill"><bi-icon name="shield" [size]="14" /> Read-only</span>
            <div class="top-user">
              <span class="avatar" aria-hidden="true"><bi-icon name="sparkles" [size]="16" /></span>
              <span class="top-user-text"><b>Actuvara BI</b><span class="muted small">Business Intelligence</span></span>
            </div>
          </div>
        </header>
        <main class="main"><router-outlet /></main>
      </div>
    </div>
    @if (ui.openSubmissionId(); as id) {
      <bi-submission-drawer [id]="id" (close)="ui.openSubmissionId.set(null)" (ask)="ui.ask($event)" />
    }`,
})
export class AppComponent {
  ui = inject(UiStateService);
  collapsed = signal(false);

  sections: { title: string; items: NavItem[] }[] = [
    { title: 'General', items: [
      { path: '/overview', label: 'Dashboard', icon: 'dashboard', title: 'Dashboard',
        hint: 'Submissions, extraction runs and workflow health at a glance' },
      { path: '/submissions', label: 'Submissions', icon: 'inbox', title: 'Submissions',
        hint: 'Every email, webhook and manual upload and what happened to it' },
      { path: '/data', label: 'Data model', icon: 'database', title: 'Data model',
        hint: 'Collections in the database and how they connect' },
    ] },
    { title: 'Tools', items: [
      { path: '/assistant', label: 'Assistant', icon: 'sparkles', badge: 'AI', title: 'AI Assistant',
        hint: 'Ask questions about your document-processing data' },
    ] },
  ];

  private url = toSignal(inject(Router).events.pipe(
    filter((e): e is NavigationEnd => e instanceof NavigationEnd),
    map(e => e.urlAfterRedirects),
  ), { initialValue: '' });

  /** The nav item for the current page, shown in the top bar. */
  page = computed(() => {
    const path = this.url().split(/[?#]/)[0];
    return this.sections.flatMap(s => s.items).find(n => path === n.path || path.startsWith(n.path + '/'));
  });

}
