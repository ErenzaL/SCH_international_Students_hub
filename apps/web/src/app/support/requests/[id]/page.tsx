import { RequestDetail } from "@/features/support/request-detail";

export default async function RequestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <RequestDetail id={id} />
    </div>
  );
}
