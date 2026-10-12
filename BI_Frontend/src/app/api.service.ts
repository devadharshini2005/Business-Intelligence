import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';

import {
  ChatReply, ChatTurn, CollectionRow, Health, NodeHotspot, Overview, ProcessRow, RunDetails, Submission,
  SubmissionRow, Trend,
} from './models';

/** Client for BI_Backend/api_server.py (proxied at /api in development). */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  private get<T>(path: string, params: Record<string, string | number | undefined> = {}): Observable<T> {
    let p = new HttpParams();
    for (const [k, v] of Object.entries(params)) if (v !== '' && v != null) p = p.set(k, String(v));
    return this.http.get<T>(`/api/${path}`, { params: p }).pipe(
      catchError((e: HttpErrorResponse) =>
        throwError(() => new Error(e.error?.error || (e.status ? `HTTP ${e.status}` : 'API server not reachable')))),
    );
  }

  health() { return this.get<Health>('health'); }
  overview(days: number) { return this.get<Overview>('overview', { days }); }
  trend(days: number) { return this.get<Trend>('trend', { days }); }
  processes(days: number) { return this.get<ProcessRow[]>('processes', { days }); }
  nodeHotspots(days: number) { return this.get<NodeHotspot[]>('node-hotspots', { days }); }
  collections() { return this.get<CollectionRow[]>('collections'); }
  submissions(q: { source?: string; status?: string; search?: string; days?: number; limit?: number }) {
    return this.get<SubmissionRow[]>('submissions', q);
  }
  submission(id: string) { return this.get<Submission>(`submissions/${encodeURIComponent(id)}`); }
  run(id: string) { return this.get<RunDetails>(`runs/${encodeURIComponent(id)}`); }

  /** Ask the assistant: the whole conversation goes up, one answer (text + charts + the queries it ran) comes back. */
  async chat(messages: ChatTurn[], signal?: AbortSignal): Promise<ChatReply> {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
      signal,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof body.detail === 'string' ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d: { msg?: string }) => d.msg).join('; ') : '';
      throw new Error(detail || `The API server answered HTTP ${res.status}.`);
    }
    return { answer: body.answer ?? '', charts: body.charts ?? [], steps: body.steps ?? [] };
  }
}
