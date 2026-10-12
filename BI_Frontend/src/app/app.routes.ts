import { Routes } from '@angular/router';

import { ChatPage } from './pages/chat';
import { DashboardPage } from './pages/dashboard';

export const routes: Routes = [
  { path: 'dashboard', component: DashboardPage, title: 'Dashboard · Actuvara BI' },
  { path: 'chat', component: ChatPage, title: 'Chatbot · Actuvara BI' },
  { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
  { path: '**', redirectTo: 'dashboard' },
];
