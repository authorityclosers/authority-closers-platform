/** Two letters for a person's avatar: from the name, else the email; "" when neither says. */
export function accountInitials(name: string | null, email: string | null) {
  const source = name?.trim() || email?.split("@")[0] || "";
  const parts = source.split(/\s+/).filter(Boolean);
  const letters =
    parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2);
  // Nothing to take initials from: the caller shows a person instead.
  return letters.toUpperCase();
}
