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
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  charts?: ChartSpec[];
  steps?: ToolStep[];
  error?: boolean;
}

export interface Health {
  database: boolean;
  database_name?: string;
  database_error?: string;
  chat_configured: boolean;
}
