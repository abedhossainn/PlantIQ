import { redirect } from "next/navigation";

export default function RootPage() {
  // Reviewer-friendly landing behavior:
  // Always route root to login so the public URL does not bypass authentication UI.
  redirect("/login");
}
