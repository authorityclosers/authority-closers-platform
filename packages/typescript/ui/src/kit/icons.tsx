/**
 * Reuse the shared inline Lucide paths (ISC), preserving Sales X-Ray's SVG
 * classes and automatic aria-hidden without changing @ac/ui/sx's markup.
 */
import * as Icons from "../sx/icons";
import type { IconComponent, IconProps } from "../sx/icons";

export type { IconComponent } from "../sx/icons";

function withLucideMarkup(Icon: IconComponent, name: string) {
  return function KitIcon({ className, ...props }: IconProps) {
    const accessible = Object.keys(props).some(
      (key) => key.startsWith("aria-") || key === "role" || key === "title",
    );
    return (
      <Icon
        className={`lucide lucide-${name}${className ? ` ${className}` : ""}`}
        {...(!props.children && !accessible
          ? { "aria-hidden": "true" as const }
          : {})}
        {...props}
      />
    );
  };
}

export const ArrowDownRight = withLucideMarkup(
  Icons.ArrowDownRight,
  "arrow-down-right",
);
export const ArrowUpRight = withLucideMarkup(
  Icons.ArrowUpRight,
  "arrow-up-right",
);
export const ChevronLeft = withLucideMarkup(Icons.ChevronLeft, "chevron-left");
export const ChevronRight = withLucideMarkup(
  Icons.ChevronRight,
  "chevron-right",
);
export const Info = withLucideMarkup(Icons.Info, "info");
export const Minus = withLucideMarkup(Icons.Minus, "minus");
export const Pencil = withLucideMarkup(Icons.Pencil, "pencil");
export const X = withLucideMarkup(Icons.X, "x");
export const BellRing = withLucideMarkup(Icons.BellRing, "bell-ring");
export const Siren = withLucideMarkup(Icons.Siren, "siren");
