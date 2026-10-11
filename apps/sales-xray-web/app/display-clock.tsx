"use client";

import {
  createContext,
  useContext,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import {
  dayKey,
  INDIA_TIME,
  INDIAN_ENGLISH,
  type DisplayDates,
} from "./display-dates";

/**
 * Dates on screen are the browser's own: its language and time zone. A page
 * the server draws (dev) can't know the zone, so it writes dates in the
 * language the browser asked for, in India time (display-dates.ts). The
 * browser starts from exactly what the server used, so the page keeps its
 * words when the app starts; only where its own language or zone differ
 * does it then rewrite its dates its own way.
 */
const DisplayDatesContext = createContext<DisplayDates | null>(null);

export function DisplayDatesProvider({
  value,
  children,
}: {
  value: DisplayDates | null;
  children: ReactNode;
}) {
  return (
    <DisplayDatesContext.Provider value={value}>
      {children}
    </DisplayDatesContext.Provider>
  );
}

const SEPARATOR = "|";
const keyOf = (dates: DisplayDates) =>
  [dates.locale, dates.timeZone, dates.today].join(SEPARATOR);

let browser: { locale: string; timeZone: string } | null = null;
function browserKey() {
  if (!browser) {
    const options = new Intl.DateTimeFormat().resolvedOptions();
    browser = {
      locale: options.locale || INDIAN_ENGLISH,
      timeZone: options.timeZone || INDIA_TIME,
    };
  }
  return keyOf({
    ...browser,
    today: dayKey(Date.now(), browser.timeZone) as string,
  });
}

const subscribeToNothing = () => () => {};

/** How this screen writes dates now (see above). */
export function useDisplayDates(): DisplayDates {
  const server = useContext(DisplayDatesContext);
  const key = useSyncExternalStore(subscribeToNothing, browserKey, () =>
    keyOf(
      server ?? {
        locale: INDIAN_ENGLISH,
        timeZone: INDIA_TIME,
        today: dayKey(Date.now(), INDIA_TIME) as string,
      },
    ),
  );
  return useMemo(() => {
    const [locale, timeZone, today] = key.split(SEPARATOR);
    return { locale, timeZone, today };
  }, [key]);
}
