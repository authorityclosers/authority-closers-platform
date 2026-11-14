/**
 * The Reports page's waveform (Dipak's Reports V4 spec, section 4): thin bars
 * whose heights rise and fall like a recording, soft teal, no card behind it.
 * A picture only: not a player, nothing to press, hidden from screen readers.
 * The bars are the V4 prototype's, at its proportions.
 */

import styles from "./report-library.module.css";

/** Each bar's height in a 78-unit box and its strength, left to right. */
const BARS: readonly (readonly [number, number])[] = [
  [19.7, 0.48],
  [19.3, 0.48],
  [14.4, 0.49],
  [18.4, 0.49],
  [21.3, 0.5],
  [22.4, 0.51],
  [23.5, 0.52],
  [18.4, 0.53],
  [20.3, 0.55],
  [25.8, 0.57],
  [28.0, 0.58],
  [31.6, 0.6],
  [25.9, 0.63],
  [23.5, 0.65],
  [32.9, 0.68],
  [36.2, 0.7],
  [43.9, 0.73],
  [37.7, 0.76],
  [31.5, 0.79],
  [40.3, 0.81],
  [44.2, 0.84],
  [56.7, 0.86],
  [50.8, 0.89],
  [41.3, 0.91],
  [43.9, 0.92],
  [48.4, 0.94],
  [63.5, 0.95],
  [59.2, 0.95],
  [47.1, 0.95],
  [40.7, 0.95],
  [46.2, 0.94],
  [59.9, 0.92],
  [58.1, 0.91],
  [45.5, 0.89],
  [38.0, 0.86],
  [37.6, 0.84],
  [47.9, 0.81],
  [48.5, 0.79],
  [38.1, 0.76],
  [33.3, 0.73],
  [27.5, 0.7],
  [34.2, 0.68],
  [36.4, 0.65],
  [29.2, 0.63],
  [26.9, 0.6],
  [19.6, 0.58],
  [24.0, 0.57],
  [26.9, 0.55],
  [22.9, 0.53],
  [22.1, 0.52],
  [16.7, 0.51],
  [18.1, 0.5],
  [21.5, 0.49],
  [19.8, 0.49],
  [19.7, 0.48],
  [16.3, 0.48],
];
const STEP = 5.7;
const WIDTH = 3.2;
const HEIGHT = 78;
export const WAVEFORM_BARS = BARS.length;

export function Waveform() {
  return (
    <div className={styles.waveform} aria-hidden="true" data-waveform="">
      <svg
        viewBox={`0 0 ${(BARS.length - 1) * STEP + WIDTH + 6} ${HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
        focusable="false"
      >
        {BARS.map(([height, strength], index) => (
          <rect
            key={index}
            x={3 + index * STEP}
            y={(HEIGHT - height) / 2}
            width={WIDTH}
            height={height}
            rx={WIDTH / 2}
            opacity={strength}
          />
        ))}
      </svg>
    </div>
  );
}
