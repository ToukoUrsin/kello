import { useCallback, useEffect, useRef, useState } from "react";

/** The six acts of one run. Lengths in milliseconds; together about a minute. */
export const ACTS = [
  { id: "gap", label: "The gap", ms: 8000 },
  { id: "where", label: "Where they are lost", ms: 10000 },
  { id: "plan", label: "The plan", ms: 10000 },
  { id: "check", label: "The check", ms: 17500 },
  { id: "evidence", label: "The evidence", ms: 8000 },
  { id: "sim", label: "The simulation", ms: 12000 },
] as const;
export const LAST = ACTS.length - 1;

/** When things happen inside each act (ms from the start of the act). One place, so the picture is the same every run. */
export const T = {
  gap: { fillEnd: 2600, dotsFrom: 2800, dotsEnd: 5400, headline: 5400 },
  where: { places: 900, line: 1900, lineLabel: 2700, step: [3300, 4100, 4900, 5700], split: 6500 },
  plan: { first: 700, every: 1150, range: 8200 },
  check: { query0: 300, queryEvery: 600, page0: 2900, pageEvery: 2600, quoteAfter: 900, verdict: 8200, advice: 8900, rest0: 9800, restEvery: 600, restSpan: 2600, narrowAfter: 0 },
  evidence: { quote: 900, fly: 2600, value: 3500, range: 4300, kind: 5100 },
  sim: { year0: 400, yearEvery: 2700, ask: 9000 },
};

export interface Clock { act: number; t: number; playing: boolean; started: boolean; done: boolean }
export interface Run extends Clock { play: () => void; pause: () => void; toggle: () => void; jump: (act: number, at?: number, play?: boolean) => void; next: () => void; prev: () => void; replay: () => void; hold: (on: boolean) => void }

/** The clock of a run. It publishes time in tenths of a second: everything on screen is a step that CSS eases into. */
export function useRun(initial?: Partial<Clock>): Run {
  const [c, setC] = useState<Clock>(() => ({ act: 0, t: ACTS[0].ms, playing: false, started: false, done: false, ...initial }));
  // One writer: `now` always holds the latest clock, also between a change and the render that follows it.
  const now = useRef(c);
  const exact = useRef(c.t);
  const held = useRef(false);
  const commit = useCallback((next: Clock) => { now.current = next; setC(next); }, []);
  useEffect(() => {
    if (!c.playing) return;
    let raf = 0, last = performance.now();
    const tick = (ts: number) => {
      const dt = Math.min(100, ts - last); last = ts;
      const cur = now.current;
      if (!cur.playing) return;
      if (!held.current) exact.current += dt;
      const len = ACTS[cur.act].ms;
      if (exact.current >= len) {
        if (cur.act < LAST) { exact.current = 0; commit({ ...cur, act: cur.act + 1, t: 0 }); }
        else { exact.current = len; commit({ ...cur, t: len, playing: false, done: true }); return; }
      } else {
        const q = Math.floor(exact.current / 100) * 100;
        if (q !== cur.t) commit({ ...cur, t: q });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [c.playing, commit]);
  const set = useCallback((act: number, at: number, playing: boolean, done = false) => {
    const a = Math.max(0, Math.min(LAST, act)), t = Math.max(0, Math.min(ACTS[a].ms, at));
    exact.current = t;
    commit({ act: a, t: Math.floor(t / 100) * 100, playing, started: true, done });
  }, [commit]);
  const jump = useCallback((act: number, at = 0, play = true) => set(act, at, play), [set]);
  const play = useCallback(() => { const cur = now.current; if (!cur.started || cur.done) set(0, 0, true); else commit({ ...cur, playing: true }); }, [set, commit]);
  const pause = useCallback(() => commit({ ...now.current, playing: false }), [commit]);
  const toggle = useCallback(() => (now.current.playing ? pause() : play()), [pause, play]);
  const next = useCallback(() => { const cur = now.current; if (!cur.started) set(0, 0, true); else if (cur.act < LAST) set(cur.act + 1, 0, true); else set(LAST, ACTS[LAST].ms, false, true); }, [set]);
  const prev = useCallback(() => { const cur = now.current; set(!cur.started || cur.t > 1500 || cur.act === 0 ? cur.act : cur.act - 1, 0, true); }, [set]);
  const replay = useCallback(() => set(0, 0, true), [set]);
  /** While something outside the clock is running (a live check), the act waits. */
  const hold = useCallback((on: boolean) => { held.current = on; }, []);
  return { ...c, play, pause, toggle, jump, next, prev, replay, hold };
}

/** Has this moment of the run been reached? Earlier acts are always complete, later ones have not begun. */
export const reached = (c: { act: number; t: number }, act: number, at: number) => c.act > act || (c.act === act && c.t >= at);
/** How many of a series of evenly spaced moments have passed. */
export const countAt = (c: { act: number; t: number }, act: number, from: number, every: number, n: number) =>
  c.act > act ? n : c.act < act ? 0 : Math.max(0, Math.min(n, Math.floor((c.t - from) / every) + 1));

export function useReducedMotion(): boolean {
  const [r, setR] = useState(() => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const m = matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setR(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return r;
}

/** How far a stretch of an act has got, 0 to 1. */
export const progress = (c: { act: number; t: number }, act: number, from: number, to: number) =>
  c.act > act ? 1 : c.act < act ? 0 : Math.max(0, Math.min(1, (c.t - from) / Math.max(1, to - from)));

/** A number that counts to its value instead of jumping there. Ends exactly on the value. */
export function useTween(value: number, ms = 600, still = false): number {
  const [v, setV] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    if (still || from.current === value) { from.current = value; setV(value); return; }
    const a = from.current, t0 = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - p, 3);
      const x = a + (value - a) * e;
      from.current = x; setV(p >= 1 ? value : x);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, ms, still]);
  return v;
}
