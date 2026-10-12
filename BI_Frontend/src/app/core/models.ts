/** Chart spec produced by the backend (BI_Backend/charts.py). */
export type ChartType = 'bar' | 'hbar' | 'line' | 'pie' | 'doughnut' | 'table' | 'kpi' | 'error';

export interface ChartSeries {
  name: string;
  data: (number | null)[];
}

export interface ChartSpec {
  id?: string;
  title: string;
  type: ChartType;
  labels?: string[];
  series?: ChartSeries[];
  columns?: string[];
  rows?: unknown[][];
  /** Table rows that open a detail view (e.g. submission ids), same order as rows. */
  row_ids?: (string | null)[];
  value?: number | null;
  unit?: string;
  status?: 'critical' | 'warning' | 'good' | null;
  status_colors?: boolean;
  error?: string;
}

export interface DashboardData {
  days: number;
  generated_at: string;
  kpis: ChartSpec[];
  kpi_error?: string;
  charts: ChartSpec[];
}

export interface ToolStep {
  tool: string;
  input: Record<string, unknown>;
  ok: boolean;
}

export interface ChatResponse {
  answer: string;
  charts: ChartSpec[];
  steps: ToolStep[];
  follow_ups?: string[];
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  charts?: ChartSpec[];
  steps?: ToolStep[];
  followUps?: string[];
  /** Still being answered (steps and charts arrive live). */
  pending?: boolean;
  error?: boolean;
  at?: string;
}

export interface Health {
  database: boolean;
  database_name?: string;
  database_error?: string;
  chat_configured: boolean;
}

/** /api/submissions/{id} - BI_Backend/idp_flow.py get_submission(). */
export interface RunSummary {
  run_id: string;
  process: string | null;
  status: string | null;
  started_at: string | null;
  completed_at?: string | null;
  duration_s?: number | null;
  confidence_score?: number | null;
  error_message?: string | null;
  node_progress?: string | null;
  node_status_counts?: Record<string, number>;
  needs_attention?: { step: number; name: string; status: string; error?: string }[];
  current_step?: { step: number; name: string; status: string } | null;
  fetched_documents?: number;
  [key: string]: unknown;
}

export interface FileSummary {
  file_id: string;
  filename: string | null;
  file_type: string | null;
  file_size: number | null;
  pages: number | null;
  status: string | null;
  uploaded_at: string | null;
  origin: string;
  run_status: string;
  runs: RunSummary[];
}

export interface Submission {
  submission_id: string;
  source: string;
  collection: string;
  details: Record<string, unknown>;
  totals: { files: number; runs: number; run_status: string; runs_by_status: Record<string, number> };
  files: FileSummary[];
  note?: string;
}

/** /api/submissions - one row of MCP idp_find_submissions. */
export interface SubmissionRow {
  submission_id: string;
  source: string;
  title: string | null;
  from: string | null;
  received_at: string | null;
  status: string | null;
  files?: number;
  runs?: number;
  run_status?: string;
}

/** MCP tools wrap lists as {rows, row_count, truncated, note?}. */
export interface Envelope<T> {
  rows: T[];
  row_count: number;
  truncated: boolean;
  total_found?: number;
  note?: string;
}

/** /api/collections - MCP list_collections. */
export interface CollectionRow {
  collection: string;
  type: string;
  approx_documents: number | null;
  view_on?: string | null;
  capped?: boolean;
  has_validator?: boolean;
}

/** /api/collections/{c}/schema - MCP infer_collection_schema. */
export interface SchemaField {
  field: string;
  types: string;
  present_in: number;
  sampled_docs: number;
  presence_pct: number;
}

/** /api/mcp - the MCP server behind every number on screen. */
export interface McpInfo {
  server: string;
  transport: string;
  server_info: { hosts?: string[]; default_database?: string | null; version?: string } | null;
  tools: { name: string; description: string }[];
}

/** One request the UI made, and the MCP tool that answered it. */
export interface McpCall {
  tool: string;
  at: Date;
  /** Round trip in ms; absent for tools the chatbot called (timed server-side). */
  ms?: number;
  ok: boolean;
  /** Who asked: a page of the UI, or the chatbot. */
  via: 'ui' | 'chat';
}
