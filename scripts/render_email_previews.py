"""Render the approved AC alpha transactional email family for visual QA."""

from __future__ import annotations

import argparse
from pathlib import Path

from ac_platform.providers.ports import EmailMessage
from ac_platform.providers.resend_email import render_email


def _messages(base_url: str) -> tuple[tuple[str, EmailMessage], ...]:
    origin = base_url.rstrip("/")
    common = {
        "first_name": "Alex",
        "expires_at": "2026-09-01T18:30:00+00:00",
    }
    return (
        (
            "01-email-verification",
            EmailMessage(
                to="alex@example.test",
                template="identity-email-verification",
                idempotency_key="preview/email-verification",
                variables={
                    **common,
                    "action_link": f"{origin}/verify-email#token=PREVIEW_ONLY_NOT_A_CREDENTIAL",
                },
                communication_class="verification_security",
            ),
        ),
        (
            "02-password-reset",
            EmailMessage(
                to="alex@example.test",
                template="identity-password-reset",
                idempotency_key="preview/password-reset",
                variables={
                    **common,
                    "action_link": f"{origin}/reset-password#token=PREVIEW_ONLY_NOT_A_CREDENTIAL",
                },
                communication_class="verification_security",
            ),
        ),
        (
            "03-course-access-welcome",
            EmailMessage(
                to="alex@example.test",
                template="enrollment-welcome",
                idempotency_key="preview/enrollment-welcome",
                variables={
                    "first_name": "Alex",
                    "action_link": f"{origin}/home",
                },
                communication_class="enrollment_welcome_next_action",
            ),
        ),
    )


def render_previews(output_dir: Path, *, base_url: str) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered_paths: list[Path] = []
    links: list[str] = []
    for stem, message in _messages(base_url):
        rendered = render_email(message)
        path = output_dir / f"{stem}.html"
        path.write_text(rendered.html, encoding="utf-8")
        rendered_paths.append(path)
        links.append(
            f'<li><a href="{path.name}">{rendered.subject}</a>'
            f"<span>{message.communication_class} · "
            f"template v{message.template_version}</span></li>"
        )
    index = output_dir / "index.html"
    index.write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Authority Closers email previews</title><style>"
        "body{margin:0;background:#f3f6fb;color:#0f1b33;font-family:Inter,system-ui,sans-serif}"
        "main{width:min(760px,calc(100% - 32px));margin:0 auto;padding:56px 0}"
        "p{color:#5e6878;line-height:1.6}ul{display:grid;gap:12px;padding:0;list-style:none}"
        "li{display:grid;gap:6px;padding:18px;border:1px solid #dfe5ee;"
        "border-radius:12px;background:#fff}"
        "a{color:#3730a3;font-weight:800;text-decoration:none}span{color:#687386;font-size:12px}"
        "</style></head><body><main><p>Authority Closers · v0.1 evidence</p>"
        "<h1>Transactional email previews</h1>"
        "<p>Static rendering evidence for approved templates. Links contain preview-only values "
        "and do not prove external delivery.</p><ul>"
        + "".join(links)
        + "</ul></main></body></html>",
        encoding="utf-8",
    )
    return (index, *rendered_paths)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/evidence/email-previews/v0.1-auth-family"),
    )
    parser.add_argument(
        "--base-url",
        default="https://staging.authorityclosers.com",
    )
    args = parser.parse_args()
    for path in render_previews(args.output_dir, base_url=args.base_url):
        print(path)


if __name__ == "__main__":
    main()
