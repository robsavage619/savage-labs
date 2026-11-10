import { redirect } from "next/navigation";

/** /review became /week, then /training when Week split into Training and Recovery. */
export default function Page() {
  redirect("/training");
}
