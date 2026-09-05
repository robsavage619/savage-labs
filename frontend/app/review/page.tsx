import { redirect } from "next/navigation";

/** /review became /week when the app went to four surfaces. */
export default function Page() {
  redirect("/week");
}
