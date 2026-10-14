import { Routes } from '@angular/router';

import { ChatPage } from './pages/chat';
import { DashboardPage } from './pages/dashboard';

export const routes: Routes = [
  { path: 'analytics', component: DashboardPage, title: 'Analytics · Actuvara BI' },
  { path: 'dashboard', redirectTo: 'analytics' }, // old address
  { path: 'submissions', redirectTo: 'analytics' }, // page removed; old links land on Analytics
  { path: 'chat', component: ChatPage, title: 'Ask AI · Actuvara BI' },
  { path: 'chat/:id', component: ChatPage, title: 'Ask AI · Actuvara BI' },
  { path: '', pathMatch: 'full', redirectTo: 'analytics' },
  { path: '**', redirectTo: 'analytics' },
];
