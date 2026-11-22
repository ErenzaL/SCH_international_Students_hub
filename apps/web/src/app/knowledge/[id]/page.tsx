import { KnowledgeArticle } from "@/features/knowledge/knowledge-article";

export default async function KnowledgeArticlePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <KnowledgeArticle id={id} />;
}
