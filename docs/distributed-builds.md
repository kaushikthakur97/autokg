# Distributed builds

`autokg distributed-build` prepares partitioned table artifacts and runs the deterministic v1 compiler for final semantic correctness.

```bash
autokg distributed-build -c autokg.yml --partitions 8 --backend local
```

Output:

```text
gold/distributed_report.json
```

The built-in backend is `local`. The interface is designed for future Ray, Dask, and Spark adapters.

Current guarantees:

- deterministic final graph equals v1 compiler output
- partition files are generated for scalable execution planning
- distributed report records backend, partitions, files, and duration

Future adapters can parallelize row-to-triple mapping while keeping the same final graph contract.
