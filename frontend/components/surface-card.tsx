"use client";

import { CardHelp } from "@/components/card-help";
import { ErrorBoundary } from "@/components/error-boundary";
import type { Span } from "@/lib/sections";

/**
 * One card on the Training and Recovery boards. The `id` is the anchor the
 * command palette and every deep link scroll to, so it must match a row in
 * `lib/sections.ts`, the only place section ids are declared.
 *
 * `help` is mandatory: one sentence, plain words, second person. Acronyms go
 * in `helpDetail`, where there is room to define them.
 */
export function SurfaceCard({
  id,
  span,
  label,
  help,
  helpDetail,
  children,
}: {
  id: string;
  span: Span;
  label: string;
  help: string;
  helpDetail?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className={`span-${span} scroll-mt-24`}>
      <CardHelp summary={help}>{helpDetail}</CardHelp>
      <ErrorBoundary label={label}>{children}</ErrorBoundary>
    </section>
  );
}
