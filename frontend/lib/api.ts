const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

export interface RecoveryToday {
  date: string;
  score: number;
  hrv: number;
  rhr: number;
  skin_temp: number | null;
  skin_temp_baseline_28d?: number | null;
  skin_temp_delta?: number | null;
}

export interface RecoveryPoint {
  date: string;
  score: number;
  hrv: number;
  rhr: number;
}

export interface HRVPoint {
  date: string;
  hrv: number;
  avg: number;
  sd: number;
}

export interface SleepEntry {
  date: string;
  stages: string | null;
  spo2: number | null;
  rhr: number | null;
  hours: number | null;
}

export interface SleepTrendPoint {
  date: string;
  stages: string | null;
  hours: number | null;
}

export interface ReadinessToday {
  date: string;
  recovery_score: number;
  hrv: number;
  rhr: number;
  sleep_hours: number;
  energy: number | null;
  stress: number | null;
}

export interface OAuthStatus {
  source: string;
  last_sync_at: string;
  needs_reauth: boolean;
}

export interface StatsSummary {
  acwr: { acute: number | null; chronic: number | null; ratio: number | null };
  hrv: { today: number | null; baseline_28d: number | null; deviation_sigma: number | null };
  rhr: { baseline_28d: number | null; last_7_avg: number | null; elevated_pct: number | null };
  sleep: {
    consistency_stdev: number | null;
    avg_7d: number | null;
    debt_7d_hours: number | null;
  };
  recovery_trend_slope_7d: number;
  streaks: { recovery_above_60: number; sleep_above_7h: number };
  personal_bests: {
    best_hrv: { date: string; hrv: number } | null;
    lowest_rhr: { date: string; rhr: number } | null;
  };
}

export interface Insight {
  headline: string;
  body: string;
  polarity: "positive" | "neutral" | "negative";
}

export interface WeekDay {
  label: string;
  date: string;
  is_today: boolean;
  is_future: boolean;
  recovery: number | null;
  sleep_hours: number | null;
}

export interface PersonalBests {
  top_hrv: { date: string; value: number }[];
  lowest_rhr: { date: string; value: number }[];
  longest_sleep: { date: string; value: number }[];
}

export interface HeatmapDay {
  date: string;
  intensity: number;
  sets: number;
  volume_kg: number;
}

export interface WeeklyVolume {
  week: string;
  sets: number;
  volume_kg: number;
  sessions: number;
}

export interface PR {
  exercise: string;
  pr_lbs: number;
  pr_kg: number;
  pr_reps: number;
  pr_date: string;
  est_1rm_lbs: number;
  est_1rm_kg: number;
  last_performed: string;
}

export interface CardioSession {
  id: string;
  date: string;
  started_at: string | null;
  kind: string;
  strain: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  kcal: number | null;
  duration_min: number | null;
  source: string;
  rpe?: number | null;
}

export interface CardioRecent {
  days: number;
  sessions: CardioSession[];
  summary_28d: {
    kind: string;
    sessions: number;
    minutes: number;
    kcal: number;
    strain: number;
  }[];
}

export interface ExerciseLast {
  found: boolean;
  exercise: string;
  date?: string;
  weight_lbs?: number;
  weight_kg?: number;
  reps?: number;
  rpe?: number | null;
}

export interface Correlation {
  question: string;
  sample_days: number;
  avg_recovery_yes: number | null;
  avg_recovery_no: number | null;
  avg_hrv_yes: number | null;
  avg_hrv_no: number | null;
  hrv_delta: number | null;
}

export interface ClinicalOverview {
  conditions: { name: string; onset: string | null; status: string }[];
  medications: { name: string; dose: string | null; frequency: string | null; started: string | null }[];
  key_labs: { name: string; value: number; unit: string | null; collected_at: string | null }[];
}

export interface TopExercise {
  exercise: string;
  total_sets: number;
  total_volume_kg: number;
  pr_lbs: number;
  training_days: number;
  last_performed: string;
}

export interface OverloadSignal {
  overload_pct: number | null;
  prior_avg_kg: number;
  recent_avg_kg: number;
  trend: "progressing" | "maintaining" | "deloading" | "insufficient_data";
  recent_sessions_per_week: number | null;
}

export interface LastSession {
  date: string;
  days_ago: number;
  sets: number;
  exercises: number;
  volume_kg: number;
  exercise_list: string[];
  week_sets: number;
  week_volume_kg: number;
}

export interface WeightPoint {
  date: string;
  kg: number;
  lbs: number;
}

export interface VO2Point { date: string; vo2max: number }
export interface StepPoint { date: string; steps: number }
export interface RHRPoint { date: string; apple: number | null; whoop: number | null }

export interface Briefing {
  briefing_date: string;
  generated_at: string;
  training_call: "Push" | "Train" | "Maintain" | "Easy" | "Rest";
  training_rationale: string;
  readiness_headline: string;
  coaching_note: string;
  flags: string[];
  priority_metric: string;
  tokens: { input: number; output: number; cache_read: number };
  cost_usd: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface WarmupItem {
  name: string;
  sets?: number;
  reps?: number;
  duration_sec?: number;
  notes?: string;
}

export interface WorkoutExercise {
  name: string;
  sets: number;
  reps: string;
  weight_kg?: number;
  weight_lbs?: number;
  rpe_target: number;
  notes?: string;
}

export interface WorkoutBlock {
  label: string;
  exercises: WorkoutExercise[];
}

export interface WorkoutPlan {
  generated_at: string;
  source: "claude" | "claude_code" | "fallback" | string;
  readiness_tier: "green" | "yellow" | "red";
  readiness_summary: string;
  recommendation: {
    intensity: "high" | "moderate" | "low" | "rest";
    focus: string;
    rationale: string;
    estimated_duration_min: number;
    target_rpe: number;
  };
  warmup: WarmupItem[];
  blocks: WorkoutBlock[];
  cooldown: string;
  clinical_notes: string[];
  vault_insights: string[];
}

export const api = {
  recoveryToday: () => get<RecoveryToday>("/api/recovery/today"),
  recoveryTrend: (days = 14) => get<RecoveryPoint[]>(`/api/recovery/trend?days=${days}`),
  hrvTrend: (days = 28) => get<HRVPoint[]>(`/api/hrv/trend?days=${days}`),
  sleepRecent: (days = 7) => get<SleepEntry[]>(`/api/sleep/recent?days=${days}`),
  sleepTrend: (days = 30) => get<SleepTrendPoint[]>(`/api/sleep/trend?days=${days}`),
  readinessToday: () => get<ReadinessToday>("/api/readiness/today"),
  oauthStatus: () => get<OAuthStatus[]>("/api/oauth/status"),
  statsSummary: () => get<StatsSummary>("/api/stats/summary"),
  insights: () => get<Insight[]>("/api/insights"),
  weekSummary: () => get<WeekDay[]>("/api/week/summary"),
  personalBests: () => get<PersonalBests>("/api/personal-bests"),
  trainingLastSession: () => get<LastSession>("/api/training/last-session"),
  trainingTopExercises: (n = 10) => get<TopExercise[]>(`/api/training/top-exercises?n=${n}`),
  trainingOverloadSignal: () => get<OverloadSignal>("/api/training/overload-signal"),
  trainingHeatmap: (weeks = 52) => get<HeatmapDay[]>(`/api/training/heatmap?weeks=${weeks}`),
  trainingWeekly: (weeks = 16) => get<WeeklyVolume[]>(`/api/training/weekly?weeks=${weeks}`),
  trainingPRs: (n = 15) => get<PR[]>(`/api/training/prs?n=${n}`),
  insightsCorrelations: () => get<Correlation[]>("/api/insights/correlations"),
  clinicalOverview: () => get<ClinicalOverview>("/api/clinical/overview"),
  bodyTrend: () => get<WeightPoint[]>("/api/body/trend"),
  bodyVO2Max: () => get<VO2Point[]>("/api/body/vo2max"),
  bodySteps: (days = 90) => get<StepPoint[]>(`/api/body/steps?days=${days}`),
  bodyRHRTrend: (days = 90) => get<RHRPoint[]>(`/api/body/rhr-trend?days=${days}`),
  briefing: () => get<Briefing | Record<string, never>>("/api/briefing"),
  workoutNext: (regen = false) =>
    get<WorkoutPlan>(`/api/workout/next${regen ? "?regen=true" : ""}`),
  workoutGenerate: async () => {
    const r = await fetch(`${BASE}/api/workout/generate`, { method: "POST" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `workoutGenerate ${r.status}`);
    }
    return r.json() as Promise<WorkoutPlan>;
  },
  workoutContext: () => get<{ context: string }>("/api/workout/context"),
  workoutSubmit: async (plan: object) => {
    const r = await fetch(`${BASE}/api/workout/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan, source: "claude", push_to_hevy: false }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `workoutSubmit ${r.status}`);
    }
    return r.json();
  },
  workoutDelete: async () => {
    const r = await fetch(`${BASE}/api/workout/plan`, { method: "DELETE" });
    if (!r.ok) throw new Error(`workoutDelete ${r.status}`);
    return r.json() as Promise<{ status: string; date: string }>;
  },
  syncAll: async () => {
    const [whoop, hevy] = await Promise.allSettled([
      fetch(`${BASE}/api/whoop/sync`, { method: "POST" }).then((r) => r.json()),
      fetch(`${BASE}/api/hevy/sync`, { method: "POST" }).then((r) => r.json()),
    ]);
    return {
      whoop: whoop.status === "fulfilled" ? whoop.value : { error: String((whoop as PromiseRejectedResult).reason) },
      hevy: hevy.status === "fulfilled" ? hevy.value : { error: String((hevy as PromiseRejectedResult).reason) },
    };
  },
  hevyPushRoutine: async (regen = false) => {
    const r = await fetch(
      `${BASE}/api/hevy/push-routine${regen ? "?regen=true" : ""}`,
      { method: "POST" },
    );
    if (!r.ok) throw new Error(`hevyPushRoutine ${r.status}`);
    return r.json() as Promise<{
      ok: boolean;
      routine_id: string;
      plan_readiness_tier: string;
      plan_focus: string;
    }>;
  },
  trainingMuscleBalance: (weeks = 4) =>
    get<{
      weeks: number;
      total_sets: number;
      groups: {
        group: string;
        sets: number;
        volume_kg: number;
        share_pct: number;
        weekly_sets: number;
      }[];
    }>(`/api/training/muscle-balance?weeks=${weeks}`),
  cardioRecent: (days = 60) => get<CardioRecent>(`/api/cardio/recent?days=${days}`),
  cardioLog: async (body: {
    date?: string;
    modality: string;
    duration_min: number;
    avg_hr?: number | null;
    rpe?: number | null;
    notes?: string | null;
  }) => {
    const r = await fetch(`${BASE}/api/cardio/log`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`cardioLog ${r.status}`);
    return r.json() as Promise<{ status: string; id: string; date: string }>;
  },
  cardioDelete: async (id: string) => {
    const r = await fetch(`${BASE}/api/cardio/log/${id}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`cardioDelete ${r.status}`);
    return r.json();
  },
  trainingExerciseLast: (exercise: string) =>
    get<ExerciseLast>(
      `/api/training/exercise-last?exercise=${encodeURIComponent(exercise)}`,
    ),
  trainingProgression: (exercise: string, sessions = 20) =>
    get<{
      exercise: string;
      history: {
        date: string;
        exercise: string;
        work_sets: number;
        max_lbs: number;
        max_kg: number;
        total_reps: number;
        volume_kg: number;
        avg_rpe: number | null;
      }[];
    }>(
      `/api/training/progression?exercise=${encodeURIComponent(
        exercise,
      )}&sessions=${sessions}`,
    ),
};

export async function* streamChat(messages: ChatMessage[]): AsyncGenerator<string> {
  const res = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
  if (!res.ok || !res.body) throw new Error(`chat ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = JSON.parse(line.slice(6));
      if (payload.type === "text") yield payload.text as string;
      if (payload.type === "error") throw new Error(payload.text as string);
      if (payload.type === "done") return;
    }
  }
}
