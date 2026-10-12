// Display helpers shared by the dashboard and assistant.

export function compact(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '–';
  const abs = Math.abs(n);
  if (abs >= 1e6) return `${(n / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(abs >= 1e4 ? 0 : 1)}k`;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export const full = (n: number | null | undefined) => (n == null ? '–' : Number(n).toLocaleString());

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '–';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso)
    : d.toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function shortDate(isoDay: string): string {
  return new Date(`${isoDay}T00:00:00`).toLocaleDateString(undefined, { day: '2-digit', month: 'short' });
}

export function duration(s: number | null | undefined): string {
  if (s == null) return '–';
  if (s < 60) return `${s.toFixed(1)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
}

export const SOURCE_LABEL: Record<string, string> = {
  email: 'Email', webhook: 'Webhook', manual_upload: 'Manual upload',
};

export type StatusRole = 'good' | 'critical' | 'warning' | 'info' | 'neutral';

/** Status → reserved status role (never a series colour); always rendered with icon + label. */
export function statusRole(status: string | null | undefined): StatusRole {
  const s = (status || '').toLowerCase();
  if (['completed', 'processed', 'success', 'validated'].includes(s)) return 'good';
  if (['failed', 'rejected', 'error', 'has_failures'].includes(s)) return 'critical';
  if (['awaiting_approval', 'pending_review', 'mixed'].includes(s)) return 'warning';
  if (['inprogress', 'in_progress', 'pending', 'received', 'processing'].includes(s)) return 'info';
  return 'neutral';
}
