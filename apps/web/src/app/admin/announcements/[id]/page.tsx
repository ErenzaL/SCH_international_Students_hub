import { AnnouncementAdminDetail } from "@/features/admin/announcements/announcement-admin-detail";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AnnouncementAdminDetail id={id} />;
}
