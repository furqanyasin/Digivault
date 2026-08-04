import { redirect } from "next/navigation";

/** My Account merged into Settings. Kept as a redirect so existing bookmarks —
 *  and the "manage your own security in My Account" links that used to point
 *  here — still land somewhere sensible. */
export default function AccountPage() {
  redirect("/settings");
}
