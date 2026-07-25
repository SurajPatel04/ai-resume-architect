"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export default function SignInPage() {
  const { signIn } = useAuth();
  const router = useRouter();

  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    const formData = new FormData(e.currentTarget);
    const email = formData.get("email")?.toString().trim() || "";
    const password = formData.get("password")?.toString() || "";

    try {
      await signIn({ email, password });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="shadow-input mx-auto w-full max-w-md rounded-lg bg-white p-5 pb-4 md:p-8 md:pb-4 dark:bg-black">
      <h2 className="text-xl font-bold text-neutral-800 dark:text-neutral-200">
        Welcome back
      </h2>
      <p className="mt-2 max-w-sm text-sm text-neutral-600 dark:text-neutral-300">
        Sign in with your email and password.
      </p>

      {error && (
        <div className="mt-4 rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      <form className="mt-8 mb-0" onSubmit={handleSubmit}>
        <LabelInputContainer className="mb-4">
          <Label htmlFor="email">Email Address</Label>
          <Input
            autoComplete="email"
            id="email"
            name="email"
            placeholder="you@example.com"
            required
            type="email"
          />
        </LabelInputContainer>

        <LabelInputContainer className="mb-4">
          <Label htmlFor="password">Password</Label>
          <Input
            autoComplete="current-password"
            id="password"
            name="password"
            placeholder="••••••••"
            required
            type="password"
          />
        </LabelInputContainer>

        <button
          className="group/btn relative block h-10 w-full rounded-md bg-gradient-to-br from-black to-neutral-700 font-medium text-white shadow-[0px_1px_0px_0px_#ffffff40_inset,0px_-1px_0px_0px_#ffffff40_inset] disabled:cursor-not-allowed disabled:opacity-70 dark:bg-zinc-800 dark:from-zinc-900 dark:to-zinc-900 dark:shadow-[0px_1px_0px_0px_#27272a_inset,0px_-1px_0px_0px_#27272a_inset]"
          disabled={isLoading}
          type="submit"
          id="signin-submit"
        >
          {isLoading ? "Please wait..." : "Sign in"}
          <BottomGradient />
        </button>
      </form>

      <p className="mt-5 text-center text-sm text-neutral-300">
        Need an account?{" "}
        <button
          className="font-medium text-white underline bg-transparent border-none cursor-pointer p-0"
          onClick={() => router.push("/signup")}
        >
          Sign up
        </button>
      </p>
    </div>
  );
}

const BottomGradient = () => {
  return (
    <>
      <span className="absolute inset-x-0 -bottom-px block h-px w-full bg-gradient-to-r from-transparent via-cyan-500 to-transparent opacity-0 transition duration-500 group-hover/btn:opacity-100" />
      <span className="absolute inset-x-10 -bottom-px mx-auto block h-px w-1/2 bg-gradient-to-r from-transparent via-indigo-500 to-transparent opacity-0 blur-sm transition duration-500 group-hover/btn:opacity-100" />
    </>
  );
};

const LabelInputContainer = ({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) => {
  return (
    <div className={cn("flex w-full flex-col space-y-2", className)}>
      {children}
    </div>
  );
};
