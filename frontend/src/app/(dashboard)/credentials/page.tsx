import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, Credential } from "@/lib/api";
import { CredentialsVaultClient } from "@/components/credentials-vault-client";

export default async function CredentialsPage() {
  const token = await getAccessToken();

  let websites: Website[] = [];
  try {
    websites = await api.get<Website[]>("/api/v1/websites/", token ?? "");
  } catch { /* ignore */ }

  const credsByWebsite: Record<string, Credential[]> = {};
  if (websites.length > 0) {
    const results = await Promise.allSettled(
      websites.map((s) =>
        api.get<Credential[]>(`/api/v1/websites/${s.id}/credentials/`, token ?? "")
      )
    );
    results.forEach((r, i) => {
      credsByWebsite[websites[i].id] = r.status === "fulfilled" ? r.value : [];
    });
  }

  return (
    <CredentialsVaultClient
      websites={websites}
      credsByWebsite={credsByWebsite}
    />
  );
}
