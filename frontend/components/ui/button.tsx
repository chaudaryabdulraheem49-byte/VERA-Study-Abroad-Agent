import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  // rounded-[8px]: the system's CTA radius. Cards use 12px; buttons are
  // deliberately tighter - the "developer dialect" the design calls for.
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[12px] text-sm font-semibold leading-none transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        // Cursor Orange, with the documented press colour rather than an
        // opacity fade - the system names #d04200 explicitly.
        default:
          "bg-primary text-primary-foreground hover:bg-primary-hover active:bg-primary-hover disabled:bg-muted disabled:text-muted-foreground",
        outline:
          "border border-border bg-card text-ink hover:bg-surface-soft",
        ghost: "text-ink hover:bg-surface-soft",
        secondary: "bg-secondary text-secondary-foreground hover:bg-surface-strong",
        // Ink-on-cream CTA, the system's "Download for macOS" treatment.
        // White button for use over a saturated feature card.
        "on-color": "bg-background text-ink hover:bg-surface-soft",
      },
      size: {
        default: "h-11 px-5 py-3",
        sm: "h-8 px-3 text-xs",
        lg: "h-12 px-6 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /**
   * Render the child element with the button's styling instead of a <button>.
   *
   * A CTA that navigates must be an anchor: a <button> with an onClick cannot
   * be opened in a new tab, has no href for the browser to show, and is not
   * announced as a link. Radix's Slot is not a dependency here, so this clones
   * the single child and merges the class names.
   */
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, children, ...props }, ref) => {
    const classes = cn(buttonVariants({ variant, size }), className);

    if (asChild && React.isValidElement(children)) {
      const child = children as React.ReactElement<{ className?: string }>;
      return React.cloneElement(child, {
        className: cn(classes, child.props.className),
      });
    }

    return (
      <button ref={ref} className={classes} {...props}>
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
