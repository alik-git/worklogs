# API

`worklogs` does not expose a stable public Python API yet. The supported surface
is the `worklogs` command-line interface.

Use `worklogs new` to create dated markdown worklog files:

```bash
worklogs new plan--backend-api--improve-deploy-notes --scope work
```

Public Python helpers will be documented here if the package grows a stable API
outside the CLI.
