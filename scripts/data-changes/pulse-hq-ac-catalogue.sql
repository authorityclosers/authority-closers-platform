-- Pulse HQ for Authority Closers: the SQL of scripts/data-changes/pulse-hq-ac-catalogue.py.
-- The script fills in the double-underscore tokens; never run this file by hand.
\set ON_ERROR_STOP 1
\pset pager off
begin;
select set_config('pulse.org_id', (select id::text from pulse.org where slug = '__ORG_SLUG__'), true) org;
select set_config('pulse.actor_account', $ac_actor$__ACTOR__$ac_actor$, true) actor;

\echo == BEFORE: the modules document
select version, body, is_active from pulse.tenant_config
 where org_id = pulse.current_org() and doc_kind = 'tenant' and doc_key = 'modules' order by version;
\echo == BEFORE: Pulse HQ catalogue
select category, status, count(*) from pulse.hq_feature where org_id = pulse.current_org()
 group by 1, 2 order by 1, 2;

do $switch$
declare v_org uuid := pulse.current_org(); v_founder uuid; cur record; next_body jsonb;
begin
  if v_org is null then raise exception 'organisation __ORG_SLUG__ not found'; end if;
  select person_id into v_founder from pulse.people_profile where org_id = v_org and lower(email) = '__FOUNDER_EMAIL__';
  select version, body into cur from pulse.tenant_config
   where org_id = v_org and doc_kind = 'tenant' and doc_key = 'modules' and is_active;
  if cur.body is not null and coalesce(cur.body->'on', '[]'::jsonb) ? 'pulse_hq' then
    raise notice 'pulse_hq is already on (modules version %)', cur.version;
    return;
  end if;
  next_body := coalesce(cur.body, '{"off": []}'::jsonb)
    || jsonb_build_object('on', coalesce(cur.body->'on', '[]'::jsonb) || '["pulse_hq"]'::jsonb);
  update pulse.tenant_config set is_active = false
   where org_id = v_org and doc_kind = 'tenant' and doc_key = 'modules' and is_active;
  insert into pulse.tenant_config(org_id, doc_kind, doc_key, version, body, is_active, created_by)
  values (v_org, 'tenant', 'modules',
    coalesce((select max(version) from pulse.tenant_config
      where org_id = v_org and doc_kind = 'tenant' and doc_key = 'modules'), 0) + 1,
    next_body, true, v_founder);
end $switch$;

with incoming as (
  select * from jsonb_to_recordset($ac_catalogue$__DATA__$ac_catalogue$::jsonb) as f(
    key text, category text, name text, promise text, what text, who text, status text,
    icon text, proof text, sort int)
), up as (
  insert into pulse.hq_feature(org_id, key, category, name, promise, what, who, status, icon, proof, sort, draft, created_by)
  select pulse.current_org(), i.key, i.category, i.name, i.promise, i.what, i.who, i.status, i.icon, i.proof, i.sort, false,
    (select person_id from pulse.people_profile where org_id = pulse.current_org() and lower(email) = '__FOUNDER_EMAIL__')
  from incoming i
  on conflict (org_id, key) do update set category = excluded.category, name = excluded.name,
    promise = excluded.promise, what = excluded.what, who = excluded.who, status = excluded.status,
    icon = excluded.icon, proof = excluded.proof, sort = excluded.sort, archived = false, updated_at = now()
  where (pulse.hq_feature.category, pulse.hq_feature.name, pulse.hq_feature.promise, pulse.hq_feature.what,
         pulse.hq_feature.who, pulse.hq_feature.status, pulse.hq_feature.icon, pulse.hq_feature.proof,
         pulse.hq_feature.sort, pulse.hq_feature.archived)
    is distinct from (excluded.category, excluded.name, excluded.promise, excluded.what, excluded.who,
         excluded.status, excluded.icon, excluded.proof, excluded.sort, false)
  returning (xmax = 0) inserted
), counted as (
  select count(*) filter (where inserted) added, count(*) filter (where not inserted) changed from up
)
insert into pulse.audit_event(org_id, actor_account, action, resource, resource_id, fields, source, changes)
select pulse.current_org(), current_setting('pulse.actor_account'), 'insert', 'hq_feature', 'ac-feature-catalogue',
  array['key', 'category', 'name', 'promise', 'what', 'who', 'status', 'icon', 'proof', 'sort'], 'sync',
  jsonb_build_object('added', added, 'changed', changed, 'features', __COUNT__)
from counted where added + changed > 0
returning changes;

\echo == AFTER: the modules document
select version, body, is_active from pulse.tenant_config
 where org_id = pulse.current_org() and doc_kind = 'tenant' and doc_key = 'modules' order by version;
\echo == AFTER: Pulse HQ catalogue
select category, status, count(*) from pulse.hq_feature where org_id = pulse.current_org()
 group by 1, 2 order by 1, 2;
select count(*) total from pulse.hq_feature where org_id = pulse.current_org();
\echo == AFTER: audit events written in this transaction
select action, resource, resource_id, actor_account, changes from pulse.audit_event
 where org_id = pulse.current_org() and at = now() order by resource;

__END__
\echo __END_NOTE__
