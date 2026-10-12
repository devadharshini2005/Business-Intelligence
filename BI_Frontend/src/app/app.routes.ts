import { Routes } from '@angular/router';

import { CatalogPage } from './pages/catalog';
import { ChatPage } from './pages/chat';
import { DashboardPage } from './pages/dashboard';
import { SubmissionsPage } from './pages/submissions';

export const routes: Routes = [
  { path: 'dashboard', component: DashboardPage, title: 'Overview · Actuvara BI' },
  { path: 'submissions', component: SubmissionsPage, title: 'Submissions · Actuvara BI' },
  { path: 'chat', component: ChatPage, title: 'Ask AI · Actuvara BI' },
  { path: 'catalog', component: CatalogPage, title: 'Data catalog · Actuvara BI' },
  { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
  { path: '**', redirectTo: 'dashboard' },
];
