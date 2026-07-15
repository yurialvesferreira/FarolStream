import type { SSEEvent } from '@/hooks/useSSE';

interface EventPanelProps {
  title: string;
  subtitle: string;
  accentClass: string;
  events: SSEEvent[];
  renderItem: (event: SSEEvent) => React.ReactNode;
}

export function EventPanel({ title, subtitle, accentClass, events, renderItem }: EventPanelProps) {
  return (
    <section className="flex flex-col rounded-xl border border-zinc-800 bg-zinc-900/60 overflow-hidden">
      <header className={`border-b border-zinc-800 px-4 py-3 border-t-2 ${accentClass}`}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider">{title}</h2>
          <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400 tabular-nums">
            {events.length}
          </span>
        </div>
        <p className="mt-0.5 text-xs text-zinc-500">{subtitle}</p>
      </header>
      <ul className="flex-1 divide-y divide-zinc-800/60 overflow-y-auto max-h-[65vh]">
        {events.length === 0 ? (
          <li className="px-4 py-8 text-center text-sm text-zinc-600">
            Aguardando eventos…
          </li>
        ) : (
          events.map((event) => (
            <li key={`${event.id}-${event.receivedAt}`} className="px-4 py-2.5 text-sm">
              {renderItem(event)}
            </li>
          ))
        )}
      </ul>
    </section>
  );
}
