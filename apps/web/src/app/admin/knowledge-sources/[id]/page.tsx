import { SourceDetailPage } from "@/features/admin/knowledge/source-detail-page";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SourceDetailPage id={id} />;
}
