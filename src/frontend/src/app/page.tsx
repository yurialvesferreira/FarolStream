'use client';

/**
 * Painel de operações em tempo real.
 *
 * Um único EventSource (via useSSE) alimenta os três painéis — os eventos
 * chegam NOMEADOS (event: log|alert|trade) e são separados por
 * addEventListener, não por parsing manual em onmessage.
 */

import { EventPanel } from '@/components/EventPanel';
import { useSSE, type ConnectionStatus, type SSEEvent } from '@/hooks/useSSE';

const EVENT_TYPES = ['log', 'alert', 'trade'] as const;

interface LogData {
  level: 'info' | 'warning' | 'error';
  service: string;
  message: string;
  timestamp: string;
}

interface AlertData {
  severity: 'warning' | 'critical';
  title: string;
  source: string;
  timestamp: string;
}

interface TradeData {
  symbol: string;
  price: number;
  change_pct: number;
  side: 'buy' | 'sell';
  quantity: number;
  timestamp: string;
}

const STATUS_LABEL: Record<ConnectionStatus, { text: string; dotClass: string }> = {
  connecting: { text: 'Conectando…', dotClass: 'bg-amber-400' },
  open: { text: 'Stream aberto', dotClass: 'bg-emerald-400 animate-pulse' },
  reconnecting: { text: 'Reconectando…', dotClass: 'bg-red-400' },
};

const LOG_LEVEL_CLASS: Record<LogData['level'], string> = {
  info: 'text-sky-400',
  warning: 'text-amber-400',
  error: 'text-red-400',
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('pt-BR');
}

function renderLog(event: SSEEvent) {
  const log = event.data as LogData;
  return (
    <div className="flex items-baseline gap-2 font-mono text-xs">
      <span className="text-zinc-600 tabular-nums">{formatTime(log.timestamp)}</span>
      <span className={`w-16 shrink-0 uppercase ${LOG_LEVEL_CLASS[log.level]}`}>{log.level}</span>
      <span className="text-zinc-500">{log.service}</span>
      <span className="text-zinc-300">{log.message}</span>
    </div>
  );
}

function renderAlert(event: SSEEvent) {
  const alert = event.data as AlertData;
  const critical = alert.severity === 'critical';
  return (
    <div>
      <div className="flex items-center gap-2">
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
            critical ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'
          }`}
        >
          {alert.severity}
        </span>
        <span className="text-xs text-zinc-500">
          {alert.source} · {formatTime(alert.timestamp)}
        </span>
      </div>
      <p className="mt-1 text-zinc-200">{alert.title}</p>
    </div>
  );
}

function renderTrade(event: SSEEvent) {
  const trade = event.data as TradeData;
  const positive = trade.change_pct >= 0;
  return (
    <div className="flex items-center justify-between font-mono text-xs">
      <div className="flex items-center gap-2">
        <span className="font-bold text-zinc-100">{trade.symbol}</span>
        <span className={trade.side === 'buy' ? 'text-emerald-500' : 'text-red-500'}>
          {trade.side === 'buy' ? 'COMPRA' : 'VENDA'}
        </span>
        <span className="text-zinc-500">×{trade.quantity}</span>
      </div>
      <div className="flex items-center gap-3 tabular-nums">
        <span className="text-zinc-200">R$ {trade.price.toFixed(2)}</span>
        <span className={positive ? 'text-emerald-400' : 'text-red-400'}>
          {positive ? '▲' : '▼'} {Math.abs(trade.change_pct).toFixed(2)}%
        </span>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { status, eventsByType } = useSSE(EVENT_TYPES);
  const statusInfo = STATUS_LABEL[status];

  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            🚨 FarolStream <span className="text-zinc-500 font-normal">· Painel de Operações</span>
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            Server-Sent Events · Redis Pub/Sub · uma conexão, três tipos de evento nomeado
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-400">
          <span className={`h-2 w-2 rounded-full ${statusInfo.dotClass}`} />
          {statusInfo.text}
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-3">
        <EventPanel
          title="Logs"
          subtitle="event: log — publisher-ops"
          accentClass="border-t-sky-500"
          events={eventsByType.log ?? []}
          renderItem={renderLog}
        />
        <EventPanel
          title="Alertas"
          subtitle="event: alert — publisher-ops"
          accentClass="border-t-amber-500"
          events={eventsByType.alert ?? []}
          renderItem={renderAlert}
        />
        <EventPanel
          title="Trades"
          subtitle="event: trade — publisher-market"
          accentClass="border-t-emerald-500"
          events={eventsByType.trade ?? []}
          renderItem={renderTrade}
        />
      </div>
    </main>
  );
}
