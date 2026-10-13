import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';

import {
  ChatEvent, ChatReply, ChatTurn, CollectionRow, Health, NodeHotspot, Overview, ProcessRow, RunDetails, Submission,
  SubmissionRow, Trend,
} from './models';

export interface DateRange { start: string; end: string; }

function errorDetail(body: { detail?: unknown }, status: number): string {
  const d = body?.detail;
  const text = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg).join('; ') : '';
  return text || `The API server answered HTTP ${status}.`;
}

function toReply(body: Partial<ChatReply>): ChatReply {
  return { answer: body.answer ?? '', charts: body.charts ?? [], steps: body.steps ?? [] };
}

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
  // `range` (YYYY-MM-DD, both days included) overrides `days` when given.
  overview(days: number, range?: DateRange) { return this.get<Overview>('overview', { days, ...range }); }
  trend(days: number, range?: DateRange) { return this.get<Trend>('trend', { days, ...range }); }
  processes(days: number, range?: DateRange) { return this.get<ProcessRow[]>('processes', { days, ...range }); }
  nodeHotspots(days: number, range?: DateRange) { return this.get<NodeHotspot[]>('node-hotspots', { days, ...range }); }
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
    if (!res.ok) throw new Error(errorDetail(body, res.status));
    return toReply(body);
  }

  /** Like chat(), but reports each step (tool calls, what the agent is doing) through onEvent as it happens. */
  async chatStream(messages: ChatTurn[], onEvent: (e: ChatEvent) => void, signal?: AbortSignal): Promise<ChatReply> {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
      signal,
    });
    if (res.status === 404) return this.chat(messages, signal);  // API server older than the stream endpoint
    if (!res.ok || !res.body) throw new Error(errorDetail(await res.json().catch(() => ({})), res.status));
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      buffer += value ?? '';
      const lines = buffer.split('\n');
      buffer = done ? '' : lines.pop()!;
      for (const line of lines) {
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.type === 'result') return toReply(ev);
        if (ev.type === 'error') throw new Error(ev.detail || `The API server answered HTTP ${ev.status}.`);
        onEvent(ev as ChatEvent);
      }
      if (done) throw new Error('The answer stream ended early - check the API server log.');
    }
  }
}
