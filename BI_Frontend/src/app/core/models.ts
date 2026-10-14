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
  /** One-sentence takeaway written by the assistant (build_chart insight). */
  insight?: string;
  /** Label to emphasise; the other bars are muted. */
  highlight?: string;
}

/** /api/dashboard - the Analytics page (BI_Backend/dashboard.py). Panels are null when their query failed. */
export interface DashboardData {
  days: number;
  source: string;
  process: string;
  process_name: string | null;
  generated_at: string;
  /** Most recent run in scope, any time - shown when the period is empty. */
  latest_activity: string | null;
  filters: { sources: Option[]; processes: (Option & { runs: number })[] };
  errors: Record<string, string>;
  kpis: Kpi[] | null;
  pipeline: Pipeline | null;
  processes: ProcessRow[] | null;
  trend: ChartSpec | null;
  bottlenecks: Bottleneck[] | null;
  review_queue: ReviewItem[] | null;
  by_source: ChartSpec | null;
  recent: ChartSpec | null;
  insights: Insight[];
}

export interface Option {
  value: string;
  label: string;
}

export interface Kpi {
  key: string;
  title: string;
  value: number | null;
  unit: string;
  previous: number | null;
  /** Relative change (0.25 = +25%) for counts, percentage points for rates; null = nothing to compare. */
  delta: number | null;
  delta_kind: 'count' | 'points';
  better: 'higher' | 'lower' | 'neutral';
  spark: (number | null)[] | null;
  hint: string | null;
}

export interface Pipeline {
  stages: { key: string; label: string; value: number; hint: string }[];
  leaks: { key: string; label: string; value: number; tone: 'neutral' | 'warning' | 'critical' }[];
  note: string;
}

export interface ProcessRow {
  process_id: string | null;
  name: string;
  runs: number;
  completed: number;
  review: number;
  failed: number;
  rejected: number;
  completion: number | null;
  confidence: number | null;
  time_s: number | null;
  last_run: string | null;
  spark: number[];
}

export interface Bottleneck {
  process: string;
  process_id: string;
  step: string;
  failed: number;
  awaiting_approval: number;
  rejected: number;
  total: number;
}

export interface ReviewItem {
  run_id: string;
  file: string;
  process: string;
  waiting_since: string | null;
  waiting_days: number | null;
  confidence: number | null;
}

export interface Insight {
  kind: 'observation' | 'risk' | 'gap';
  text: string;
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

/** One conversation in the chat history (saved in this browser). */
export interface Conversation {
  id: string;
  /** The first question, shortened; can be renamed. */
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
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
