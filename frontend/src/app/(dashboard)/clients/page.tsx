import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import { ClientsClient } from "@/components/clients-client";

export interface ClientRecord {
  id: string;
  name: string;
  website_url: string;
  domain: string;
  status: "active" | "paused" | "offboarded";
  tier: string;
  hosting_platform: string;
  hosting_platform_other: string;
  hosting_renewal_date: string | null;
  domain_renewal_date: string | null;
  domain_access_location: string;
  website_access_level: string;
  departments: string[];
  running_ppc_ads: string;
  website_built_by_digi: string;
  website_maintained_by_digi: string;
  notes: string;
  notify_desktop: boolean;
  notify_email: boolean;
  created_at: string;
  updated_at: string;
}

export default async function ClientsPage() {
  const token = await getAccessToken();
  const clients = token
    ? await api.getAll<ClientRecord>("/api/v1/clients/", token).catch(() => [] as ClientRecord[])
    : ([] as ClientRecord[]);

  return <ClientsClient initialClients={Array.isArray(clients) ? clients : []} />;
}
