'use client';

/**
 * useSSE — abre um EventSource autenticado e escuta EVENTOS NOMEADOS.
 *
 * Pontos que este hook demonstra (ver docs/protocol.md e docs/anti-patterns.md):
 *
 * 1. Eventos com `event: log|alert|trade` NÃO chegam em `onmessage` —
 *    `onmessage` só recebe eventos sem nome. Cada tipo exige um
 *    `addEventListener` próprio.
 *
 * 2. O token do handshake é one-time-use: a reconexão automática do
 *    EventSource reutilizaria a mesma URL e levaria 401. Por isso o hook
 *    fecha a conexão no erro e refaz o handshake com um token novo.
 *
 * 3. Cleanup no unmount: fechar o EventSource e cancelar timers — o
 *    equivalente client-side do "sem zombie listeners" do gateway.
 */

import { useEffect, useRef, useState } from 'react';

export interface SSEEvent<T = unknown> {
  id: string;
  type: string;
  receivedAt: number;
  data: T;
}

export type ConnectionStatus = 'connecting' | 'open' | 'reconnecting';

const MAX_EVENTS_PER_TYPE = 50;
const RECONNECT_DELAY_MS = 3000;
const TOKEN_ENDPOINT = '/api/auth/sse-token';
const STREAM_ENDPOINT = '/api/events';

export function useSSE(eventTypes: readonly string[]) {
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const [eventsByType, setEventsByType] = useState<Record<string, SSEEvent[]>>(() =>
    Object.fromEntries(eventTypes.map((type) => [type, []])),
  );
  const sourceRef = useRef<EventSource | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Chave estável: reconectar só se a LISTA de tipos mudar, não a referência.
  const eventTypesKey = eventTypes.join(',');

  useEffect(() => {
    const types = eventTypesKey.split(',');
    let cancelled = false;

    const scheduleReconnect = () => {
      if (cancelled) return;
      setStatus('reconnecting');
      retryTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
    };

    async function connect() {
      try {
        // Handshake: token curto e one-time-use (ver SECURITY.md).
        const response = await fetch(TOKEN_ENDPOINT, { method: 'POST' });
        if (!response.ok) throw new Error(`handshake falhou: ${response.status}`);
        const { token } = (await response.json()) as { token: string };
        if (cancelled) return;

        const source = new EventSource(
          `${STREAM_ENDPOINT}?token=${encodeURIComponent(token)}`,
        );
        sourceRef.current = source;

        source.onopen = () => setStatus('open');

        for (const type of types) {
          source.addEventListener(type, (raw) => {
            const message = raw as MessageEvent<string>;
            let data: unknown;
            try {
              data = JSON.parse(message.data);
            } catch {
              // Payload malformado não pode derrubar o listener do tipo.
              return;
            }
            const record: SSEEvent = {
              id: message.lastEventId,
              type,
              receivedAt: Date.now(),
              data,
            };
            setEventsByType((previous) => ({
              ...previous,
              [type]: [record, ...previous[type]].slice(0, MAX_EVENTS_PER_TYPE),
            }));
          });
        }

        source.onerror = () => {
          // Não deixar o EventSource reconectar sozinho: o token já foi
          // consumido no handshake anterior. Fecha e recomeça do zero.
          source.close();
          scheduleReconnect();
        };
      } catch {
        scheduleReconnect();
      }
    }

    connect();

    return () => {
      cancelled = true;
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      sourceRef.current?.close();
    };
  }, [eventTypesKey]);

  return { status, eventsByType };
}
