import { KeyValuePipe, NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService, DateRange } from '../api.service';
import { compact, duration, full, SOURCE_LABEL, statusRole } from '../format';
import { NodeHotspot, Overview, ProcessRow, SubmissionRow, Trend } from '../models';
import { FlowBucket, FlowChartComponent, FlowSeries } from '../shared/flow-chart.component';
import { GaugeComponent, GaugePart } from '../shared/gauge.component';
import { IconComponent } from '../shared/icon.component';
import { StatusBadgeComponent } from '../shared/status-badge.component';
import { SubmissionsTableComponent } from '../shared/submissions-table.component';
import { WeekdayChartComponent } from '../shared/weekday-chart.component';
import { UiStateService } from '../ui-state.service';
import { load, loadable } from './load';

const MONTH = { month: 'short' } as const;
const DAY_MONTH = { day: '2-digit', month: 'short' } as const;

/** Local calendar date as YYYY-MM-DD (what <input type="date"> uses). */
function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
/** Days from start to end, both included. */
function dayCount(start: string, end: string): number {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 864e5) + 1;
}

@Component({
  selector: 'bi-overview',
  imports: [FormsModule, KeyValuePipe, NgTemplateOutlet, FlowChartComponent, GaugeComponent, IconComponent, StatusBadgeComponent,
            SubmissionsTableComponent, WeekdayChartComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './overview.page.html',
  host: { '(document:click)': 'menu.set(null)' },
})
export class OverviewPage {
  private api = inject(ApiService);
  ui = inject(UiStateService);

  ranges = [{ days: 0, label: 'All time' }, { days: 7, label: 'Last 7 days' }, { days: 30, label: 'Last 30 days' }, { days: 90, label: 'Last 90 days' }];
  /** Preset length in days; 0 = all time (the default). */
  days = signal(0);
  /** A range picked on the calendar; null while a preset (`days`) is in use. */
  custom = signal<DateRange | null>(null);
  /** Length of the period shown, in days. */
  span = computed(() => { const c = this.custom(); return c ? dayCount(c.start, c.end) : this.days(); });
  /** No period to compare with, so change badges are hidden. */
  allTime = computed(() => !this.custom() && this.days() === 0);
  today = isoDay(new Date());
  draftStart = '';
  draftEnd = '';
  menu = signal<'calendar' | 'range' | 'filter' | 'weekday' | null>(null);
  hiddenSources = signal<Set<string>>(new Set());
  weekdayMetric = signal<'runs' | 'submissions'>('runs');
  selected = signal<Set<string>>(new Set());

  overview = loadable<Overview>();
  trend = loadable<Trend>();
  processes = loadable<ProcessRow[]>();
  hotspots = loadable<NodeHotspot[]>();
  recent = loadable<SubmissionRow[]>();

  compact = compact; full = full; duration = duration;
  sourceLabel = (s: string) => SOURCE_LABEL[s] || s;

  constructor() {
    this.refresh();
    load(this.api.submissions({ limit: 8 }), this.recent);
  }

  setDays(d: number) {
    this.days.set(d);
    this.custom.set(null);
    this.menu.set(null);
    this.selected.set(new Set());
    this.refresh();
  }

  refresh() {
    const d = this.days();
    const r = this.custom() ?? undefined;
    load(this.api.overview(d, r), this.overview);
    load(this.api.trend(d, r), this.trend);
    load(this.api.processes(d, r), this.processes);
    load(this.api.nodeHotspots(d, r), this.hotspots);
  }

  toggleMenu(m: 'calendar' | 'range' | 'filter' | 'weekday', ev: Event) {
    ev.stopPropagation();
    if (m === 'calendar' && this.menu() !== 'calendar') {
      // Start the pickers on the period currently shown.
      const c = this.custom();
      const first = this.trend().data?.rows[0]?.date;
      this.draftStart = c?.start ?? (this.days() ? isoDay(new Date(Date.now() - (this.days() - 1) * 864e5))
        : first ?? isoDay(new Date(Date.now() - 29 * 864e5)));
      this.draftEnd = c?.end ?? this.today;
    }
    this.menu.set(this.menu() === m ? null : m);
  }

  draftDays() {
    return this.draftStart && this.draftEnd && this.draftStart <= this.draftEnd ? dayCount(this.draftStart, this.draftEnd) : 0;
  }

  applyRange() {
    if (!this.draftDays()) return;
    this.custom.set({ start: this.draftStart, end: this.draftEnd });
    this.menu.set(null);
    this.selected.set(new Set());
    this.refresh();
  }

  periodText() {
    const c = this.custom();
    if (c) return `from ${c.start} to ${c.end} (${this.span()} days)`;
    return this.days() ? `the last ${this.days()} days` : 'all time';
  }

  ask(q: string) { this.ui.ask(`${q} (Dashboard period: ${this.periodText()}.)`); }

  askNode(n: NodeHotspot) {
    const where = n.process ? ` in the "${n.process}" process` : '';
    this.ask(`Why does the "${n.name}" workflow node${where} keep failing or waiting for approval? Show examples.`);
  }

  // --- header ------------------------------------------------------------------
  rangeLabel = computed(() => {
    const c = this.custom();
    if (c) {
      const day = (s: string) => new Date(`${s}T00:00:00`).toLocaleDateString(undefined, DAY_MONTH);
      return `${day(c.start)} – ${day(c.end)}`;
    }
    const o = this.overview().data;
    const valid = (d: Date) => !Number.isNaN(d.getTime());
    let to = new Date(o?.to ?? '');
    // All time has no "from": start at the first day with data.
    let from = new Date(o?.from ?? (this.trend().data?.rows[0]?.date ? `${this.trend().data!.rows[0].date}T00:00:00` : ''));
    if (!valid(to) || !valid(from)) {
      to = new Date();
      from = new Date(Date.now() - this.days() * 864e5);
    }
    return `${from.toLocaleDateString(undefined, DAY_MONTH)} – ${to.toLocaleDateString(undefined, DAY_MONTH)}`;
  });
  periodLabel = computed(() => {
    const n = this.span();
    return this.custom() ? `${n} day${n === 1 ? '' : 's'}` : this.ranges.find((r) => r.days === n)?.label ?? `Last ${n} days`;
  });

  toggleSource(key: string, ev: Event) {
    ev.stopPropagation();
    const next = new Set(this.hiddenSources());
    if (next.has(key)) next.delete(key); else next.add(key);
    // Keep at least one source visible.
    if (next.size < (this.trend().data?.sources.length ?? 3)) this.hiddenSources.set(next);
  }

  // --- KPI cards ---------------------------------------------------------------
  kpis = computed(() => {
    const o = this.overview().data;
    if (!o) return [];
    const c = o.current;
    return [
      { icon: 'inbox', title: 'Total submissions', value: full(c.submissions), delta: o.change_pct['submissions'],
        goodUp: true, info: this.allTime() ? 'All emails, webhooks and manual uploads received so far.'
          : `Emails, webhooks and manual uploads received in ${this.custom() ? 'the selected' : 'the last'} ${o.days} days, vs the ${o.days} days before.` },
      { icon: 'files', title: 'Files received', value: full(c.files), delta: o.change_pct['files'], goodUp: true,
        info: 'Files sent in with those submissions (their attachments). Files created by workflows (API connector fetches, correction re-uploads) are not counted.' },
      { icon: 'gauge', title: 'Run success rate', value: c.success_rate == null ? '–' : `${c.success_rate}%`,
        delta: o.change_pct['success_rate'], goodUp: true,
        info: 'Share of extraction runs in the period whose status is completed.' },
    ];
  });

  // --- submissions overview (stacked flow) -------------------------------------
  flowSeries = computed<FlowSeries[]>(() => {
    const hidden = this.hiddenSources();
    return (this.trend().data?.sources ?? [])
      .map((s, i) => ({ key: s, label: this.sourceLabel(s), slot: i + 1 }))
      .filter((s) => !hidden.has(s.key));
  });

  /** Days → columns: daily up to a week, weekly up to a month, monthly beyond. */
  flowBuckets = computed<FlowBucket[]>(() => {
    const t = this.trend().data;
    if (!t) return [];
    const days = this.span() || t.rows.length;  // all time: size buckets by the days with data
    const groups = new Map<string, { label: string; title: string; values: Record<string, number> }>();
    t.rows.forEach((r, i) => {
      const d = new Date(`${r.date}T00:00:00`);
      let key: string, label: string, title: string;
      if (days <= 7) {
        key = r.date; label = d.toLocaleDateString(undefined, { weekday: 'short' });
        title = d.toLocaleDateString(undefined, DAY_MONTH);
      } else if (days <= 31) {
        // 7-day buckets counted back from the last day; rows are oldest-first, so the first row
        // seen for a bucket is its start date.
        key = `w${Math.floor((t.rows.length - 1 - i) / 7)}`;
        label = d.toLocaleDateString(undefined, DAY_MONTH);
        title = `Week of ${label}`;
      } else {
        key = r.date.slice(0, 7); label = d.toLocaleDateString(undefined, MONTH);
        title = d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
      }
      const g = groups.get(key) ?? { label, title, values: {} };
      for (const s of t.sources) g.values[s] = (g.values[s] || 0) + Number(r[s] || 0);
      groups.set(key, g);
    });
    return [...groups.values()];
  });

  flowTotal = computed(() => this.flowBuckets().reduce(
    (a, b) => a + this.flowSeries().reduce((x, s) => x + (b.values[s.key] || 0), 0), 0));

  submissionsIncrease = computed(() => {
    const o = this.overview().data;
    return o?.previous ? o.current.submissions - o.previous.submissions : null;
  });

  // --- weekday ------------------------------------------------------------------
  weekday = computed(() => {
    const t = this.trend().data;
    const v = [0, 0, 0, 0, 0, 0, 0];
    if (!t) return v;
    for (const r of t.rows) {
      const n = this.weekdayMetric() === 'runs' ? Number(r.runs || 0)
        : t.sources.reduce((a, s) => a + Number(r[s] || 0), 0);
      v[new Date(`${r.date}T00:00:00`).getDay()] += n;
    }
    return v;
  });
  weekdayTotal = computed(() => this.weekday().reduce((a, b) => a + b, 0));
  weekdayDelta = computed(() => this.overview().data?.change_pct[this.weekdayMetric() === 'runs' ? 'runs' : 'submissions'] ?? null);
  weekdayIncrease = computed(() => {
    const o = this.overview().data;
    if (!o?.previous) return null;
    return this.weekdayMetric() === 'runs' ? o.current.runs - o.previous.runs : o.current.submissions - o.previous.submissions;
  });

  // --- run distribution ----------------------------------------------------------
  distribution = computed(() => {
    const c = this.overview().data?.current;
    if (!c) return [] as GaugePart[];
    let completed = 0, failed = 0, other = 0;
    for (const [s, n] of Object.entries(c.runs_by_status)) {
      const role = statusRole(s);
      if (role === 'good') completed += n; else if (role === 'critical') failed += n; else other += n;
    }
    return [
      { label: 'Completed', value: completed, role: 'good' },
      { label: 'Failed', value: failed, role: 'critical' },
      { label: 'Other', value: other, role: 'neutral' },
    ];
  });

  // --- processes table ---------------------------------------------------------------
  toggleRow(id: string) {
    const next = new Set(this.selected());
    if (next.has(id)) next.delete(id); else next.add(id);
    this.selected.set(next);
  }
  toggleAll() {
    const rows = this.processes().data ?? [];
    this.selected.set(this.selected().size === rows.length ? new Set() : new Set(rows.map((p) => p.name)));
  }
  askSelected() {
    const names = [...this.selected()];
    this.ask(`Compare these processes: ${names.map((n) => `"${n}"`).join(', ')} – run volume, success rate, slowest and most failing nodes.`);
  }
  initial = (name: string) => (name.replace(/[^A-Za-z0-9]/g, '')[0] || '?').toUpperCase();
  avatarSlot = (name: string) => ([...name].reduce((a, ch) => a + ch.charCodeAt(0), 0) % 3) + 1;

  // --- export ----------------------------------------------------------------------
  exportCsv() {
    const t = this.trend().data;
    const o = this.overview().data;
    const lines: string[] = [];
    const esc = (v: unknown) => `"${String(v ?? '').replaceAll('"', '""')}"`;
    if (o) {
      lines.push('Summary', 'metric,current,previous,change_pct');
      for (const k of ['submissions', 'files', 'runs', 'completed_runs', 'failed_runs', 'success_rate',
                       'avg_processing_s', 'avg_confidence'] as const) {
        lines.push([k, o.current[k], o.previous?.[k], o.change_pct[k]].map(esc).join(','));
      }
      lines.push('');
    }
    if (t) {
      lines.push('Daily', ['date', ...t.sources, 'runs'].join(','));
      for (const r of t.rows) lines.push([r.date, ...t.sources.map((s) => r[s]), r.runs].map(esc).join(','));
      lines.push('');
    }
    const p = this.processes().data;
    if (p) {
      lines.push('Processes', 'process,runs,completed,failed,other,success_rate,avg_processing_s');
      for (const r of p) lines.push([r.name, r.runs, r.completed, r.failed, r.other, r.success_rate, r.avg_processing_s].map(esc).join(','));
    }
    const blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const c = this.custom();
    a.download = c ? `actuvara-bi-${c.start}-to-${c.end}.csv`
      : this.days() ? `actuvara-bi-last-${this.days()}-days.csv` : 'actuvara-bi-all-time.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // --- helpers -----------------------------------------------------------------------
  maxHotspot = computed(() => Math.max(1, ...(this.hotspots().data ?? []).map((p) => p.total)));
  good(v: number | null | undefined, goodUp = true) { return v == null || v === 0 ? null : (v > 0) === goodUp; }
  abs(v: number) { return Math.abs(v); }
}
