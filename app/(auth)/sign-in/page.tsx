"use client";

import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import InputField from "@/components/forms/InputField";
import FooterLink from "@/components/forms/FooterLink";
import { signInWithEmail } from "@/lib/actions/auth.actions";
import { toast } from "sonner";
import { signInEmail } from "better-auth/api";
import { useRouter } from "next/navigation";

const SignIn = () => {
  const router = useRouter();
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SignInFormData>({
    defaultValues: {
      email: "",
      password: "",
    },
    mode: "onBlur",
  });

  const onSubmit = async (data: SignInFormData) => {
    try {
      const result = await signInWithEmail(data);
      if (result.success) {
        // Force a full page reload to ensure cookies are set and session is established
        window.location.href = "/";
      } else {
        toast.error("Sign in failed", {
          description: result.error || "Failed to sign in.",
        });
      }
    } catch (e) {
      console.error(e);
      toast.error("Sign in failed", {
        description: e instanceof Error ? e.message : "Failed to sign in.",
      });
    }
  };

  const handleDemoSignIn = async () => {
    try {
      const { signInAsDemo } = await import("@/lib/actions/auth.actions");
      const result = await signInAsDemo();
      if (result.success) {
        toast.success("Demo mode activated", {
          description: "Welcome! You're signed in as Yosef (Demo)",
        });
        // Force a full page reload to ensure cookies are set and session is established
        window.location.href = "/";
      } else {
        toast.error("Demo sign in failed", {
          description: result.error || "Failed to sign in as demo user.",
        });
      }
    } catch (e) {
      console.error(e);
      toast.error("Demo sign in failed", {
        description:
          e instanceof Error ? e.message : "Failed to sign in as demo user.",
      });
    }
  };

  return (
    <>
      <h1 className="form-title">Welcome back</h1>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
        <InputField
          name="email"
          label="Email"
          placeholder="yosefpetrosh@gmail.com"
          register={register}
          error={errors.email}
          validation={{
            required: "Email is required",
            pattern: /^\w+@\w+\.\w+$/,
          }}
        />

        <InputField
          name="password"
          label="Password"
          placeholder="Enter your password"
          type="password"
          register={register}
          error={errors.password}
          validation={{ required: "Password is required", minLength: 8 }}
        />

        <Button
          type="submit"
          disabled={isSubmitting}
          className="yellow-btn w-full mt-5"
        >
          {isSubmitting ? "Signing In" : "Sign In"}
        </Button>

        <div className="relative my-5">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t border-gray-600" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-gray-900 px-2 text-gray-400">Or</span>
          </div>
        </div>

        <Button
          type="button"
          onClick={handleDemoSignIn}
          className="w-full mt-5 border-2 border-yellow-500 bg-transparent hover:bg-yellow-500/10 text-yellow-500 font-semibold"
        >
          Try Demo Mode
        </Button>
        <p className="text-xs text-gray-500 text-center mt-2">
          Experience the app instantly as Yosef - no sign up needed
        </p>

        <FooterLink
          text="Don't have an account?"
          linkText="Create an account"
          href="/sign-up"
        />
      </form>
    </>
  );
};
export default SignIn;
