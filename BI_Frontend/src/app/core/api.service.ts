import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, defer, tap } from 'rxjs';

import { McpLog } from './mcp-log.service';
import {
  ChartSpec,
  ChatMessage,
  ChatResponse,
  CollectionRow,
  DashboardData,
  Envelope,
  Health,
  McpInfo,
  SchemaField,
  Submission,
  SubmissionRow,
  ToolStep,
} from './models';

export interface ChatStreamHandlers {
  step: (step: ToolStep) => void;
  chart: (chart: ChartSpec) => void;
}

export interface SubmissionQuery {
  source?: string;
  status?: string;
  search?: string;
  days?: number;
  limit?: number;
}

/**
 * Calls BI_Backend/api_server.py. In dev, /api is proxied to :8000 (proxy.conf.json).
 * Every endpoint is a thin wrapper over one MCP tool (named in each call below) - the API
 * never queries the database itself.
 */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly log = inject(McpLog);

  health(): Observable<Health> {
    return this.get('ping_db', '/api/health');
  }

  mcp(): Observable<McpInfo> {
    return this.get('list_tools', '/api/mcp');
  }

  dashboard(days: number): Observable<DashboardData> {
    return this.get('get_dashboard', '/api/dashboard', { days });
  }

  submissions(q: SubmissionQuery): Observable<Envelope<SubmissionRow>> {
    const params: Record<string, string | number> = {};
    for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== '') params[k] = v;
    return this.get('idp_find_submissions', '/api/submissions', params);
  }

  submission(id: string): Observable<Submission> {
    return this.get('idp_get_submission', `/api/submissions/${encodeURIComponent(id)}`);
  }

  collections(): Observable<Envelope<CollectionRow>> {
    return this.get('list_collections', '/api/collections');
  }

  schema(collection: string): Observable<Envelope<SchemaField>> {
    return this.get('infer_collection_schema', `/api/collections/${encodeURIComponent(collection)}/schema`);
  }

  /** GET an endpoint and log which MCP tool answered it, how long it took and whether it worked. */
  private get<T>(tool: string, url: string, params?: Record<string, string | number>): Observable<T> {
    return defer(() => {
      const start = performance.now();
      const done = (ok: boolean) =>
        this.log.record({ tool, at: new Date(), ms: Math.round(performance.now() - start), ok, via: 'ui' });
      return this.http.get<T>(url, { params }).pipe(tap({ next: () => done(true), error: () => done(false) }));
    });
  }

  /**
   * Asks the chatbot and reports progress as it happens (server-sent events from /api/chat/stream).
   * Resolves with the full answer; rejects with a readable message.
   */
  async chatStream(history: ChatMessage[], on: ChatStreamHandlers, signal: AbortSignal): Promise<ChatResponse> {
    let res: Response;
    try {
      res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({ messages: toApiMessages(history) }),
        signal,
      });
    } catch (e) {
      if (signal.aborted) throw new Error('Stopped.');
      throw new Error('Cannot reach the API. Is the backend running on port 8000?');
    }
    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => ({}));
      throw new Error(detailText(body) ?? `${res.status} ${res.statusText}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
      let cut: number;
      while ((cut = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const event = /^event: (.+)$/m.exec(block)?.[1];
        const data = block
          .split('\n')
          .filter((l) => l.startsWith('data: '))
          .map((l) => l.slice(6))
          .join('\n');
        if (!event || !data) continue; // keep-alive comment
        const payload = JSON.parse(data);
        if (event === 'step') on.step(payload);
        else if (event === 'chart') on.chart(payload);
        else if (event === 'done') return payload as ChatResponse;
        else if (event === 'error') throw new Error(payload.detail ?? 'The assistant failed.');
      }
    }
    throw new Error('The connection closed before the answer was complete.');
  }
}

/** Recent turns sent as context. The API accepts at most 40 messages of 20,000 characters each. */
const CONTEXT_MESSAGES = 16;
const MAX_CONTENT = 20_000;

/**
 * Only the text goes back to the model; charts are rebuilt from queries each turn. Older turns are
 * dropped (a long saved chat would exceed the API's limit and every question would get a 422), and
 * the context always starts with a user message.
 */
function toApiMessages(history: ChatMessage[]) {
  const recent = history.filter((m) => !m.error && !m.pending && m.content).slice(-CONTEXT_MESSAGES);
  const start = recent.findIndex((m) => m.role === 'user');
  return recent
    .slice(Math.max(start, 0))
    .map(({ role, content }) => ({ role, content: content.slice(0, MAX_CONTENT) }));
}

/** FastAPI's `detail`: a message string, or (422) a list of {loc, msg} validation errors. */
function detailText(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    const parts = detail.map((d: { loc?: unknown[]; msg?: string }) =>
      [(d.loc ?? []).filter((l) => l !== 'body').join('.'), d.msg].filter(Boolean).join(': '),
    );
    return `The request was rejected - ${parts.join('; ')}`;
  }
  return null;
}

export function errorText(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    if (err.status === 0) return 'Cannot reach the API. Is the backend running on port 8000?';
    return detailText(err.error) ?? `${err.status} ${err.statusText}`;
  }
  return err instanceof Error ? err.message : String(err);
}
