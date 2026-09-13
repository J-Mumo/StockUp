import { create } from 'zustand';
import type { MetricDefinition } from '../lib/metrics/types';

const STORAGE_KEY = 'stockup.learn_mode';

// Learn Mode global state.
//
//  - `enabled` controls whether ⓘ icons are always visible and one-liners
//    render inline under metric labels. Persisted to localStorage.
//  - `activeMetric` is the metric currently opened in the LearnCard drawer.
//    `contextValue`, `contextLabel`, and `contextSector` let the card show
//    "this company's value" alongside the generic explanation.

interface LearnCardContext {
  metric: MetricDefinition;
  value?: number | null;
  contextLabel?: string;   // e.g. "KCB Group" or "Sector median"
  sector?: string | null;
}

interface LearnState {
  enabled: boolean;
  active: LearnCardContext | null;

  toggle: () => void;
  setEnabled: (v: boolean) => void;
  open: (ctx: LearnCardContext) => void;
  close: () => void;
}

function readInitial(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

export const useLearnStore = create<LearnState>((set, get) => ({
  enabled: readInitial(),
  active: null,

  toggle: () => {
    const next = !get().enabled;
    try { localStorage.setItem(STORAGE_KEY, next ? '1' : '0'); } catch { /* ignore */ }
    set({ enabled: next });
  },
  setEnabled: (v: boolean) => {
    try { localStorage.setItem(STORAGE_KEY, v ? '1' : '0'); } catch { /* ignore */ }
    set({ enabled: v });
  },
  open: (ctx: LearnCardContext) => set({ active: ctx }),
  close: () => set({ active: null }),
}));
