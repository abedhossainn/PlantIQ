import QAGatesClient from "./Client";
import { mockDocuments } from "@/lib/mock";

export const dynamic = "force-static";
export const dynamicParams = false;

export async function generateStaticParams() {
  return mockDocuments.map((doc) => ({ id: doc.id }));
}

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <QAGatesClient docId={id} />;
}
