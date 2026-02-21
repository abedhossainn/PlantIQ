import QAGatesClient from "./Client";
import { mockDocuments } from "@/lib/mock";

export const dynamic = "force-static";
export const dynamicParams = false;

export async function generateStaticParams() {
  return mockDocuments.map((doc) => ({ id: doc.id }));
}

export default function Page({ params }: { params: { id: string } }) {
  return <QAGatesClient docId={params.id} />;
}
