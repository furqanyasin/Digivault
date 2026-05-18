import { cookies } from "next/headers";

export async function getAccessToken(): Promise<string | null> {
  const jar = await cookies();
  return jar.get("ss_access")?.value ?? null;
}
