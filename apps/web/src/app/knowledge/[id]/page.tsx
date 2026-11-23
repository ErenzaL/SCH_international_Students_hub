import { KnowledgeArticle } from "@/features/knowledge/knowledge-article";

export default async function KnowledgeArticlePage({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<{ page?: string | string[] }>;
}) {
  const { id } = await params;
  const raw = (await searchParams).page;
  const page = Number(Array.isArray(raw) ? raw[0] : raw);
  // ?page=N (a chatbot citation) opens the original PDF at that page
  return <KnowledgeArticle id={id} initialPage={Number.isInteger(page) && page > 0 ? page : undefined} />;
}
