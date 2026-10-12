// Shapes returned by BI_Backend/api_server.py.

/** GET /api/health */
export interface Health {
  database: boolean;            // reachable?
  database_name?: string;
  database_error?: string;
  chat_configured?: boolean;    // a model key (Azure OpenAI / Claude) is set
}

export interface Period {
  submissions: number;
  submissions_by_source: Record<string, number>;
  files: number;
  runs: number;
  runs_by_status: Record<string, number>;
  completed_runs: number;
  failed_runs: number;
  validated_runs: number;
  success_rate: number | null;
  avg_processing_s: number | null;
  avg_confidence: number | null;
}

export interface FunnelStage { stage: string; value: number; }

export interface Overview {
  days: number; from: string; to: string; previous_from: string;
  current: Period; previous: Period;
  change_pct: Record<string, number | null>;
  funnel: FunnelStage[];
}

export interface TrendRow { date: string; runs: number; [source: string]: number | string; }
export interface Trend { days: number; sources: string[]; rows: TrendRow[]; peak: string | null; }

export interface ProcessRow {
  process_id: string | null; name: string; runs: number; completed: number; failed: number; other: number;
  success_rate: number | null; avg_processing_s: number | null;
}

export interface NodeHotspot {
  node_id: string; name: string; process: string | null; total: number;
  by_status: Record<string, number>; sample_reason: string | null; sample_run_id: string | null;
}

export interface CollectionRow { collection: string; documents: number | null; }

export interface SubmissionRow {
  submission_id: string; source: string; title: string | null; from: string | null;
  received_at: string | null; status: string | null; files: number; runs: number; run_status: string;
}

export interface RunSummary {
  run_id: string; process: string | null; status: string | null; started_at: string | null;
  duration_s: number | null; confidence_score: number | null; error_message: string | null;
  node_progress: string; current_step: { step: number; name: string; status: string } | null;
  needs_attention: { step: number; name: string; status: string; error?: Record<string, unknown> }[];
}

export interface SubmissionFile {
  file_id: string; filename: string | null; file_type: string | null; pages: number | null;
  status: string | null; origin: string; run_status: string; runs: RunSummary[];
}

export interface Submission {
  submission_id: string; source: string; collection: string; details: Record<string, unknown>;
  totals: { files: number; runs: number; run_status: string; runs_by_status: Record<string, number> };
  files: SubmissionFile[]; note?: string;
}

export interface RunNode {
  step: number; node_id: string; name: string | null; type: string | null; status: string | null;
  duration_s: number | null; actions: string; error?: Record<string, unknown>;
  outcome?: Record<string, unknown>; summary?: string;
}

export interface RunDetails {
  run_id: string; process: string | null; status: string | null; duration_s: number | null;
  confidence_score: number | null; error_message: string | null; nodes: RunNode[];
}

/** Chart spec returned by the assistant (BI_Backend/charts.py). */
export interface ChartSpec {
  title: string;
  type: 'bar' | 'hbar' | 'line' | 'pie' | 'doughnut' | 'table' | 'kpi' | 'error';
  labels?: string[];
  series?: { name: string; data: (number | null)[] }[];
  columns?: string[];
  rows?: unknown[][];
  value?: number | null;
  unit?: string;
  note?: string;
  error?: string;
}

export interface ChatTurn { role: 'user' | 'assistant'; content: string; }

/** POST /api/chat reply. */
export interface ChatReply {
  answer: string;
  charts: ChartSpec[];
  steps: { tool: string; input: Record<string, unknown>; ok: boolean }[];
}
