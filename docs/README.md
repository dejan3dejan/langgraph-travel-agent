# Atlas docs

How Atlas works, with diagrams. These pages assume you have read the top-level
[README](../README.md).

- [architecture.md](architecture.md): system overview and deployment topology, the moving parts and
  how a request flows through them.
- [planning-pipeline.md](planning-pipeline.md): the LangGraph planning pipeline, the deterministic
  interview gate, the parallel research, and the critic loop.
- [streaming.md](streaming.md): the Server-Sent Events streaming contract between the backend and the
  web UI.
- [data-model.md](data-model.md): the PostgreSQL schema and how the tables relate.

The diagrams are Mermaid and render on GitHub. For the production runbook (hosting, environment
variables, migrations, durability) see [DEPLOYMENT.md](../DEPLOYMENT.md).
