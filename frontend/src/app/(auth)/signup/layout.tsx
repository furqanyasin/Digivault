import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Create your free account",
  description: "Sign up for Stacks Monitor and monitor your first client website free. No card needed.",
  alternates: { canonical: "/signup" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
