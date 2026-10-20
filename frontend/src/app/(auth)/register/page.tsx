import { redirect } from "next/navigation";

// Old URL, kept so existing links still land on the signup form.
export default function RegisterPage() {
  redirect("/signup");
}
