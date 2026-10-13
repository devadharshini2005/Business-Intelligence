import { Routes } from '@angular/router';

import { ChatPage } from './pages/chat';
import { DashboardPage } from './pages/dashboard';
import { SubmissionsPage } from './pages/submissions';

export const routes: Routes = [
  { path: 'analytics', component: DashboardPage, title: 'Analytics · Actuvara BI' },
  { path: 'dashboard', redirectTo: 'analytics' }, // old address
  { path: 'submissions', component: SubmissionsPage, title: 'Submissions · Actuvara BI' },
  { path: 'chat', component: ChatPage, title: 'Ask AI · Actuvara BI' },
  { path: 'chat/:id', component: ChatPage, title: 'Ask AI · Actuvara BI' },
  { path: '', pathMatch: 'full', redirectTo: 'analytics' },
  { path: '**', redirectTo: 'analytics' },
];
