import { Star } from "lucide-react";

/**
 * StarRating — display + interactive star widget.
 *
 * Props:
 *   value:        number (0..5, supports half stars in display mode)
 *   onChange:     (n:number) => void   — if provided, becomes interactive
 *   size:         px size of each star (default 18)
 *   testid:       optional data-testid prefix
 */
export default function StarRating({ value = 0, onChange, size = 18, testid = "star" }) {
  const interactive = typeof onChange === "function";
  return (
    <div className="inline-flex items-center gap-0.5" data-testid={`${testid}-rating`}>
      {[1, 2, 3, 4, 5].map((n) => {
        const filled = value >= n - 0.25;
        const half = !filled && value >= n - 0.75;
        return (
          <button
            type="button"
            key={n}
            tabIndex={interactive ? 0 : -1}
            aria-label={`${n} star${n > 1 ? "s" : ""}`}
            disabled={!interactive}
            onClick={() => interactive && onChange(n)}
            data-testid={`${testid}-${n}`}
            className={`p-0 leading-none ${interactive ? "cursor-pointer hover:scale-110 transition-transform" : "cursor-default"}`}
          >
            <Star
              size={size}
              strokeWidth={1.5}
              className={
                filled ? "fill-amber-400 text-amber-500"
                : half ? "fill-amber-200 text-amber-400"
                : "text-muted-foreground/40"
              }
            />
          </button>
        );
      })}
    </div>
  );
}
