/** Same bounds as CrossAppHandoffStartRequest; do not normalize unsafe paths. */
export function reflexRequest(search: string) {
  const query = new URLSearchParams(search);
  const challenge = query.get("challenge");
  const return_path = query.get("return") ?? "/home";
  if (
    query.getAll("challenge").length !== 1 ||
    query.getAll("return").length > 1 ||
    !challenge ||
    !/^[A-Za-z0-9_-]{43}$/.test(challenge) ||
    !return_path.startsWith("/") ||
    return_path.startsWith("//") ||
    [...return_path].length > 512 ||
    /[\\\u0000-\u001f\u007f-\u009f]/.test(return_path)
  )
    return null;
  return { target: "learner" as const, challenge, return_path };
}
