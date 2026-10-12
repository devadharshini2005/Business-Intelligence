import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ChatMessage, ChatResponse, DashboardData, Health } from './models';

/** Calls BI_Backend/api_server.py. In dev, /api is proxied to :8000 (proxy.conf.json). */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  health(): Observable<Health> {
    return this.http.get<Health>('/api/health');
  }

  dashboard(days: number): Observable<DashboardData> {
    return this.http.get<DashboardData>('/api/dashboard', { params: { days } });
  }

  chat(history: ChatMessage[]): Observable<ChatResponse> {
    // Only the text goes back to the model; charts are re-built from queries each turn.
    const messages = history
      .filter((m) => !m.error && m.content)
      .map(({ role, content }) => ({ role, content }));
    return this.http.post<ChatResponse>('/api/chat', { messages });
  }
}

export function errorText(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    if (err.status === 0) return 'Cannot reach the API. Is the backend running on port 8000?';
    const detail = (err.error as { detail?: unknown })?.detail;
    return typeof detail === 'string' ? detail : `${err.status} ${err.statusText}`;
  }
  return String(err);
}
