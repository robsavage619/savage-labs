// Types and fetchers for the research team routes (/api/research/team and friends).

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

export type ResearcherKey = "hypertrophy" | "recovery" | "conditioning" | "metabolic";
export type LeadStatus = "open" | "chasing" | "parked" | "closed";

export interface Lead {
  lead: string;
  why: string;
  priority: 1 | 2 | 3 | 4 | 5;
  status: LeadStatus;
  opened: string;
}

export interface Agenda {
  interests: string;
  open_leads: Lead[];
  hunches: string;
  next_steps: string;
  updated_at: string;
}

export interface TeamMember {
  researcher: ResearcherKey;
  name: string;
  field: string;
  curiosity: string;
  agenda: Agenda | null;
  last_activity: { at: string; kind: string; title: string; entries: number } | null;
}

export interface CustomFeature {
  name: string;
  owner: ResearcherKey;
  description: string;
  unit: string;
  timing: "morning" | "day";
  goal: string | null;
  sql: string;
  status: "proposed" | "approved" | "rejected";
  review_reason: string | null;
  created_at: string;
}

export const teamApi = {
  team: () => get<TeamMember[]>("/api/research/team"),
  customFeatures: () => get<CustomFeature[]>("/api/research/custom-features"),
};
