# Changelog

All notable changes to this project. Dates are commit dates (Pacific time).

---

## [Unreleased]

_In-progress work on the current branch._

---

## 2026-04-22

### Fixed

- **StrengthPanel null guards** (`41b91da`) — Guard `volume_kg` and `total_sets` fields against null before rendering; prevents chart crash when no training data is present for the selected window.

### Added

- **V2 dashboard + AI next-workout coach** (`01ad062`) — Full V2 dashboard layout with all five zones wired: Command Briefing strip, four Pillars (Recovery, Sleep, Training Load, Readiness), Trend Intelligence tabs, Right Rail, and AI Advisor chat sheet (Cmd+K). Next-workout endpoint calls Claude Sonnet 4.6 with clinical context and caches the response.

- **AI-powered next workout tab** (`94cce6b`) — Initial `next-workout.tsx` component with readiness-tier display (green/yellow/red), exercise blocks, RPE targets, warmup/cooldown sections, and clinical disclaimer notes.

---

## 2026-04-21

### Added

- **Real training, insights, and clinical data** (`9f23a8e`) — Wired production data into the dashboard: training heatmap, weekly volume, PRs, overload signal, correlation insights, clinical overview (meds, conditions, labs), and body-weight trend. All backed by live DuckDB queries.

- **Session-token auth layer** (`010bc73`) — Local PHI protection: dashboard requires a session token issued at startup. Prevents casual access to health data on shared machines.

- **P1 baseline snapshot** (`b858655`) — Committed working P1 state as the v2 baseline. Three-card layout: recovery ring, HRV trend, sleep stacked bars.

- **P1 skeleton** (`13d31b9`) — Initial project scaffold: FastAPI backend, DuckDB schema (migrations 0001–0005), WHOOP OAuth client, Apple Health CCDA XML ingest, Next.js 15 frontend with shadcn/ui, TanStack Query, Recharts, and synthetic data seeder (90 days).

---

## 2026-04-21 (project start)

- **Initial commit** (`a2f1eed`) — Repository initialised.

---

_Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are date-based (no semver) since this is a single-user tool with no public API contract._
