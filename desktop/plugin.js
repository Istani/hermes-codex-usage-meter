import { host, haptic, PALETTE_AREA, Tip, useMutation, useQuery, useQueryClient } from '@hermes/plugin-sdk'
import { useEffect, useMemo, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'codex-usage-meter'
const DEFAULTS = { mode: 'workweek', notifications: false, osNotifications: false, overPlanThreshold: 12, restBudgetThreshold: 45 }

function clamp(value) { return Math.max(0, Math.min(100, Math.round(Number(value)))) }
function formatTime(iso) { if (!iso) return 'wird aktualisiert'; const d = new Date(iso); return Number.isNaN(d.valueOf()) ? 'wird aktualisiert' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(d) }
function relative(iso) { const ms = new Date(iso).valueOf() - Date.now(); if (!Number.isFinite(ms) || ms <= 0) return 'wird aktualisiert'; const mins = Math.ceil(ms / 60000); return mins >= 60 ? `Reset in ${Math.floor(mins / 60)} h ${mins % 60} min` : `Reset in ${mins} min` }
function pctText(window) { return window ? `${window.remaining_percent} % übrig` : 'Nicht verfügbar' }
function style(width, state) { return { width: `${clamp(width)}%`, background: state === 'danger' ? 'var(--ui-red)' : state === 'good' ? 'var(--ui-green)' : 'var(--ui-accent)' } }

function Meter({ label, window, compact = false }) {
  const used = window?.used_percent
  const reset = window?.reset_at
  return jsxs('div', { className: compact ? 'flex min-w-0 flex-1 flex-col gap-1' : 'flex flex-col gap-2 rounded-md border border-(--ui-stroke-secondary) p-3', children: [
    jsxs('div', { className: 'flex items-baseline justify-between gap-2', children: [
      jsx('span', { className: compact ? 'text-[0.625rem] text-(--ui-text-quaternary)' : 'font-medium text-foreground', children: label }),
      jsx('span', { className: compact ? 'shrink-0 text-[0.625rem] tabular-nums text-(--ui-text-secondary)' : 'shrink-0 tabular-nums text-(--ui-text-secondary)', children: pctText(window) })
    ] }),
    jsx('div', { className: 'h-1.5 overflow-hidden rounded-full bg-(--ui-stroke-tertiary)', children: window ? jsx('span', { className: 'block h-full rounded-full', style: style(used, used >= 85 ? 'danger' : undefined) }) : null }),
    !compact && jsx('div', { className: 'flex justify-between gap-2 text-[0.6875rem] text-(--ui-text-tertiary)', children: reset ? `${formatTime(reset)} · ${relative(reset)}` : 'Reset wird aktualisiert' })
  ] })
}

function paceFor(window, mode) {
  if (!window?.reset_at || !window?.window_duration_minutes || window.reset_state === 'refreshing') return null
  const reset = new Date(window.reset_at); const start = new Date(reset.valueOf() - window.window_duration_minutes * 60000); const now = new Date(Math.min(Math.max(Date.now(), start.valueOf()), reset.valueOf()))
  const span = (from, to) => {
    if (mode === 'calendar') return Math.max(0, to - from)
    let total = 0; let cursor = new Date(from)
    while (cursor < to) { const end = new Date(cursor); end.setHours(24, 0, 0, 0); const slice = new Date(Math.min(end, to)); if (cursor.getDay() !== 0 && cursor.getDay() !== 6) total += Math.max(0, slice - cursor); cursor = end }
    return total
  }
  const total = span(start, reset); if (!total) return null
  const target = clamp(100 * span(start, now) / total); const delta = window.used_percent - target
  return { target, delta, status: delta <= -7 ? 'under_plan' : delta >= 7 ? 'over_plan' : 'im_plan' }
}
function paceCopy(pace) { if (!pace) return { title: 'Nicht verfügbar', text: 'Der echte Wochen-Reset wird noch aktualisiert.' }; if (pace.status === 'under_plan') return { title: 'unter Plan', text: `Du liegst ${Math.abs(pace.delta)} % unter deinem Wochenplan – gut für einen größeren Task.` }; if (pace.status === 'over_plan') return { title: 'über Plan', text: `Du liegst ${pace.delta} % über Plan – Routineaufgaben besser mit Luna erledigen.` }; return { title: 'im Plan', text: 'Dein Wochenverbrauch liegt im geplanten Rahmen.' } }

function useSettings(ctx) { const [settings, setSettings] = useState(DEFAULTS); useEffect(() => { let live = true; Promise.resolve(ctx.storage.get('settings')).then(saved => { if (live && saved && typeof saved === 'object') setSettings({ ...DEFAULTS, ...saved }) }).catch(() => {}); return () => { live = false } }, [ctx]); const update = patch => { const next = { ...settings, ...patch }; setSettings(next); Promise.resolve(ctx.storage.set('settings', next)).catch(() => host.notify({ kind: 'error', message: 'Einstellung konnte nicht gespeichert werden.' })) }; return [settings, update] }

function UsageView({ ctx }) {
  const [settings, update] = useSettings(ctx); const client = useQueryClient()
  const query = useQuery({ queryKey: [ID, 'usage'], queryFn: () => ctx.rest('/usage', { timeoutMs: 20000 }), enabled: true, refetchInterval: () => document.visibilityState === 'visible' ? 60000 : 300000, retry: 1, staleTime: 45000, refetchOnWindowFocus: true })
  const refresh = useMutation({ mutationFn: () => ctx.rest('/refresh', { method: 'POST', timeoutMs: 20000 }), onSuccess: data => client.setQueryData([ID, 'usage'], data) })
  const response = query.data; const data = response?.data; const pace = useMemo(() => paceFor(data?.week, settings.mode), [data?.week, settings.mode]); const message = paceCopy(pace)
  useEffect(() => { if (!data || !settings.notifications || !pace) return; const high = pace.status === 'over_plan' && pace.delta >= settings.overPlanThreshold; const late = data.week?.remaining_percent >= settings.restBudgetThreshold && data.week?.reset_at && (new Date(data.week.reset_at) - Date.now()) < 2 * 86400000; if (!high && !late) return; const key = `${high ? 'over' : 'rest'}:${data.week?.reset_at}`; Promise.resolve(ctx.storage.get('noticeKey')).then(previous => { if (previous === key) return; ctx.storage.set('noticeKey', key); const body = high ? `Wochenverbrauch ${pace.delta} % über Plan.` : `${data.week.remaining_percent} % Wochenbudget sind kurz vor Reset noch frei.`; host.notify({ kind: 'info', message: `Codex-Verbrauch: ${body}` }); if (settings.osNotifications) ctx.os.notify({ title: 'Codex-Verbrauch', body, silent: true, activate: { path: '/' } }) }).catch(() => {}) }, [data, pace, settings, ctx])
  const stateText = query.isLoading ? 'Lade lokale Codex-Limits …' : response?.message || (query.isError ? 'Abruf fehlgeschlagen.' : 'Nicht verfügbar')
  return jsxs('section', { className: 'flex h-full flex-col gap-3 overflow-auto p-3 text-sm', children: [
    jsxs('header', { className: 'flex items-start justify-between gap-3', children: [jsxs('div', { children: [jsx('h2', { className: 'font-medium text-foreground', children: 'Codex-Verbrauch' }), jsx('p', { className: `mt-1 text-[0.6875rem] ${response?.stale ? 'text-(--ui-yellow)' : 'text-(--ui-text-tertiary)'}`, children: `${stateText}${response?.stale ? ' · veraltete Daten' : ''}` })] }), jsx('button', { type: 'button', className: 'rounded-md border border-(--ui-stroke-secondary) px-2 py-1 text-xs text-(--ui-text-secondary) hover:bg-(--chrome-action-hover)', disabled: refresh.isPending, onClick: () => refresh.mutate(), children: refresh.isPending ? 'Aktualisiere …' : 'Aktualisieren' })] }),
    jsx(Meter, { label: '5-Stunden-Fenster', window: data?.five_hour }), jsx(Meter, { label: 'Woche', window: data?.week }),
    jsxs('div', { className: 'flex flex-col gap-2 rounded-md border border-(--ui-stroke-secondary) p-3', children: [jsx('div', { className: 'flex items-baseline justify-between', children: [jsx('span', { className: 'font-medium text-foreground', children: 'Wochen-Pace' }), jsx('span', { className: `text-[0.6875rem] ${pace?.status === 'over_plan' ? 'text-(--ui-red)' : pace?.status === 'under_plan' ? 'text-(--ui-green)' : 'text-(--ui-text-secondary)'}`, children: message.title })] }), pace ? jsx('div', { className: 'text-[0.6875rem] tabular-nums text-(--ui-text-secondary)', children: `Ist ${data.week.used_percent} % · Soll ${pace.target} %` }) : null, jsx('p', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: message.text })] }),
    jsxs('div', { className: 'flex flex-col gap-2 rounded-md border border-(--ui-stroke-secondary) p-3', children: [jsx('div', { className: 'font-medium text-foreground', children: 'Einstellungen' }), jsxs('label', { className: 'flex items-center justify-between gap-3 text-[0.75rem] text-(--ui-text-secondary)', children: [jsx('span', { children: 'Verteilungsmodus' }), jsx('select', { className: 'rounded border border-(--ui-stroke-secondary) bg-transparent px-1 py-0.5 text-[0.75rem] text-foreground', value: settings.mode, onChange: e => update({ mode: e.target.value }), children: [jsx('option', { value: 'workweek', children: 'Arbeitswoche' }), jsx('option', { value: 'calendar', children: 'Kalenderwoche' })] })] }), jsxs('label', { className: 'flex items-center gap-2 text-[0.75rem] text-(--ui-text-secondary)', children: [jsx('input', { type: 'checkbox', checked: settings.notifications, onChange: e => update({ notifications: e.target.checked }) }), 'Lokale Hinweise aktivieren'] }), settings.notifications ? jsxs('label', { className: 'flex items-center gap-2 text-[0.75rem] text-(--ui-text-secondary)', children: [jsx('input', { type: 'checkbox', checked: settings.osNotifications, onChange: e => update({ osNotifications: e.target.checked }) }), 'OS-Benachrichtigungen aktivieren'] }) : null] }),
    data?.available_reset_credits != null ? jsx('p', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: `Verfügbare Reset-Credits: ${data.available_reset_credits}` }) : null,
    jsx('p', { className: 'text-[0.6875rem] text-(--ui-text-quaternary)', children: response?.source_updated_at ? `Zuletzt erfolgreich aktualisiert: ${formatTime(response.source_updated_at)} · Lokale Datenquelle` : 'Noch keine erfolgreiche Aktualisierung.' })
  ] })
}

function Status({ ctx }) { const query = useQuery({ queryKey: [ID, 'usage'], queryFn: () => ctx.rest('/usage', { timeoutMs: 20000 }), enabled: true, refetchInterval: () => document.visibilityState === 'visible' ? 60000 : 300000, retry: 1, staleTime: 45000 }); const data = query.data?.data; const warning = query.data?.stale || query.isError || !data; const label = warning ? (query.data?.message || 'Lokale Codex-Limits nicht verfügbar') : `5 h: ${data.five_hour?.remaining_percent ?? '—'} % übrig · Woche: ${data.week?.remaining_percent ?? '—'} % übrig`; return jsx(Tip, { label, children: jsxs('button', { type: 'button', className: 'inline-flex h-full items-center gap-1.5 px-1.5 text-[0.6875rem] text-(--ui-text-tertiary) hover:text-foreground', onClick: () => { haptic('tap'); host.openWorkspace(`${ID}.detail`, { title: 'Codex-Verbrauch', render: () => jsx(UsageView, { ctx }) }) }, children: [jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Codex' }), jsx(Meter, { label: '5 h', window: data?.five_hour, compact: true }), jsx(Meter, { label: 'Woche', window: data?.week, compact: true }), warning ? jsx('span', { className: 'text-(--ui-yellow)', children: '!' }) : null] }) }) }

export default { id: ID, name: 'Codex Usage Meter', defaultEnabled: false, register(ctx) { const render = () => jsx(UsageView, { ctx }); ctx.register({ id: 'status', area: 'statusBar.right', order: 125, render: () => jsx(Status, { ctx }) }); ctx.register({ id: 'pane', area: 'panes', title: 'Codex-Verbrauch', data: { placement: 'right', width: '320px' }, render }); ctx.register({ id: 'open', area: PALETTE_AREA, data: { id: `${ID}.open`, label: 'Codex-Verbrauch anzeigen', keywords: ['codex', 'verbrauch', 'quota', 'limits'], run: () => host.openWorkspace(`${ID}.detail`, { title: 'Codex-Verbrauch', render }) } }) } }
