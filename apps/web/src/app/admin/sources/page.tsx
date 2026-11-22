import { redirect } from "next/navigation";

/** Phase 2 moved this page to /admin/knowledge-sources. */
export default function Page() {
  redirect("/admin/knowledge-sources");
}
