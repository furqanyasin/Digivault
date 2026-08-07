import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website } from "@/lib/api";
import { ClientDetailClient } from "@/components/client-detail-client";
import type { ClientRecord } from "@/app/(dashboard)/clients/page";
import { notFound } from "next/navigation";

type Ctx = { params: Promise<{ id: string }> };

export default async function ClientDetailPage({ params }: Ctx) {
  const { id } = await params;
  const token = await getAccessToken();
  if (!token) return notFound();

  // The websites viewset has no ?client= filter and the list is team-scoped and
  // small, so fetch it and match here rather than adding a backend param. A
  // failed fetch degrades to an empty list — the client's own details still load.
  const [client, websitesResult] = await Promise.all([
    api.get<ClientRecord>(`/api/v1/clients/${id}/`, token).catch(() => null),
    api.getAll<Website>("/api/v1/websites/", token).catch(() => [] as Website[]),
  ]);
  if (!client) return notFound();

  const websites = websitesResult.filter((w) => w.client === id);

  return <ClientDetailClient client={client} websites={websites} />;
}
