import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function icon(path: React.ReactNode, viewBox = "0 0 16 16") {
  return function Icon({ size = 16, className, style, ...props }: IconProps) {
    return (
      <svg
        viewBox={viewBox}
        width={size}
        height={size}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
        style={style}
        aria-hidden
        {...props}
      >
        {path}
      </svg>
    );
  };
}

export const CheckIcon = icon(<polyline points="2,8 6,12 14,4" />);

export const XIcon = icon(
  <>
    <line x1="3" y1="3" x2="13" y2="13" />
    <line x1="13" y1="3" x2="3" y2="13" />
  </>
);

export const RefreshIcon = icon(
  <path d="M13.5 2.5A6 6 0 1 1 8 2m5.5.5V6H10" />
);

export const WarningIcon = icon(
  <>
    <path d="M8 1.5 L14.5 13.5 H1.5 Z" strokeWidth={1.4} />
    <line x1="8" y1="6" x2="8" y2="9.5" />
    <circle cx="8" cy="11.5" r="0.6" fill="currentColor" stroke="none" />
  </>
);

export const SparkleIcon = icon(
  <path d="M8 1 L9.2 6.8 L15 8 L9.2 9.2 L8 15 L6.8 9.2 L1 8 L6.8 6.8 Z" strokeWidth={1} />
);

export const BookIcon = icon(
  <>
    <path d="M3 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3V2Z" />
    <line x1="3" y1="14" x2="11" y2="14" />
    <line x1="6" y1="5" x2="10" y2="5" />
    <line x1="6" y1="8" x2="10" y2="8" />
  </>
);

export const ArrowRightIcon = icon(
  <>
    <line x1="2" y1="8" x2="14" y2="8" />
    <polyline points="10,4 14,8 10,12" />
  </>
);

// Sport / modality icons

export const PickleballIcon = icon(
  <>
    <circle cx="6.5" cy="6.5" r="3.5" />
    <line x1="9.5" y1="9.5" x2="13" y2="13" strokeWidth={2.5} strokeLinecap="round" />
    <line x1="11.5" y1="11.5" x2="14" y2="9" strokeWidth={1.5} />
  </>
);

export const TennisIcon = icon(
  <>
    <circle cx="8" cy="8" r="6" />
    <path d="M4 4 Q8 8 4 12" fill="none" />
    <path d="M12 4 Q8 8 12 12" fill="none" />
  </>
);

export const WalkingIcon = icon(
  <>
    <circle cx="9" cy="2.5" r="1.5" fill="currentColor" stroke="none" />
    <path d="M7 5.5 L5.5 10 L8 10 L9 14" strokeWidth={1.4} />
    <path d="M7 5.5 L10 7.5 L12 6" strokeWidth={1.4} />
    <path d="M5.5 10 L4 13.5" strokeWidth={1.4} />
  </>
);

export const RunningIcon = icon(
  <>
    <circle cx="10" cy="2.5" r="1.5" fill="currentColor" stroke="none" />
    <path d="M9 4.5 L7 9 L10 9.5 L8 14" strokeWidth={1.4} />
    <path d="M9 4.5 L12 6.5 L14 5" strokeWidth={1.4} />
    <path d="M7 9 L5 12" strokeWidth={1.4} />
  </>
);

export const CyclingIcon = icon(
  <>
    <circle cx="4.5" cy="11" r="3" />
    <circle cx="11.5" cy="11" r="3" />
    <path d="M8 3 L11.5 8 L4.5 8" strokeWidth={1.4} />
    <circle cx="8" cy="3" r="1" fill="currentColor" stroke="none" />
  </>
);

export const HikingIcon = icon(
  <>
    <path d="M5 14 L7 8 L10 10 L12 5" strokeWidth={1.4} />
    <circle cx="10" cy="3.5" r="1.5" fill="currentColor" stroke="none" />
    <line x1="3" y1="14" x2="13" y2="14" strokeWidth={1.5} />
    <line x1="11" y1="7" x2="14" y2="10" strokeWidth={1.4} />
  </>
);

export const SwimmingIcon = icon(
  <>
    <path d="M1 10 Q3 8 5 10 Q7 12 9 10 Q11 8 13 10 Q15 12 15 10" fill="none" strokeWidth={1.5} />
    <path d="M1 13 Q3 11 5 13 Q7 15 9 13 Q11 11 13 13" fill="none" strokeWidth={1.5} />
    <circle cx="8" cy="4" r="1.5" fill="currentColor" stroke="none" />
    <path d="M8 5.5 L10 8" strokeWidth={1.4} />
  </>
);

export const YogaIcon = icon(
  <>
    <circle cx="8" cy="2.5" r="1.5" fill="currentColor" stroke="none" />
    <path d="M8 4 L8 8" strokeWidth={1.4} />
    <path d="M4 6 L8 8 L12 6" strokeWidth={1.4} />
    <path d="M8 8 L6 13 M8 8 L10 13" strokeWidth={1.4} />
  </>
);

export const MODALITY_ICON: Record<string, React.ComponentType<IconProps>> = {
  pickleball: PickleballIcon,
  tennis: TennisIcon,
  walk: WalkingIcon,
  run: RunningIcon,
  bike: CyclingIcon,
  hike: HikingIcon,
  swim: SwimmingIcon,
  yoga: YogaIcon,
};
