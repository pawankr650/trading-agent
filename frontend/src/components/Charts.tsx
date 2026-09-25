import { useEffect, useRef } from "react";
import { createChart, LineStyle, type DeepPartial, type ChartOptions, type UTCTimestamp } from "lightweight-charts";
import type { Candle, Plan, Trade } from "../types";

function baseOptions(): DeepPartial<ChartOptions> {
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const grid = dark ? "#1f2937" : "#f3f4f6";
  return {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: dark ? "#9ca3af" : "#374151" },
    grid: { vertLines: { color: grid }, horzLines: { color: grid } },
    timeScale: { borderVisible: false },
    rightPriceScale: { borderVisible: false },
  };
}

const ts = (t: number) => t as UTCTimestamp;

/** Candles + 20/50/200 DMA + volume + trade-plan lines, with a synced RSI pane below. */
export function PriceChart({ candles, plan }: { candles: Candle[]; plan: Plan | null }) {
  const mainRef = useRef<HTMLDivElement>(null);
  const rsiRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mainRef.current || !rsiRef.current) return;
    const main = createChart(mainRef.current, baseOptions());
    const cs = main.addCandlestickSeries({
      upColor: "#16a34a", downColor: "#dc2626", wickUpColor: "#16a34a", wickDownColor: "#dc2626", borderVisible: false,
    });
    cs.setData(candles.map((b) => ({ time: ts(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
    ([["sma20", "#2563eb"], ["sma50", "#f59e0b"], ["sma200", "#7c3aed"]] as const).forEach(([k, color]) => {
      main.addLineSeries({ color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: k.toUpperCase() })
        .setData(candles.filter((b) => b[k] !== null).map((b) => ({ time: ts(b.t), value: b[k] as number })));
    });
    const vol = main.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false });
    main.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(candles.map((b) => ({ time: ts(b.t), value: b.v, color: b.c >= b.o ? "rgba(22,163,74,.35)" : "rgba(220,38,38,.35)" })));
    if (plan) {
      ([["entry", "#6b7280"], ["stop", "#dc2626"], ["target", "#16a34a"]] as const).forEach(([k, color]) =>
        cs.createPriceLine({ price: plan[k], color, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: k }));
    }

    const rsi = createChart(rsiRef.current, baseOptions());
    const rs = rsi.addLineSeries({ color: "#0ea5e9", lineWidth: 1, title: "RSI" });
    rs.setData(candles.filter((b) => b.rsi !== null).map((b) => ({ time: ts(b.t), value: b.rsi as number })));
    rs.createPriceLine({ price: 70, color: "#dc2626", lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: "" });
    rs.createPriceLine({ price: 30, color: "#16a34a", lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: "" });

    main.timeScale().fitContent();
    rsi.timeScale().fitContent();
    const sync = (r: { from: number; to: number } | null) => r && rsi.timeScale().setVisibleLogicalRange(r);
    main.timeScale().subscribeVisibleLogicalRangeChange(sync);
    return () => { main.remove(); rsi.remove(); };
  }, [candles, plan]);

  return (
    <>
      <div ref={mainRef} className="chart" style={{ marginTop: ".5rem" }} />
      <div ref={rsiRef} className="chart rsi" />
    </>
  );
}

/** Cumulative realised P&L of closed trades. */
export function EquityCurve({ trades }: { trades: Trade[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !trades.length) return;
    const chart = createChart(ref.current, baseOptions());
    let cum = 0, last = 0;
    const pts = trades.map((t) => {
      cum += t.pnl ?? 0;
      let time = Math.floor(new Date(t.closed_at ?? t.opened_at).getTime() / 1000);
      if (time <= last) time = last + 1; // chart needs strictly increasing times
      last = time;
      return { time: ts(time), value: cum };
    });
    chart.addAreaSeries({ lineColor: "#2563eb", topColor: "rgba(37,99,235,.3)", bottomColor: "rgba(37,99,235,0)" }).setData(pts);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [trades]);
  return <div ref={ref} className="chart small" />;
}
