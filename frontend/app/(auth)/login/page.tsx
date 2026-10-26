import { Suspense } from "react";

import { AuthForm } from "@/components/auth/auth-form";

export const metadata = {
  title: "Log in — Orbitly",
};

export default function Page() {
  // useSearchParams needs a Suspense boundary, or the whole route opts out of
  // static rendering and Next refuses to build it.
  return (
    <Suspense fallback={<div className="h-80" />}>
      <AuthForm mode="login" />
    </Suspense>
  );
}
