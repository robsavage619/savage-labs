"use client";

import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, YAxis } from "recharts";

import { api } from "@/lib/api";
import { Eyebrow, Metric } from "@/components/ui/metric";

function proteinTone(perKg: number | null): "positive" | "neutral" | "negative" {
  if (perKg == null) return "neutral";
  if (perKg >= 1.6 && perKg <= 2.4) return "positive";
  if (perKg >= 1.2) return "neutral";
  return "negative";
}

function balanceTone(b: number | null): "positive" | "neutral" | "negative" {
  if (b == null) return "neutral";
  if (Math.abs(b) <= 250) return "positive";
  if (Math.abs(b) <= 600) return "neutral";
  return "negative";
}

export function FuelingPanel() {
  const today = useQuery({ queryKey: ["fueling-today"], queryFn: api.fuelingToday, refetchInterval: 5 * 60_000 });
  const trend = useQuery({ queryKey: ["fueling-trend", 14], queryFn: () => api.fuelingTrend(14), refetchInterval: 5 * 60_000 });

  const f = today.data;
  const hasDiet = f?.has_diet_data ?? false;
  const hasBodyComp = f?.has_body_comp_data ?? false;

  const balance = f?.kcal_balance ?? null;
  const balanceColor =
    balanceTone(balance) === "positive"
      ? "var(--positive)"
      : balanceTone(balance) === "negative"
      ? "var(--negative)"
      : "var(--text-primary)";

  const proteinColor =
    proteinTone(f?.protein_per_kg ?? null) === "positive"
      ? "var(--positive)"
      : proteinTone(f?.protein_per_kg ?? null) === "negative"
      ? "var(--negative)"
      : "var(--text-primary)";

  return (
    <div className="shc-card shc-enter p-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <Eyebrow>Fueling · today</Eyebrow>
        <div className="flex items-center gap-3 text-[10px] text-[var(--text-dim)] uppercase tracking-wider">
          <span>Diet · Apple Health</span>
          <span className="text-[var(--text-faint)]">·</span>
          <span>Body comp · smart scale</span>
        </div>
      </div>

      {/* Body composition strip */}
      <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4 pb-4 border-b border-[var(--hairline)]">
        <div>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Body weight</p>
          <Metric
            value={f?.body_mass_lbs != null ? f.body_mass_lbs.toFixed(1) : "—"}
            unit={f?.body_mass_lbs != null ? "lbs" : undefined}
            size="lg"
          />
        </div>
        <div>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Body fat</p>
          {f?.body_fat_pct != null ? (
            <>
              <Metric value={f.body_fat_pct.toFixed(1)} unit="%" size="lg" />
              <p className="text-[10px] text-[var(--text-faint)] tabular-nums mt-0.5">
                {f.body_fat_date}
              </p>
            </>
          ) : (
            <p className="text-[13px] text-[var(--text-dim)] mt-1">
              No reading
              <br />
              <span className="text-[10.5px] text-[var(--text-faint)]">
                Pair a smart scale to Apple Health
              </span>
            </p>
          )}
        </div>
        <div>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Lean mass</p>
          {f?.lean_body_mass_lbs != null ? (
            <>
              <Metric value={f.lean_body_mass_lbs.toFixed(1)} unit="lbs" size="lg" />
              <p className="text-[10px] text-[var(--text-faint)] tabular-nums mt-0.5">
                {f.lean_body_mass_date}
              </p>
            </>
          ) : f?.body_mass_lbs != null && f?.body_fat_pct != null ? (
            <Metric
              value={(f.body_mass_lbs * (1 - f.body_fat_pct / 100)).toFixed(1)}
              unit="lbs"
              size="lg"
            />
          ) : (
            <p className="text-[13px] text-[var(--text-dim)] mt-1">No reading</p>
          )}
        </div>
      </div>

      {/* Energy + macros */}
      {hasDiet ? (
        <div className="mt-4 grid grid-cols-2 md:grid-cols-5 gap-3">
          <div>
            <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">kcal in</p>
            <Metric value={f?.kcal_in != null ? Math.round(f.kcal_in).toString() : "—"} unit="kcal" size="md" />
          </div>
          <div>
            <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">kcal out</p>
            <Metric
              value={f?.kcal_tdee_today != null ? Math.round(f.kcal_tdee_today).toString() : "—"}
              unit="kcal"
              size="md"
            />
          </div>
          <div>
            <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Balance</p>
            <p className="text-[18px] font-medium tabular-nums" style={{ color: balanceColor }}>
              {balance == null ? "—" : balance > 0 ? `+${Math.round(balance)}` : Math.round(balance)}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Protein</p>
            <p className="text-[18px] font-medium tabular-nums text-[var(--text-primary)]">
              {f?.protein_g != null ? Math.round(f.protein_g) : "—"}
              <span className="text-[11px] text-[var(--text-muted)] ml-0.5">g</span>
            </p>
            {f?.protein_per_kg != null && (
              <p className="text-[10px] tabular-nums" style={{ color: proteinColor }}>
                {f.protein_per_kg.toFixed(2)} g/kg
                {f.protein_target_g && (
                  <span className="text-[var(--text-faint)] ml-1">/ {Math.round(f.protein_target_g)}g target</span>
                )}
              </p>
            )}
          </div>
          <div>
            <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Hydration</p>
            <p className="text-[18px] font-medium tabular-nums text-[var(--text-primary)]">
              {f?.water_oz != null ? f.water_oz.toFixed(0) : "—"}
              <span className="text-[11px] text-[var(--text-muted)] ml-0.5">oz</span>
            </p>
            {f?.sodium_mg != null && (
              <p className="text-[10px] text-[var(--text-faint)] tabular-nums">
                {Math.round(f.sodium_mg)}mg Na
              </p>
            )}
          </div>
        </div>
      ) : (
        <div className="mt-4 p-4 rounded-md border border-dashed border-[var(--hairline)] text-center">
          <p className="text-[13px] text-[var(--text-muted)]">No diet data logged today.</p>
          <p className="text-[11px] text-[var(--text-dim)] mt-1 leading-relaxed max-w-[520px] mx-auto">
            Connect MyFitnessPal, Cronometer, or Lose-It to Apple Health → Sources, then re-import the
            Apple Health export. Targets at this body weight: ~{f?.body_mass_kg ? Math.round(f.body_mass_kg * 1.8) : "190"}g protein
            (1.8 g/kg), ~{f?.body_mass_kg ? Math.round(f.body_mass_kg * 35) : "3700"}ml water, and TDEE
            balance ±250 kcal of training-day target.
          </p>
        </div>
      )}

      {/* 14-day balance chart (only if we have any data) */}
      {hasDiet && trend.data && trend.data.some((d) => d.balance != null) && (
        <div className="mt-5">
          <div className="flex items-baseline justify-between">
            <Eyebrow>Energy balance · 14 days</Eyebrow>
            <span className="text-[10.5px] text-[var(--text-dim)]">red = surplus · green = deficit</span>
          </div>
          <div className="mt-2 h-[80px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={trend.data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <YAxis hide domain={["auto", "auto"]} />
                <ReferenceLine y={0} stroke="var(--hairline)" />
                <Tooltip
                  contentStyle={{
                    background: "var(--panel)",
                    border: "1px solid var(--hairline)",
                    borderRadius: 6,
                    fontSize: 11,
                  }}
                  formatter={(v: number) => [v > 0 ? `+${v}` : v, "kcal"]}
                />
                <Bar dataKey="balance" radius={[2, 2, 0, 0]}>
                  {trend.data.map((d, i) => (
                    <Cell
                      key={i}
                      fill={
                        d.balance == null
                          ? "var(--text-faint)"
                          : d.balance > 0
                          ? "var(--negative)"
                          : "var(--positive)"
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <p className="mt-4 pt-3 text-[10.5px] text-[var(--text-dim)] leading-snug border-t border-[var(--hairline)]">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        Protein 1.6–2.2 g/kg supports hypertrophy; under 1.2 g/kg blunts MPS recovery
        (Morton 2018 meta). Energy balance ±250 kcal of TDEE preserves lean mass while losing fat
        (Helms et al, 2014). Body composition flows from a smart scale via Apple Health; diet flows from
        any Health-connected logger. {!hasBodyComp && "Add a smart scale to surface body fat % and lean mass."}
      </p>
    </div>
  );
}
