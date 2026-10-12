import { Routes } from '@angular/router';

import { AssistantPage } from './pages/assistant.page';
import { DataModelPage } from './pages/data-model.page';
import { OverviewPage } from './pages/overview.page';
import { SubmissionsPage } from './pages/submissions.page';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'overview' },
  { path: 'overview', component: OverviewPage, title: 'Overview · Actuvara BI' },
  { path: 'submissions', component: SubmissionsPage, title: 'Submissions · Actuvara BI' },
  { path: 'assistant', component: AssistantPage, title: 'Assistant · Actuvara BI' },
  { path: 'data', component: DataModelPage, title: 'Data model · Actuvara BI' },
  { path: '**', redirectTo: 'overview' },
];
