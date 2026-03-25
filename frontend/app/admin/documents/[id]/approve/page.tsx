import ApproveClient from "./Client";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ApproveClient docId={id} />;
}
