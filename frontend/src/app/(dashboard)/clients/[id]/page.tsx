import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import { ClientDetailClient } from "@/components/client-detail-client";
import type { ClientRecord } from "@/app/(dashboard)/clients/page";
import { notFound } from "next/navigation";

type Ctx = { params: Promise<{ id: string }> };

export default async function ClientDetailPage({ params }: Ctx) {
  const { id } = await params;
  const token = await getAccessToken();
  if (!token) return notFound();

  const client = await api.get<ClientRecord>(`/api/v1/clients/${id}/`, token).catch(() => null);
  if (!client) return notFound();

  return <ClientDetailClient client={client} />;
}
