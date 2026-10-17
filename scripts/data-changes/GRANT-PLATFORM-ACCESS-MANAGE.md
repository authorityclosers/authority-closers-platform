# Grant platform_access_manage to an operations owner (18 Oct 2026)

Owner order, relayed by Orchestrator 2 on 18 Oct 2026: admin@authorityclosers.com manages platform access, so minute grants (first: the Wise Life pilot, AUT-2076) don't depend on one other account. Approver: suyash.

Production order:
1. Snapshot: `sudo /usr/local/sbin/ac-db-snapshot production before-admin-platform-access`.
2. Make the target an operations owner with the baked tool (preview, then the same command with `--apply`):
   `docker exec ac-application-production-api-1 python -m ac_platform.authorization.operator_data_change add-operations-owner --environment production --allow-production --email admin@authorityclosers.com --command-id <uuid> --approver suyash --issue AUT-2076 --reason "<reason>"`
3. Grant the permission (preview, then `--apply`):
   `docker exec -i ac-application-production-api-1 python - --environment production --allow-production --email admin@authorityclosers.com --command-id <uuid> --approver suyash --issue AUT-2076 --reason "<reason>" < scripts/data-changes/grant-platform-access-manage.py`
4. Read back through the API: `GET /v1/admin/conversation-minute-accounts/{tenant}/{person}` with an admin@ session answers 200, not 403.
5. Log before/after, command ids and the approver on AUT-2076.

Same command id and intent on retry. A replay is a no-op; different intent is refused. Revoke through the existing capability CLI `revoke` by a platform access manager.
