import { LoginForm } from "@/features/auth/login-form";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string; as?: string }> }) {
  const { next, as } = await searchParams;
  return (
    <div className="mx-auto max-w-md px-4 py-12">
      <LoginForm next={next} as={as} />
    </div>
  );
}
