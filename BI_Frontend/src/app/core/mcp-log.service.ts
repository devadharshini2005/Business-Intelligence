import { Injectable, signal } from '@angular/core';

import { McpCall } from './models';

const MAX = 12;

/**
 * Every request the UI makes, tagged with the MCP tool that served it. The source panel shows
 * this log so it is always visible that the numbers came through the MCP server - the API has
 * no other route to the database.
 */
@Injectable({ providedIn: 'root' })
export class McpLog {
  readonly calls = signal<McpCall[]>([]);

  record(call: McpCall): void {
    this.calls.update((list) => [call, ...list].slice(0, MAX));
  }
}
