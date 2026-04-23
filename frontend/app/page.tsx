import { CommandBriefing } from "@/components/command-briefing";
import { PillarRecovery } from "@/components/pillar-recovery";
import { PillarSleep } from "@/components/pillar-sleep";
import { PillarTrainingLoad } from "@/components/pillar-training-load";
import { PillarReadiness } from "@/components/pillar-readiness";
import { StrengthPanel } from "@/components/strength-panel";
import { TrendIntelligence } from "@/components/trend-intelligence";
import { RightRail } from "@/components/right-rail";
import { AdvisorChat } from "@/components/advisor-chat";
import { SyncStatus } from "@/components/sync-status";

export default function Dashboard() {
  const now = new Date();
  const dayLabel = now.toLocaleDateString("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
  const timeLabel = now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

  return (
    <main className="min-h-screen px-5 pb-20 pt-6 max-w-[1600px] mx-auto">
      <header className="flex items-baseline justify-between pb-4 border-b border-[var(--hairline)] mb-5">
        <div className="flex items-baseline gap-3">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--positive)] animate-pulse" />
          <h1 className="text-[11px] font-medium tracking-[0.2em] uppercase text-[var(--text-muted)]">
            Savage Health Center
          </h1>
          <span className="text-[10.5px] text-[var(--text-faint)] tabular-nums">v2 · personal</span>
        </div>
        <div className="text-[11px] text-[var(--text-dim)] tabular-nums flex gap-3">
          <span>{dayLabel}</span>
          <span className="text-[var(--text-faint)]">·</span>
          <span>{timeLabel}</span>
        </div>
      </header>

      <div className="mb-4">
        <SyncStatus />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4 min-w-0">
          <CommandBriefing />

          <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <PillarRecovery />
            <PillarSleep />
            <PillarTrainingLoad />
            <PillarReadiness />
          </section>

          <StrengthPanel />

          <TrendIntelligence />
        </div>

        <div className="hidden xl:block">
          <RightRail />
        </div>
      </div>

      <div className="xl:hidden mt-4">
        <RightRail />
      </div>

      <AdvisorChat />
    </main>
  );
}
