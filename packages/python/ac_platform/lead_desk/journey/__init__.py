"""Lead stages per business, and the engine that tells every ad platform about them.

- ``templates``: industry profiles and what each stage means.
- ``model``: the business's own stage list, saved as versions.
- ``mapping``: each platform's match for each stage, confirmed by a person.
- ``providers``: one module per ad platform (Meta first).
- ``engine``: collects stage changes and sends them, with retries and erasure.
- ``http``: the routes under /v1/lead-desk/journey.
"""
