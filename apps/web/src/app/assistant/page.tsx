import { redirect } from "next/navigation";

/**
 * The separate assistant page was replaced by the floating SCH Assistant on every student page. Old links and
 * bookmarks land on the homepage with the assistant open; a question passed as ?q= is prefilled in the chat.
 */
export default async function AssistantPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q } = await searchParams;
  const question = (q ?? "").trim().slice(0, 2000);
  redirect(question ? `/?ask=${encodeURIComponent(question)}#chat` : "/#chat");
}
