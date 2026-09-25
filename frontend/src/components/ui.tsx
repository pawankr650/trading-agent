import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { num } from "../format";

export function Badge({ value }: { value: string }) {
  return <span className={`badge b-${value}`}>{value}</span>;
}

export function Signed({ v, d = 2, suffix = "" }: { v: number | null | undefined; d?: number; suffix?: string }) {
  if (v === null || v === undefined) return <>–</>;
  return <span className={v >= 0 ? "pos" : "neg"}>{v >= 0 ? "+" : ""}{num(v, d)}{suffix}</span>;
}

export function ScoreBar({ v }: { v: number }) {
  const w = Math.min(50, Math.abs(v) * 50);
  return (
    <>
      <span className="bar">
        <i style={{ left: `${v >= 0 ? 50 : 50 - w}%`, width: `${w}%`, background: `var(${v >= 0 ? "--buy" : "--sell"})` }} />
      </span>{" "}
      <Signed v={v} />
    </>
  );
}

export function Kpi({ label, children }: { label: string; children: ReactNode }) {
  return <div className="card"><div className="k">{label}</div><div className="v">{children}</div></div>;
}

export const Spin = () => <span className="spin" />;

export function Loading({ text = "Loading…" }: { text?: string }) {
  return <div className="empty"><Spin /> {text}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Panel({ title, extra, children }: { title?: ReactNode; extra?: ReactNode; children: ReactNode }) {
  return (
    <div className="panel">
      {(title || extra) && <div className="panel-h">{title && <h2>{title}</h2>}{extra}</div>}
      {children}
    </div>
  );
}

/* ── toast ─────────────────────────────────────────────── */
const ToastCtx = createContext<(msg: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState("");
  const timer = useRef<number | undefined>(undefined);
  const show = useCallback((m: string) => {
    setMsg(m);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMsg(""), 3500);
  }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      <div id="toast" className={msg ? "show" : ""} role="status">{msg}</div>
    </ToastCtx.Provider>
  );
}

/* ── data hook ─────────────────────────────────────────── */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fn().then((d) => alive && setData(d))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}
