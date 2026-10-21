"""People in Admin's usage figures without their ids or names in the shared store
(orchestrator decision, 20 Oct 2026: the owner asked "which user is using how much").

- ``models``: this environment's pseudonym key (one row, never answered).
- ``pseudonyms``: the HMAC pseudonym the usage export writes, and names for this
  environment's own pseudonyms, read live for a signed-in control account.
"""
