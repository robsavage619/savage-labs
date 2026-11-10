"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { hrefFor, surfaceFor } from "@/lib/sections";

/**
 * Retired: Week split into Training and Recovery. Old links carry a section
 * anchor (`/week#sleep`), which only the browser can see, so the redirect runs
 * client-side and resolves the anchor through the sections manifest.
 */
export default function Page() {
  const router = useRouter();
  useEffect(() => {
    const id = window.location.hash.slice(1);
    router.replace(id && surfaceFor(id) ? hrefFor(id) : "/training");
  }, [router]);
  return null;
}
