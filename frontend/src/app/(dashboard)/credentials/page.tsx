import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, Credential } from "@/lib/api";
import { CredentialsVaultClient } from "@/components/credentials-vault-client";

export default async function CredentialsPage() {
  const token = await getAccessToken();

  const [credentials, websites] = await Promise.all([
    api.get<Credential[]>("/api/v1/credentials/", token ?? "").catch(() => [] as Credential[]),
    api.get<Website[]>("/api/v1/websites/", token ?? "").catch(() => [] as Website[]),
  ]);

  return (
    <CredentialsVaultClient
      initialCredentials={credentials}
      websites={websites}
    />
  );
}
