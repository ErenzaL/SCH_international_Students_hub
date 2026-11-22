import { DocumentReviewPage } from "@/features/admin/review/document-review-page";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DocumentReviewPage id={id} />;
}
