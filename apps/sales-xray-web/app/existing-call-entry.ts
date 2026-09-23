import { UUID } from "./acquisition-client";

export type SalesXraySearchParams = Readonly<
  Record<string, string | string[] | undefined>
>;

/** Accept only one well-formed opaque call selector from the route. */
export function requestedExistingCallId(
  searchParams: SalesXraySearchParams,
): string | null {
  const call = searchParams.call;
  return typeof call === "string" && UUID.test(call) ? call : null;
}
