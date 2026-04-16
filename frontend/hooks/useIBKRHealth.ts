'use client';

import { useEffect, useState } from 'react';

import { publicEnv } from '@/lib/env';

export type IBKRStatus = 'connected' | 'disconnected' | 'error' | 'disabled' | 'unknown';

export interface IBKRHealth {
  status: IBKRStatus;
  lastHeartbeat: string | null;
  accountId: string | null;
  errorMessage: string | null;
}

const POLL_INTERVAL_MS = 30_000;

const INITIAL_STATE: IBKRHealth = {
  status: 'unknown',
  lastHeartbeat: null,
  accountId: null,
  errorMessage: null,
};

export function useIBKRHealth(): IBKRHealth {
  const [health, setHealth] = useState<IBKRHealth>(INITIAL_STATE);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      const url = `${publicEnv.apiUrl}/api/v1/health/ibkr`;
      try {
        const res = await fetch(url, { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) {
          setHealth({
            status: data.status as IBKRStatus,
            lastHeartbeat: data.last_heartbeat ?? null,
            accountId: data.account_id ?? null,
            errorMessage: data.error_message ?? null,
          });
        }
      } catch (err) {
        if (!cancelled) {
          setHealth({
            status: 'error',
            lastHeartbeat: null,
            accountId: null,
            errorMessage: err instanceof Error ? err.message : 'Errore sconosciuto',
          });
        }
      }
    }

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return health;
}
