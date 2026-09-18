# Hosted Sales Xray challenge credential

The API reads the one external Cloudflare Turnstile challenge secret from the
host file mounted at `/run/ac-sales-xray/challenge-secret`. It does not accept
the secret from an environment value, a Compose bundle, a command argument, an
image or a log. The release-owned environment reference is fixed per
environment:

```text
staging:    /etc/authority-closers/secrets/sales-xray/staging/challenge-secret
production: /etc/authority-closers/secrets/sales-xray/production/challenge-secret
```

The approved Cloudflare/secret-manager operator provisions the file outside
Git and outside the release archive. The final host boundary is:

- every existing parent is a root-owned, non-writable directory with no
  symlink; private `0700` source parents are valid because Docker resolves the
  host-side bind as root;
- the final path is a singly-linked regular file named `challenge-secret`, with
  no symlink in any ancestor;
- the file is no larger than 4 KiB, owned by UID `10001`, GID `0`, and mode
  `0400`.

Use an atomic create-new/rotate operation supplied by the approved secret
delivery process. Do not print or hash the secret, pass it through a shell
argument, or write it into a Compose environment file. A content-free metadata
check may use:

```sh
test -f "$AC_XRAY_CHALLENGE_SECRET_FILE"
test ! -L "$AC_XRAY_CHALLENGE_SECRET_FILE"
test "$(stat -c '%u:%g:%a' -- "$AC_XRAY_CHALLENGE_SECRET_FILE")" = '10001:0:400'
```

The release validator repeats the path, ancestor, regular-file, link-count,
size, ownership and mode checks without opening the secret. Missing or unsafe
metadata blocks hosted Compose activation before the API starts.
