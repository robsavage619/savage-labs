import { redirect } from "next/navigation";

/**
 * Retired. The console boards were a parallel UI that rendered ~20% of the
 * app's content and none of its controls; their two good ideas — a
 * plain-English sentence under every number, and colour spent only when a
 * value leaves its band — were folded into the real surfaces instead.
 */
export default function Page() {
  redirect("/week");
}
