export const EVENT_LABEL: Record<string, string> = {
  order_win: "Order win / contract", results: "Financial results", mna: "M&A / stake deal",
  regulatory: "Regulatory / legal", fund_raise: "Fund raising", rating: "Rating / broker call",
  dividend_bonus_split: "Dividend / bonus / split / buyback", capacity_expansion: "Capex / expansion",
  guidance: "Guidance", management: "Management change", market: "Market / macro", other: "Other",
};

type N = number | null | undefined;

export const num = (v: N, d = 2): string =>
  v === null || v === undefined || Number.isNaN(v)
    ? "–"
    : v.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });

export const pct = (v: N): string => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(1)}%`);

export const crore = (v: N): string => (v ? `₹${num(v / 1e7, 0)} Cr` : "–");

export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (Number.isNaN(m)) return "";
  if (m < 60) return `${Math.max(m, 0)}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

/** Only allow http(s) links from news feeds into href. */
export const safeUrl = (u: string | undefined): string | undefined => (u && /^https?:\/\//i.test(u) ? u : undefined);
