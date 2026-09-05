"use client";

/**
 * ⌘K palette over the section manifest.
 *
 * ~40 panels across 4 surfaces is past the point where a tab bar can make
 * anything findable, so the answer to "where did X go" is search. This reads
 * `lib/sections.ts` — the same list the pages render from — so a result can
 * never point at a section that isn't there.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { SECTIONS, SURFACES, hrefFor, type Section, type Surface } from "@/lib/sections";

function reducedMotion(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Do the chars of `needle` appear in `hay`, in order? */
function subsequence(hay: string, needle: string): boolean {
  if (needle.length === 0) return true;
  let i = 0;
  for (let h = 0; h < hay.length; h++) {
    if (hay[h] === needle[i] && ++i === needle.length) return true;
  }
  return false;
}

/**
 * Higher is a better match. Ordering matters more than the absolute numbers:
 * an exact prefix on the label beats a keyword hit beats a loose subsequence,
 * so typing "vol" leads with Volume rather than with whatever merely contains
 * a v, an o and an l.
 */
function score(section: Section, surfaceLabel: string, q: string): number {
  const label = section.label.toLowerCase();
  const keywords = (section.keywords ?? []).map((k) => k.toLowerCase());
  const surface = surfaceLabel.toLowerCase();

  if (label.startsWith(q)) return 100;
  if (label.includes(q)) return 80;
  if (keywords.some((k) => k.startsWith(q))) return 65;
  if (keywords.some((k) => k.includes(q))) return 55;
  if (surface.startsWith(q)) return 45;
  if (surface.includes(q)) return 40;

  const tight = q.replace(/\s+/g, "");
  if (subsequence(label.replace(/\s+/g, ""), tight)) return 25;
  if (subsequence([label, ...keywords, surface].join("").replace(/\s+/g, ""), tight)) return 10;
  return 0;
}

interface Group {
  surface: Surface;
  items: Section[];
}

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [shown, setShown] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const restoreFocusTo = useRef<HTMLElement | null>(null);

  const groups: Group[] = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out: Group[] = [];
    for (const surface of SURFACES) {
      const inSurface = SECTIONS.filter((s) => s.surface === surface.id);
      const items = q
        ? inSurface
            .map((s) => ({ s, n: score(s, surface.label, q) }))
            .filter((r) => r.n > 0)
            .sort((a, b) => b.n - a.n)
            .map((r) => r.s)
        : inSurface;
      if (items.length > 0) out.push({ surface, items });
    }
    return out;
  }, [query]);

  const flat: Section[] = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  const close = useCallback(() => {
    setOpen(false);
    setShown(false);
    setQuery("");
    setActive(0);
  }, []);

  const go = useCallback(
    (id: string) => {
      close();
      router.push(hrefFor(id));
      // `router.push` moves the hash via pushState, which fires no hashchange
      // and — when we're already on the target route — performs no scroll. The
      // collapsible sections listen for hashchange to expand themselves, so
      // announce it, then scroll on the next frame once that has landed.
      requestAnimationFrame(() => {
        window.dispatchEvent(new HashChangeEvent("hashchange"));
        document.getElementById(id)?.scrollIntoView({
          behavior: reducedMotion() ? "auto" : "smooth",
          block: "start",
        });
      });
    },
    [close, router],
  );

  // ⌘K / Ctrl-K toggles from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((was) => {
          if (!was) restoreFocusTo.current = document.activeElement as HTMLElement | null;
          return !was;
        });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Focus the input on open, hand focus back on close, and don't let the page
  // behind the backdrop scroll while we're over it.
  useEffect(() => {
    if (!open) {
      restoreFocusTo.current?.focus?.();
      restoreFocusTo.current = null;
      return;
    }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    inputRef.current?.focus();
    if (reducedMotion()) setShown(true);
    else requestAnimationFrame(() => setShown(true));
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  useEffect(() => setActive(0), [query]);

  // Keep the highlight in view as the arrows walk past the fold.
  useEffect(() => {
    itemRefs.current[active]?.scrollIntoView({ block: "nearest" });
  }, [active, groups]);

  if (!open) return null;

  const onFieldKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === "ArrowDown" || (e.key === "Tab" && !e.shiftKey)) {
      e.preventDefault();
      if (flat.length > 0) setActive((i) => (i + 1) % flat.length);
      return;
    }
    if (e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey)) {
      e.preventDefault();
      if (flat.length > 0) setActive((i) => (i - 1 + flat.length) % flat.length);
      return;
    }
    if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
      return;
    }
    if (e.key === "End") {
      e.preventDefault();
      setActive(Math.max(0, flat.length - 1));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const target = flat[active];
      if (target) go(target.id);
    }
  };

  const still = reducedMotion();
  let cursor = -1;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center px-4 pt-[12vh] pb-8"
      style={{
        background: "oklch(0.06 0.004 250 / 0.72)",
        backdropFilter: "blur(3px)",
        opacity: still ? 1 : shown ? 1 : 0,
        transition: still ? undefined : "opacity 120ms ease-out",
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search sections"
        className="w-full max-w-[560px] overflow-hidden flex flex-col"
        style={{
          background: "var(--card)",
          border: "1px solid var(--hairline-strong)",
          borderRadius: "var(--r-md)",
          maxHeight: "min(64vh, 520px)",
          transform: still || shown ? "translateY(0)" : "translateY(-6px)",
          transition: still ? undefined : "transform 140ms ease-out",
        }}
      >
        <div
          className="flex items-center gap-3 px-5 py-4"
          style={{ borderBottom: "1px solid var(--hairline)" }}
        >
          <span
            aria-hidden="true"
            style={{
              fontFamily: "var(--font-data)",
              fontSize: "var(--fs-label)",
              color: "var(--text-faint)",
            }}
          >
            /
          </span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onFieldKey}
            placeholder="Search sections…"
            aria-label="Search sections"
            aria-autocomplete="list"
            aria-controls="command-palette-results"
            aria-activedescendant={flat[active] ? `command-palette-opt-${flat[active].id}` : undefined}
            spellCheck={false}
            autoComplete="off"
            className="flex-1 bg-transparent border-0 outline-none"
            style={{ color: "var(--text-primary)", fontSize: "15px" }}
          />
          <kbd
            className="shrink-0 px-1.5 py-0.5"
            style={{
              fontFamily: "var(--font-data)",
              fontSize: "var(--fs-label)",
              color: "var(--text-faint)",
              border: "1px solid var(--hairline)",
              borderRadius: "4px",
            }}
          >
            esc
          </kbd>
        </div>

        <div
          id="command-palette-results"
          role="listbox"
          aria-label="Sections"
          ref={listRef}
          className="flex-1 overflow-y-auto py-2"
        >
          {flat.length === 0 ? (
            <p
              className="px-5 py-6"
              style={{ color: "var(--text-dim)", fontSize: "13px" }}
            >
              Nothing matches “{query.trim()}”.
            </p>
          ) : (
            groups.map((group) => (
              <div key={group.surface.id} className="pb-1">
                <div
                  className="px-5 pt-3 pb-1.5 uppercase"
                  style={{
                    fontFamily: "var(--font-data)",
                    fontSize: "var(--fs-label)",
                    letterSpacing: "0.09em",
                    color: "var(--text-faint)",
                  }}
                >
                  {group.surface.label}
                </div>
                {group.items.map((section) => {
                  cursor += 1;
                  const index = cursor;
                  const on = index === active;
                  return (
                    <button
                      key={section.id}
                      id={`command-palette-opt-${section.id}`}
                      ref={(el) => {
                        itemRefs.current[index] = el;
                      }}
                      type="button"
                      role="option"
                      aria-selected={on}
                      onMouseMove={() => setActive(index)}
                      onClick={() => go(section.id)}
                      className="w-full flex items-baseline justify-between gap-4 px-5 py-2 text-left"
                      style={{
                        background: on ? "var(--card-hover)" : "transparent",
                        borderLeft: `2px solid ${on ? "var(--sl-accent)" : "transparent"}`,
                        paddingLeft: "18px",
                      }}
                    >
                      <span
                        style={{
                          color: on ? "var(--text-primary)" : "var(--text-muted)",
                          fontSize: "14px",
                        }}
                      >
                        {section.label}
                      </span>
                      <span
                        className="shrink-0 uppercase"
                        style={{
                          fontFamily: "var(--font-data)",
                          fontSize: "var(--fs-label)",
                          letterSpacing: "0.06em",
                          color: "var(--text-faint)",
                        }}
                      >
                        {group.surface.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        <div
          className="flex items-center gap-4 px-5 py-2.5"
          style={{
            borderTop: "1px solid var(--hairline)",
            background: "var(--bg)",
            fontFamily: "var(--font-data)",
            fontSize: "var(--fs-label)",
            color: "var(--text-faint)",
          }}
        >
          <span>↑↓ move</span>
          <span>↵ open</span>
          <span className="ml-auto">⌘K</span>
        </div>
      </div>
    </div>
  );
}
