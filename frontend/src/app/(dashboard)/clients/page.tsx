import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import { ClientsClient } from "@/components/clients-client";

export interface ClientRecord {
  id: string;
  name: string;
  website_url: string;
  domain: string;
  status: "active" | "inactive";
  hosting_platform: string;
  hosting_renewal_date: string | null;
  contract_renewal_date: string | null;
  domain_access_location: string;
  migration_status: string;
  csm_migration_confirmation: string;
  running_ppc_ads: string;
  website_built_by_digi: string;
  website_maintained_by_digi: string;
  notes: string;
  comments: string;
  clickup_task_id: string;
  clickup_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export default async function ClientsPage() {
  const token = await getAccessToken();
  const clients = token
    ? await api.get<ClientRecord[]>("/api/v1/clients/", token).catch(() => [] as ClientRecord[])
    : ([] as ClientRecord[]);

  return <ClientsClient initialClients={Array.isArray(clients) ? clients : []} />;
}
