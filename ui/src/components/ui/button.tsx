import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const buttonStyles = cva(
  "inline-flex h-9 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow hover:bg-primary/90",
        outline: "border border-border bg-background shadow-sm hover:bg-accent hover:text-foreground",
        ghost: "hover:bg-accent hover:text-foreground",
        secondary: "bg-secondary text-foreground shadow-sm hover:bg-secondary/80",
      },
      size: {
        default: "h-9 px-3",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-5",
        icon: "h-9 w-9 px-0",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonStyles> & { asChild?: boolean };

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ButtonProps) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      className={cn(buttonStyles({ variant, size }), className)}
      {...props}
    />
  );
}
