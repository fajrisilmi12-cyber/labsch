# Contributing

Contributions welcome! LabSCH is a small, focused project. Here's how to help.

## Reporting issues

Open an issue at https://github.com/fajrisilmi12-cyber/labsch/issues

Include:
- LabSCH version (`labschctl health` shows it)
- Server OS + Python version
- Agent OS + Python version (or `.exe` build)
- Steps to reproduce
- Server log snippet (last 50 lines from `/tmp/labsch-api.log`)
- Agent log if available

## Code style

- Python: PEP 8, 4-space indent, type hints where natural
- Bash: `shellcheck` clean
- Markdown: CommonMark + GFM
- One feature per commit, clear message

## Submitting a PR

1. Fork the repo
2. Create a branch (`git checkout -b feature/xyz`)
3. Make your change + add a test if possible
4. Run the smoke test: `python3 server/api.py` then `curl localhost:8080/api/health`
5. Commit with a descriptive message
6. Push + open PR

## Adding a new admin CLI subcommand

The CLI is at `skill/labschctl`. To add a new subcommand:

1. Add the function: `def cmd_xyz(args): ...`
2. Add the parser block: `p_xyz = sub.add_parser("xyz", help="...")`
3. Wire it: `p_xyz.set_defaults(func=cmd_xyz)`
4. Update `SKILL.md` and `README.md`

## Adding a new blocking layer

1. Create `agent/<layer>_blocker.py` with `apply()` and `clear()` functions
2. Add the import + call in `agent/labsch_agent.py`'s `apply_all_layers()`
3. Add a config column if needed (extend `db.py` schema)
4. Test the apply + clear cycle

## License

By contributing, you agree your contributions are licensed under MIT.
