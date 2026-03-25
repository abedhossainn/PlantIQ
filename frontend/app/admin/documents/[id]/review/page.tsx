import ReviewClient from "./Client";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReviewClient docId={id} />;
}
