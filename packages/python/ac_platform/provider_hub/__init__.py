"""Admin's Providers hub (owner, 20 Oct 2026): "just search for a provider name, add, add key
and boom it's there, and all its models listed".

- ``catalogue``: every provider Sales X-Ray may use, with where its console is and how its
  models are listed;
- ``models``: the models each one offers, from OpenRouter's public catalogue, the provider
  registry's adapters and the price sheet;
- ``health``: each provider's spend and failures in this environment;
- ``keys``: a provider's key, sealed for this environment and never answered, and its free
  connection test;
- ``http``: the Admin reads and the key routes.

A key is sealed the moment it arrives; nothing here prints or returns one.
"""
