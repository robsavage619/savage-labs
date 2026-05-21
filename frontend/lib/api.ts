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
  hrv_7d_avg?: number | null;
  hrv_7d_sd?: number | null;
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

export interface MomentumWeek {
  recovery_avg: number | null;
  sleep_avg_h: number | null;
  sessions: number;
}

export interface MomentumData {
  this_week: MomentumWeek;
  last_week: MomentumWeek;
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

export interface LabPoint {
  value: number;
  unit: string | null;
  ref_low: number | null;
  ref_high: number | null;
  collected_at: string | null;
  flag: "L" | "H" | null;
}

export interface ClinicalOverview {
  conditions: { name: string; onset: string | null; status: string; icd10: string | null }[];
  medications: {
    name: string;
    dose: string | null;
    frequency: string | null;
    started: string | null;
    stopped: string | null;
  }[];
  key_labs: (LabPoint & { name: string; loinc: string | null })[];
  lab_history: Record<string, LabPoint[]>;
  panels: LabPanel[];
  vitals: { metric: string; value: number; unit: string | null; ts: string | null }[];
}

export interface LabPanelResult {
  name: string;
  value: number | null;
  value_text: string | null;
  display: string;
  unit: string | null;
  ref_low: number | null;
  ref_high: number | null;
  ref_text: string | null;
  is_abnormal: boolean;
  loinc: string | null;
}

export interface LabPanel {
  panel: string;
  collected_at: string | null;
  results: LabPanelResult[];
}

export type RiskZone =
  | "normal" | "optimal" | "near_optimal"
  | "elevated" | "borderline" | "overweight" | "prediabetic"
  | "stage1" | "high"
  | "stage2" | "very_high" | "obese" | "diabetic"
  | "underweight";

export interface ClinicalRisk {
  cardiometabolic: {
    key: "bp" | "bmi" | "ldl" | "a1c";
    label: string;
    value: string;
    unit: string;
    ts: string;
    zone: RiskZone;
  }[];
  overdue_labs: {
    name: string;
    last_value: number;
    last_date: string;
    days_overdue: number;
    interval_months: number;
    months_since: number;
  }[];
  med_advisories: {
    med: string;
    severity: "warning" | "info";
    text: string;
  }[];
  onset_windows: {
    med: string;
    days_since_start: number;
    full_effect_days: number;
    phase: "onset" | "active" | "established";
  }[];
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
  source: "apple_health" | "checkin";
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

// ── DailyState — single source of truth from /api/state/today ────────────────

export interface DailyStateRecovery {
  score: number | null;
  score_date: string | null;
  hrv_ms: number | null;
  hrv_baseline_28d: number | null;
  hrv_sd_28d: number | null;
  hrv_sigma: number | null;
  rhr: number | null;
  rhr_7d_avg: number | null;
  rhr_baseline_28d: number | null;
  rhr_elevated_pct: number | null;
  skin_temp: number | null;
  skin_temp_baseline_28d: number | null;
  skin_temp_delta: number | null;
  spo2_pct: number | null;
  user_calibrating: boolean | null;
  respiratory_rate_baseline_28d: number | null;
  respiratory_rate_delta: number | null;
}

export interface DailyStateSleep {
  last_hours: number | null;
  avg_7d: number | null;
  consistency_stdev_7d: number | null;
  debt_7d_h: number | null;
  deep_pct_last: number | null;
  deep_min_last: number | null;
  rem_min_last: number | null;
  light_min_last: number | null;
  awake_min_last: number | null;
  rem_pct_last: number | null;
  efficiency_pct_last: number | null;
  consistency_pct_last: number | null;
  performance_pct_last: number | null;
  disturbance_count_last: number | null;
  sleep_cycle_count_last: number | null;
  in_bed_min_last: number | null;
  no_data_min_last: number | null;
  sleep_needed_min_last: number | null;
  sleep_need_baseline_min_last: number | null;
  sleep_need_debt_min_last: number | null;
  sleep_need_strain_min_last: number | null;
  sleep_need_nap_min_last: number | null;
  respiratory_rate_last: number | null;
  midpoint_local_h_last: number | null;
  midpoint_stdev_h_7d: number | null;
  spo2_avg_last: number | null;
  score: number | null;
}

export interface DailyStateLoad {
  acute_load_7d: number | null;
  chronic_load_28d: number | null;
  acwr: number | null;
  last_session_date: string | null;
  days_since_last: number | null;
  days_since_legs: number;
  days_since_push: number;
  days_since_pull: number;
  push_pull_ratio_28d: number | null;
  push_sets_28d: number;
  pull_sets_28d: number;
  legs_sets_28d: number;
  cardio_min_28d: number;
  cardio_z2_min_7d: number;
  cardio_zone_min_7d: Record<string, number>;
  max_hr_measured: number | null;
  max_hr_tanaka: number | null;
  pickleball_min_7d: number;
  pickleball_min_28d: number;
  cardio_modality_min_7d: Record<string, number>;
}

export interface DailyStateCheckin {
  date: string | null;
  propranolol_taken: boolean | null;
  body_weight_kg: number | null;
  body_weight_trend_4wk: number | null;
  soreness_overall: number | null;
  sleep_quality: number | null;
  energy: number | null;
  stress: number | null;
  motivation: number | null;
  illness_flag: boolean;
  travel_flag: boolean;
  muscle_soreness?: Record<string, number>;
}

export interface DailyStateReadiness {
  score: number | null;
  tier: "green" | "yellow" | "red" | null;
  weights: { hrv: number; sleep: number; rhr: number; subj: number };
  components: {
    hrv: number | null;
    sleep: number | null;
    rhr: number | null;
    subj: number | null;
  };
  beta_blocker_adjusted: boolean;
}

export interface DailyStateGates {
  max_intensity: "high" | "moderate" | "low" | "rest";
  forbid_muscle_groups: string[];
  deload_required: boolean;
  deload_reason: string | null;
  hr_zone_shift_bpm: number;
  kcal_multiplier: number;
  e1rm_regression_4wk_pct: number | null;
  reasons: string[];
}

export interface DailyStateFreshness {
  whoop_age_days: number | null;
  sleep_age_days: number | null;
  hevy_age_days: number | null;
  cardio_age_days: number | null;
  gaps: string[];
}

export interface DailyState {
  as_of: string;
  recovery: DailyStateRecovery;
  sleep: DailyStateSleep;
  training_load: DailyStateLoad;
  checkin: DailyStateCheckin;
  readiness: DailyStateReadiness;
  gates: DailyStateGates;
  freshness: DailyStateFreshness;
}

export interface CheckinPayload {
  propranolol_taken?: boolean | null;
  body_weight_kg?: number | null;
  soreness_overall?: number | null;
  sleep_quality_1_10?: number | null;
  energy_1_10?: number | null;
  stress_1_10?: number | null;
  motivation_1_10?: number | null;
  illness_flag?: boolean | null;
  travel_flag?: boolean | null;
  notes?: string | null;
  muscle_soreness?: Record<string, number> | null;
}

export interface CheckinToday extends CheckinPayload {
  date: string;
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
  rest_seconds?: number;
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
  momentum: () => get<MomentumData>("/api/momentum"),
  trainingLastSession: () => get<LastSession>("/api/training/last-session"),
  trainingTopExercises: (n = 10) => get<TopExercise[]>(`/api/training/top-exercises?n=${n}`),
  trainingOverloadSignal: () => get<OverloadSignal>("/api/training/overload-signal"),
  trainingHeatmap: (weeks = 52) => get<HeatmapDay[]>(`/api/training/heatmap?weeks=${weeks}`),
  trainingWeekly: (weeks = 16) => get<WeeklyVolume[]>(`/api/training/weekly?weeks=${weeks}`),
  trainingPRs: (n = 15) => get<PR[]>(`/api/training/prs?n=${n}`),
  insightsCorrelations: () => get<Correlation[]>("/api/insights/correlations"),
  clinicalOverview: () => get<ClinicalOverview>("/api/clinical/overview"),
  clinicalRisk: () => get<ClinicalRisk>("/api/clinical/risk"),
  bodyTrend: () => get<WeightPoint[]>("/api/body/trend"),
  bodyVO2Max: () => get<VO2Point[]>("/api/body/vo2max"),
  bodySteps: (days = 90) => get<StepPoint[]>(`/api/body/steps?days=${days}`),
  bodyRHRTrend: (days = 90) => get<RHRPoint[]>(`/api/body/rhr-trend?days=${days}`),
  briefing: () => get<Briefing | Record<string, never>>("/api/briefing"),
  workoutNext: (regen = false) =>
    get<WorkoutPlan>(`/api/workout/next${regen ? "?regen=true" : ""}`),
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
      fetch(`${BASE}/auth/whoop/sync`, { method: "POST" }).then((r) => r.json()),
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
  dailyState: () => get<DailyState>("/api/state/today"),
  checkinToday: () => get<CheckinToday>("/api/checkin/today"),
  checkinSubmit: async (body: CheckinPayload) => {
    const r = await fetch(`${BASE}/api/checkin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `checkinSubmit ${r.status}`);
    }
    return r.json() as Promise<{ status: string; date: string }>;
  },
  adherenceRecompute: async () => {
    const r = await fetch(`${BASE}/api/training/adherence/recompute`, { method: "POST" });
    if (!r.ok) throw new Error(`adherenceRecompute ${r.status}`);
    return r.json();
  },
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
  whoopPatterns: () =>
    get<{
      by_day_of_week: { day: string; avg_recovery: number; n: number }[];
      distribution: { bucket: string; n: number }[];
      sleep_vs_recovery: {
        date: string;
        recovery: number;
        hrv: number | null;
        rhr: number | null;
        sleep_h: number | null;
      }[];
      trend_90d: { date: string; recovery: number; hrv: number | null; rhr: number | null }[];
    }>("/api/whoop/patterns"),
  mesocycle: () =>
    get<{
      id: string;
      started_on: string;
      planned_weeks: number;
      status: string;
      week_number: number;
      weeks_remaining: number;
      is_deload_week: boolean;
      deload_trigger: string | null;
      notes: string | null;
      volume_targets: Record<string, { mev: number; mav: number; mrv: number }>;
    }>("/api/training/mesocycle"),
  clinicalResearch: () =>
    get<{
      as_of: string;
      sleep_regularity_index: { value: number | null; interpretation: string | null; ref: string };
      ln_rmssd: { today: number | null; avg_4w: number | null; delta: number | null; cv_pct_7d: number | null; ref: string };
      recovery_deficit_streak: { consecutive_red_days: number; alarm: boolean; ref: string };
      allostatic_load: {
        score_0_10: number | null;
        components: Record<string, number>;
        n_markers: number;
        interpretation: string | null;
        ref: string;
      };
      hrv_drug_adjusted: {
        raw: number | null;
        adjusted: number | null;
        factor: number;
        active_drugs: string[];
        ref: string;
      };
      z2_hr_consistency: { cv_pct: number | null; interpretation: string | null; ref: string };
    }>("/api/clinical-research/insights"),
  labFindings: () =>
    get<{
      id: string;
      title: string;
      hypothesis: string;
      vault_ref: string | null;
      test_type: string;
      run_at: string | null;
      n: number | null;
      effect_size: number | null;
      effect_unit: string | null;
      p_value: number | null;
      verdict: "confirmed" | "refuted" | "insufficient" | "inconclusive" | null;
      summary: string | null;
    }[]>("/api/lab/findings"),
  labRun: async () => {
    const r = await fetch(`${BASE}/api/lab/run`, { method: "POST" });
    if (!r.ok) throw new Error(`labRun ${r.status}`);
    return r.json() as Promise<{ ran: number; verdicts: Record<string, string>; completed_at: string }>;
  },
  afterAction: () =>
    get<{
      as_of: string;
      session_date: string | null;
      days_ago?: number;
      has_plan: boolean;
      exercises: {
        exercise: string;
        block: string | null;
        sets: number;
        avg_reps: number | null;
        min_reps: number | null;
        target_reps: number | null;
        actual_weight_lbs: number | null;
        target_weight_lbs: number | null;
        avg_rpe: number | null;
        target_rpe: number | null;
        delta_pct: number;
        next_session_lbs: number | null;
        verdict: "drop" | "progress" | "repeat" | "no_plan_target";
        reason: string;
      }[];
    }>("/api/training/after-action"),
  fuelingToday: () =>
    get<{
      as_of: string;
      body_mass_kg: number | null;
      body_mass_lbs: number | null;
      body_fat_pct: number | null;
      body_fat_date: string | null;
      lean_body_mass_kg: number | null;
      lean_body_mass_lbs: number | null;
      lean_body_mass_date: string | null;
      kcal_in: number | null;
      kcal_active_out: number | null;
      kcal_basal_out: number | null;
      kcal_tdee_today: number | null;
      kcal_balance: number | null;
      protein_g: number | null;
      protein_per_kg: number | null;
      protein_target_g: number | null;
      carbs_g: number | null;
      fat_g: number | null;
      fiber_g: number | null;
      sugar_g: number | null;
      water_ml: number | null;
      water_oz: number | null;
      sodium_mg: number | null;
      caffeine_mg: number | null;
      has_diet_data: boolean;
      has_body_comp_data: boolean;
    }>("/api/fueling/today"),
  fuelingTrend: (days = 14) =>
    get<{
      date: string;
      kcal_in: number | null;
      kcal_out: number | null;
      balance: number | null;
      protein_g: number | null;
      protein_per_kg: number | null;
    }[]>(`/api/fueling/trend?days=${days}`),
  loadCurve: (days = 90) =>
    get<{
      as_of: string;
      points: { date: string; load: number; ctl: number; atl: number; tsb: number }[];
      today: { date: string; load: number; ctl: number; atl: number; tsb: number } | null;
      tau: { ctl_days: number; atl_days: number };
    }>(`/api/training/load-curve?days=${days}`),
  muscleVolume: () =>
    get<{
      as_of: string;
      week_start: string;
      mesocycle_id: string;
      muscles: {
        muscle: string;
        weekly_sets: number;
        mev: number | null;
        mav: number | null;
        mrv: number | null;
      }[];
      unmapped_exercises: string[];
    }>("/api/training/muscle-volume"),
  pickleballTrend: (days = 90) =>
    get<{
      as_of: string;
      sessions: {
        date: string;
        duration_min: number | null;
        avg_hr: number | null;
        rpe: number | null;
        recovery_day_of: number | null;
        hrv_day_of: number | null;
        hrv_next_day: number | null;
        hrv_delta: number | null;
      }[];
      tournaments: {
        id: string;
        date: string;
        name: string;
        format: string;
        dupr_before: number | null;
        dupr_after: number | null;
        dupr_delta: number | null;
        result_notes: string | null;
      }[];
      hrv_baseline: number | null;
      avg_recovery_on_play_days: number | null;
      total_sessions: number;
      total_duration_min: number;
    }>(`/api/pickleball/trend?days=${days}`),
  pickleballDupr: () =>
    get<{
      as_of: string;
      snapshots: { date: string; doubles: number | null; singles: number | null; doubles_provisional: boolean | null }[];
      current: { date: string; doubles: number | null; singles: number | null; doubles_provisional: boolean | null } | null;
      baseline_doubles: number | null;
      target_doubles: number;
      last_sync_at: string | null;
      needs_reauth: boolean;
    }>("/api/pickleball/dupr"),
  pickleballMatches: () =>
    get<{
      matches: {
        match_id: number;
        event_date: string;
        event_name: string | null;
        venue: string | null;
        format: string;
        partner_name: string | null;
        opponent1_name: string | null;
        opponent2_name: string | null;
        won: boolean;
        games: ({ us: number; them: number } | null)[];
        dupr_pre: number | null;
        dupr_post: number | null;
        dupr_delta: number | null;
        recovery_score: number | null;
        hrv_ms: number | null;
        rhr_bpm: number | null;
      }[];
      total: number;
    }>("/api/pickleball/matches"),
  trainingProgressionAll: (weeks = 8) =>
    get<{
      exercises: {
        exercise: string;
        e1rm_lbs: number | null;
        work_sets: number;
        perf_score: number | null;
        trend: string | null;
        recommendation: string;
      }[];
      as_of: string;
    }>(`/api/training/progression/all?weeks=${weeks}`),
};
