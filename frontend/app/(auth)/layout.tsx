export default function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <div className="auth-page min-h-dvh">{children}</div>;
}
