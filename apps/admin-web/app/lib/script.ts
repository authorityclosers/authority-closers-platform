/** Devanagari text (Hindi, Marathi) gets data-script="deva": upright, with more leading. */
export const DEVANAGARI = /[ऀ-ॿ]/;

export const scriptOf = (text: string) =>
  DEVANAGARI.test(text) ? "deva" : undefined;
