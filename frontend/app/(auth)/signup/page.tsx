"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export default function SignUpPage() {
  const { signUp } = useAuth();
  const router = useRouter();

  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");

    const formData = new FormData(e.currentTarget);
    const first_name = formData.get("first_name")?.toString().trim() || "";
    const last_name = formData.get("last_name")?.toString().trim() || "";
    const email = formData.get("email")?.toString().trim() || "";
    const password = formData.get("password")?.toString() || "";

    // Client-side validation matching backend constraints
    if (first_name.length < 1 || first_name.length > 100) {
      setError("First name must be between 1 and 100 characters.");
      return;
    }
    if (last_name.length < 1 || last_name.length > 100) {
      setError("Last name must be between 1 and 100 characters.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password.length > 72) {
      setError("Password must be at most 72 characters.");
      return;
    }

    setIsLoading(true);

    try {
      await signUp({ first_name, last_name, email, password });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign up failed");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="shadow-input mx-auto w-full max-w-md rounded-lg bg-white p-5 pb-4 md:p-8 md:pb-4 dark:bg-black">
      <h2 className="text-xl font-bold text-neutral-800 dark:text-neutral-200">
        Create your account
      </h2>
      <p className="mt-2 max-w-sm text-sm text-neutral-600 dark:text-neutral-300">
        Sign up with your name, email, and password.
      </p>

      {error && (
        <div className="mt-4 rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      <form className="mt-8 mb-0" onSubmit={handleSubmit}>
        <div className="mb-4 flex flex-col space-y-2 md:flex-row md:space-y-0 md:space-x-2">
          <LabelInputContainer>
            <Label htmlFor="first_name">First name</Label>
            <Input
              id="first_name"
              name="first_name"
              placeholder="John"
              required
              type="text"
              maxLength={100}
              autoComplete="given-name"
            />
          </LabelInputContainer>
          <LabelInputContainer>
            <Label htmlFor="last_name">Last name</Label>
            <Input
              id="last_name"
              name="last_name"
              placeholder="Doe"
              required
              type="text"
              maxLength={100}
              autoComplete="family-name"
            />
          </LabelInputContainer>
        </div>

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
            autoComplete="new-password"
            id="password"
            name="password"
            placeholder="Min. 8 characters"
            required
            type="password"
            minLength={8}
            maxLength={72}
          />
        </LabelInputContainer>

        <button
          className="group/btn relative block h-10 w-full rounded-md bg-gradient-to-br from-black to-neutral-700 font-medium text-white shadow-[0px_1px_0px_0px_#ffffff40_inset,0px_-1px_0px_0px_#ffffff40_inset] disabled:cursor-not-allowed disabled:opacity-70 dark:bg-zinc-800 dark:from-zinc-900 dark:to-zinc-900 dark:shadow-[0px_1px_0px_0px_#27272a_inset,0px_-1px_0px_0px_#27272a_inset]"
          disabled={isLoading}
          type="submit"
          id="signup-submit"
        >
          {isLoading ? "Please wait..." : "Sign up"}
          <BottomGradient />
        </button>
      </form>

      <p className="mt-5 text-center text-sm text-neutral-300">
        Already have an account?{" "}
        <button
          className="font-medium text-white underline bg-transparent border-none cursor-pointer p-0"
          onClick={() => router.push("/signin")}
        >
          Sign in
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
