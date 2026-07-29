"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Swal from "sweetalert2";
import { CheckCheck, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  /** Ids of the currently-visible unacknowledged changes. */
  changeIds: string[];
  /** Of those, how many are critical/high — the reason to slow the user down. */
  highRiskCount: number;
}

const swalClasses = {
  popup: "dv-swal",
  confirmButton: "dv-swal-confirm",
  cancelButton: "dv-swal-cancel",
};

/** Acknowledging clears the alerts AND lifts each site's health score, so it is
 *  not a cheap action to fire by accident — hence a real confirmation rather
 *  than a browser confirm(), and an explicit callout when high-risk changes are
 *  in the batch.
 */
export function AcknowledgeAllButton({ changeIds, highRiskCount }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  if (changeIds.length === 0) return null;

  async function run() {
    const n = changeIds.length;
    const warning =
      highRiskCount > 0
        ? `<p style="margin-top:.6rem"><strong>${highRiskCount}</strong> of these are critical or high severity. Acknowledging marks them reviewed and clears the affected sites' <em>critical</em> status.</p>`
        : "";

    const result = await Swal.fire({
      title: `Acknowledge ${n} alert${n === 1 ? "" : "s"}?`,
      html: `<p>This marks every open alert on your dashboard as reviewed and recalculates each site's health score.</p>${warning}`,
      icon: highRiskCount > 0 ? "warning" : "question",
      showCancelButton: true,
      confirmButtonText: `Acknowledge ${n}`,
      cancelButtonText: "Cancel",
      confirmButtonColor: highRiskCount > 0 ? "#dc2626" : "#6d42e5",
      reverseButtons: true,
      focusCancel: true,
      customClass: swalClasses,
    });
    if (!result.isConfirmed) return;

    setBusy(true);
    try {
      const res = await fetch("/api/changes/bulk-acknowledge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ change_ids: changeIds }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail ?? "Request failed");

      await Swal.fire({
        title: "Acknowledged",
        // Report what the server actually did, not what we asked for.
        text: `${data?.updated ?? n} alert${(data?.updated ?? n) === 1 ? "" : "s"} cleared.`,
        icon: "success",
        timer: 1800,
        showConfirmButton: false,
        customClass: swalClasses,
      });
      router.refresh();
    } catch (err) {
      await Swal.fire({
        title: "Could not acknowledge",
        text: err instanceof Error ? err.message : "Something went wrong. Try again.",
        icon: "error",
        confirmButtonText: "Close",
        confirmButtonColor: "#6d42e5",
        customClass: swalClasses,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button variant="outline" size="sm" onClick={run} disabled={busy}>
      {busy ? (
        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
      ) : (
        <CheckCheck className="mr-1.5 h-3.5 w-3.5" />
      )}
      Acknowledge all
    </Button>
  );
}
