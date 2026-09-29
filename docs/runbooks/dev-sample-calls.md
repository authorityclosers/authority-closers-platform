# Dev sample calls

Use the dev API environment file and an existing account that signed in once:

```sh
uv run python -m ac_platform.development.sales_xray_samples --email <dev-email> --count 3 --acknowledge-dev-samples
```

The command refuses every target except the pinned loopback dev database and dev Sales Xray origin. It creates synthetic tone audio and uses a local deterministic provider fake with no network and zero provider cost. It skips completed labels when run again.

Reports are fictional test fixtures. They are not official scores or evaluations. The CLI does not create or change the account profile or credentials.
